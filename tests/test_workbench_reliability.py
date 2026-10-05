"""Real local sockets and fault injection; no models or human acceptance."""
import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from workbench.http_reliability import WorkbenchHTTPServer
from workbench.maintenance import MaintenanceBusy, MaintenanceGate
from workbench.workbench_server import WorkbenchApp, make_handler, serve


class WorkbenchReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.app = WorkbenchApp(self.runtime)
        self.server = WorkbenchHTTPServer(('127.0.0.1', 0), make_handler(self.app),
                                          max_connections=2, connection_timeout=1)
        self.server.body_timeout = .15
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.app.initiative_workflow.learning_generation.close()
        self.app.delivery_runtime.close()
        self.app.deployments.close()
        self.app.previews.close()

    def request(self, path, body=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request('GET' if body is None else 'POST', path,
                           None if body is None else json.dumps(body), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    def test_readiness_checks_actual_database_and_does_not_recreate_missing_data(self):
        self.assertEqual(200, self.request('/api/health/ready')[0])
        database = self.runtime / 'workbench.db'
        retained = self.runtime / 'workbench-retained.db'
        database.rename(retained)
        self.assertEqual(200, self.request('/api/health/live')[0])
        self.assertEqual(503, self.request('/api/health')[0])
        self.assertEqual(503, self.request('/api/health/ready')[0])
        with patch.object(self.app.projects, 'list') as listing:
            self.assertEqual(503, self.request('/api/v1/projects')[0])
            listing.assert_not_called()
        with patch.object(self.app.initiatives, 'create') as create:
            status, body, _ = self.request('/api/v1/initiatives', {'actor': 'fixture', 'data': {'title': 'blocked'}})
        self.assertEqual(503, status)
        self.assertFalse(body['result_unknown'])
        create.assert_not_called()
        self.assertFalse(database.exists())
        self.assertGreater(retained.stat().st_size, 0)
        for read in (self.app.tasks.list, self.app.initiatives.list, self.app.projects.list):
            with self.assertRaises(sqlite3.OperationalError):
                read()
            self.assertFalse(database.exists())

    def test_corrupt_database_and_restore_marker_fail_readiness(self):
        database = self.runtime / 'workbench.db'
        original = database.read_bytes()
        database.write_bytes(b'corrupt fixture database')
        self.assertEqual(503, self.request('/api/health/ready')[0])
        self.assertEqual(b'corrupt fixture database', database.read_bytes())
        database.write_bytes(original)
        marker = self.runtime / 'workbench-restore-failed.json'
        marker.write_text('{}')
        status, body, _ = self.request('/api/health/ready')
        self.assertEqual(503, status)
        self.assertFalse(body['checks']['recovery']['ok'])

    def test_readiness_is_unavailable_during_maintenance_but_live_stays_readable(self):
        with MaintenanceGate(self.runtime).exclusive():
            self.assertEqual(503, self.request('/api/health/ready')[0])
            self.assertEqual(503, self.request('/api/health')[0])
            self.assertEqual(200, self.request('/api/health/live')[0])
        self.assertEqual(200, self.request('/api/health/ready')[0])

    def test_unfinished_preview_cleanup_blocks_backup_even_after_the_parent_exits(self):
        # An explicit close-failure fixture represents retained ownership/log
        # resources; the parent is already dead and there is no running payload.
        managed = Mock()
        managed.process.poll.return_value = 0
        managed.close.side_effect = [RuntimeError('fixture preview cleanup failed'), None]
        with self.app.previews._process_lock:
            self.app.previews._owned['TASK-CLEANUP-FIXTURE'] = managed
        self.assertEqual({}, self.app.previews.running)
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
            self.app.previews.close()
        self.assertTrue(self.app.previews.busy())
        self.assertTrue(self.app.backup_busy())
        with self.assertRaisesRegex(MaintenanceBusy, '仍有执行'):
            self.app.backups.create('fixture', busy_check=self.app.backup_busy)
        self.assertFalse((self.runtime / 'backups').exists())
        self.app.previews.close()
        self.assertEqual(2, managed.close.call_count)
        self.assertFalse(self.app.previews.busy())
        self.assertFalse(self.app.backup_busy())
        backup = self.app.backups.create('fixture', busy_check=self.app.backup_busy)
        self.assertTrue(Path(backup['archive_path']).is_file())
        self.assertTrue(self.app.backups.verify(backup['archive_path'])['ok'])

    def test_disk_space_blocks_new_actions_without_faking_success(self):
        with patch('workbench.service_health.shutil.disk_usage') as usage:
            usage.return_value.free = 1
            self.assertEqual(503, self.request('/api/health/ready')[0])
            with patch('workbench.platform_http.post') as action:
                self.assertEqual(503, self.request('/api/v1/unknown', {'actor': 'fixture'})[0])
                action.assert_not_called()

    def test_incomplete_body_has_total_deadline_and_creates_no_records(self):
        client = socket.create_connection(self.server.server_address, timeout=3)
        self.addCleanup(client.close)
        client.sendall(b'POST /api/v1/initiatives HTTP/1.0\r\nContent-Type: application/json\r\n'
                       b'Content-Length: 64\r\n\r\n{')
        started = time.monotonic()
        response = client.makefile('rb').read()
        self.assertIn(b'408 Request Timeout', response)
        self.assertIn(b'request_timeout', response)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual([], self.app.initiatives.list())
        self.assertEqual(200, self.request('/api/health/ready')[0])

    def test_conflicting_body_framing_is_rejected_without_dispatch(self):
        for framing in (b'Content-Length: 2\r\nContent-Length: 2',
                        b'Content-Length: 2\r\nTransfer-Encoding: chunked'):
            with socket.create_connection(self.server.server_address, timeout=3) as client:
                with patch('workbench.platform_http.post') as action:
                    client.sendall(b'POST /api/v1/unknown HTTP/1.0\r\nContent-Type: application/json\r\n'
                                   + framing + b'\r\n\r\n{}')
                    response = client.makefile('rb').read()
                    self.assertIn(b'400 Bad Request', response)
                    action.assert_not_called()

    def test_oversized_body_rejections_remain_readable_and_never_dispatch(self):
        cases = (
            ('/api/v1/initiatives', {'actor':'fixture', 'data':{'title':'中' * 12000}}),
            ('/api/v1/initiatives/fixture/workflow/v0', {'actor':'fixture', 'spec_text':'x' * 524288}),
        )
        for path, payload in cases:
            with self.subTest(path=path), patch('workbench.platform_http.post') as action:
                started = time.monotonic()
                client = HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
                try:
                    client.request('POST', path, json.dumps(payload), {'Content-Type':'application/json'})
                    time.sleep(.05)
                    response = client.getresponse()
                    status, body, headers = response.status, json.loads(response.read()), dict(response.getheaders())
                finally:
                    client.close()
                self.assertEqual(400, status)
                self.assertEqual('invalid_body', body['error'])
                self.assertEqual('close', headers['Connection'])
                self.assertLess(time.monotonic() - started, 1.5)
                action.assert_not_called()
        self.assertEqual([], self.app.initiatives.list())
        self.assertEqual(200, self.request('/api/health/ready')[0])

    def test_slow_drip_cannot_extend_total_body_deadline(self):
        handler_class = self.server.RequestHandlerClass
        original_json = handler_class._json
        for attempt in range(3):
            with self.subTest(attempt=attempt), socket.create_connection(self.server.server_address, timeout=3) as client:
                done, response_pending, tail_sent = threading.Event(), threading.Event(), threading.Event()
                def json_with_unread_input(handler, status, body):
                    if status == 408:
                        # Coordinate real unread TCP bytes precisely after the
                        # read deadline, so the former Windows reset is not a
                        # scheduler-dependent race hidden by a passing test.
                        response_pending.set()
                        tail_sent.wait(.5)
                    return original_json(handler, status, body)
                def drip():
                    tail = False
                    while not done.wait(.03):
                        try:
                            if response_pending.is_set() and not tail:
                                client.sendall(b' ' * 32)
                                tail = True
                                tail_sent.set()
                            else:
                                client.sendall(b' ')
                        except OSError:
                            return
                with patch.object(handler_class, '_json', json_with_unread_input), patch('workbench.platform_http.post') as action:
                    client.sendall(b'POST /api/v1/unknown HTTP/1.0\r\nContent-Type: application/json\r\n'
                                   b'Content-Length: 100\r\n\r\n{')
                    sender = threading.Thread(target=drip, daemon=True)
                    sender.start()
                    try:
                        started = time.monotonic()
                        self.assertTrue(tail_sent.wait(1))
                        # A loaded client may not read immediately when the
                        # server rejects its unfinished request. Preserve the
                        # same response and deadline for that real condition.
                        time.sleep(.05)
                        with client.makefile('rb') as reply:
                            response = reply.read()
                        self.assertIn(b'408 Request Timeout', response)
                        self.assertLess(time.monotonic() - started, 1.5)
                        self.assertTrue(tail_sent.is_set())
                        headers, body = response.split(b'\r\n\r\n', 1)
                        content_length = next(line.partition(b':')[2].strip() for line in headers.split(b'\r\n')
                                              if line.lower().startswith(b'content-length:'))
                        self.assertEqual(int(content_length), len(body))
                        result = json.loads(body)
                        self.assertEqual('request_timeout', result['error'])
                        self.assertFalse(result['automatic_replay'])
                        action.assert_not_called()
                    finally:
                        done.set()
                        sender.join(1)
            deadline = time.monotonic() + .5
            while self.server.active_requests and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(0, self.server.active_requests)
        self.assertEqual([], self.app.initiatives.list())
        self.assertEqual(200, self.request('/api/health/ready')[0])

    def test_generation_shutdown_stops_worker_when_database_is_missing(self):
        generation = self.app.initiative_workflow.learning_generation
        event = threading.Event()
        worker = threading.Thread(target=lambda: event.wait(3), daemon=True)
        generation.cancel_events['fixture-generation'] = event
        generation.workers['fixture-generation'] = worker
        worker.start()
        database = self.runtime / 'workbench.db'
        database.rename(self.runtime / 'workbench-retained.db')
        result = generation.close(timeout=.5)
        self.assertFalse(worker.is_alive())
        self.assertIsNotNone(result['storage_error'])
        self.assertFalse(database.exists())

    def test_concurrency_is_bounded_and_capacity_recovers(self):
        sockets = [socket.create_connection(self.server.server_address, timeout=3) for _ in range(2)]
        try:
            deadline = time.monotonic() + .5
            while self.server.active_requests < 2 and time.monotonic() < deadline:
                time.sleep(.005)
            status, body, _ = self.request('/api/health/live')
            self.assertEqual(503, status)
            self.assertEqual('server_busy', body['error'])
            self.assertEqual(2, self.server.active_requests)
            self.assertEqual(1, self.server.rejected_requests)
        finally:
            for client in sockets:
                client.close()
        deadline = time.monotonic() + 1
        while self.server.active_requests and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertEqual(0, self.server.active_requests)
        self.assertEqual(200, self.request('/api/health/live')[0])

    def test_storage_error_returns_traceable_json_without_exposing_error_details(self):
        with patch.object(self.app.projects, 'list', side_effect=sqlite3.OperationalError('secret-fixture-detail')):
            with self.assertLogs('workbench.http', level='ERROR') as logs:
                status, body, headers = self.request('/api/v1/projects')
        self.assertEqual(503, status)
        self.assertEqual('storage_unavailable', body['error'])
        self.assertEqual(body['request_id'], headers['X-Workbench-Request-ID'])
        self.assertEqual('no-store', headers['Cache-Control'])
        self.assertNotIn('secret-fixture-detail', json.dumps(body))
        self.assertIn(body['request_id'], logs.output[0])
        self.assertFalse(body['automatic_replay'])

    def test_exception_after_effect_returns_unknown_result_without_replaying(self):
        receipt = self.runtime / 'effect-fixture.txt'
        def partial_effect(*args):
            receipt.write_text('one effect')
            raise RuntimeError('fixture fails after one side effect')
        with patch('workbench.platform_http.post', side_effect=partial_effect) as action:
            with self.assertLogs('workbench.http', level='ERROR'):
                status, body, _ = self.request('/api/v1/unknown', {'actor': 'fixture'})
        self.assertEqual(500, status)
        self.assertTrue(body['result_unknown'])
        self.assertFalse(body['automatic_replay'])
        self.assertEqual('one effect', receipt.read_text())
        self.assertEqual(1, action.call_count)

    def test_receipt_query_is_readonly_and_never_exposes_approval_or_actor(self):
        operation, key = '/api/v1/initiatives/fixture/runtime/control', 'fixture-receipt-key'
        calls = []
        self.app.mutations.run(operation, key, {'actor': 'fixture signature', 'confirmed': True},
                               lambda: calls.append(1) or {'authorization': 'fixture-sensitive-result'})
        query = '/api/v1/mutations/receipt?' + urlencode({'operation': operation, 'key': key})
        for _ in range(2):
            status, body, _ = self.request(query)
            self.assertEqual(200, status)
            self.assertEqual('completed', body['status'])
            self.assertEqual({'operation', 'key', 'status', 'automatic_replay'}, set(body))
        self.assertEqual([1], calls)
        self.assertEqual('not_found', self.app.mutations.get(operation, 'unknown')['status'])
        with self.app.tasks.connect() as db:
            db.execute('INSERT INTO platform_mutations VALUES(?,?,?,?,NULL)', (operation, 'in-flight', 'fixture', 'pending'))
        self.assertEqual('pending', self.app.mutations.get(operation, 'in-flight')['status'])

    def test_service_shutdown_continues_after_one_cleanup_error(self):
        app = Mock()
        app.runtime, app.erp_url, app.harness_api = self.runtime, 'http://127.0.0.1:8100', None
        sequence = []
        app.initiative_workflow.learning_generation.close.side_effect = RuntimeError('fixture cleanup failed')
        app.delivery_runtime.close.side_effect = lambda: sequence.append('runtime')
        app.deployments.close.side_effect = lambda: sequence.append('deployment')
        app.previews.close.side_effect = lambda: sequence.append('preview')
        server = Mock()
        server.server_close.side_effect = lambda: sequence.append('listener')
        with patch('workbench.workbench_server.WorkbenchApp', return_value=app):
            with patch('workbench.workbench_server.create_http_server', return_value=server):
                with self.assertLogs('workbench.shutdown', level='ERROR'):
                    with self.assertRaisesRegex(RuntimeError, 'fixture cleanup failed'):
                        serve(port=8199, runtime_dir=self.runtime)
        self.assertEqual(['runtime', 'deployment', 'preview', 'listener'], sequence)


if __name__ == '__main__':
    unittest.main()
