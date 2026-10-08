"""Attempt-bound control against real local CLI processes, never a live model."""
import copy
import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_delivery_runtime as runtime_fixtures
from workbench.mutation_receipts import MutationReceipts
from workbench.platform_http import post


class RuntimeControlRevisionTests(unittest.TestCase):
    def setUp(self):
        # Compose the existing fixture; do not inherit and rerun its test suite.
        self.f = runtime_fixtures.DeliveryRuntimeTests(
            'test_pause_ends_owned_process_and_explicit_resume_checks_hash')
        self.addCleanup(self.cleanup_fixture)
        self.f.setUp()
        self.app = SimpleNamespace(initiative_workflow=self.f.workflow,
                                   delivery_runtime=self.f.runtime, advanced_enabled=True,
                                   mutations=MutationReceipts(self.f.tasks))
        self.path = '/api/v1/initiatives/' + self.f.item['id'] + '/runtime/control'

    def cleanup_fixture(self):
        if hasattr(self.f, 'runtime'):
            result = self.f.runtime.close()
            if result['workers_still_stopping']:
                self.f.temp._finalizer.detach()
                self.fail('owned control fixture still stopping; temporary directory retained')
        # Invoke the fixture's registered cleanup callbacks in their original order,
        # so a nested TestCase does not silently consume a cleanup exception.
        while self.f._cleanups:
            function, args, kwargs = self.f._cleanups.pop()
            function(*args, **kwargs)

    def call(self, body):
        return post(self.app, self.path, body, {}, '127.0.0.1')

    def body(self, view, *, action='pause', key='bound-stop'):
        return {'actor': 'owner', 'submission_key': key, 'action': action,
                'expected_revision': view['revision'],
                'candidate_sha256': view.get('candidate_sha256', ''),
                'run_id': view['run_id'], 'session_id': view['session_id'],
                'control_revision': view['control_revision']}

    def background_progress(self):
        with self.f.runtime.lock:
            current = self.f.runtime._load(self.f.item['id'])
            current['subtasks'][0]['progress'] = 'explicit automated progress observation'
            self.f.runtime._save(current)
        return self.f.view()

    @contextmanager
    def held_cli(self):
        worker_type = runtime_fixtures.LocalWorker
        with worker_type.ready_lock:
            self.assertEqual(0, worker_type.active, 'previous fixture CLI remained active')
            worker_type.ready.clear()
        gate = self.f.root / 'manual-control-fixture-release'
        import workbench.execution as execution
        original_spawn = execution.spawn_owned_process
        processes, cli = [], []

        def spawn(command, *args, **kwargs):
            value = original_spawn(command, *args, **kwargs)
            processes.append(value)
            if any('turn.completed' in part for part in command):
                cli.append(value)
            return value

        try:
            with patch.object(worker_type, 'completion_gate', gate), \
                    patch('workbench.execution.spawn_owned_process', side_effect=spawn):
                deadline = time.monotonic() + 10
                self.f.start()
                while time.monotonic() < deadline:
                    with worker_type.ready_lock:
                        if worker_type.ready == {'a.txt', 'b.txt'}:
                            break
                    time.sleep(.01)
                else:
                    self.fail('real control fixture CLI did not reach its two startup markers')
                self.assertEqual(2, len(cli))
                self.assert_live(cli)
                yield cli
        finally:
            event = self.f.runtime.events.get(self.f.item['id'])
            if event:
                event.set()
            worker = self.f.runtime.workers.get(self.f.item['id'])
            if worker:
                worker.join(5)
            # Explicit recovery can touch only the processes captured above.
            for process, owner, _ in processes:
                if process.poll() is None:
                    if owner:
                        owner.close()
                    else:
                        process.kill()
                    process.wait(timeout=5)
            if worker:
                worker.join(5)
                self.assertFalse(worker.is_alive(), 'control fixture worker survived explicit recovery')

    def assert_live(self, cli):
        self.assertTrue(all(process.poll() is None for process, _, _ in cli))
        self.assertFalse(self.f.runtime.events[self.f.item['id']].is_set())

    def wait_stopped(self, cli, expected='paused'):
        worker = self.f.runtime.workers[self.f.item['id']]
        worker.join(5)
        self.assertFalse(worker.is_alive(), 'bound stop did not finish the actual CLI attempt')
        for process, owner, _ in cli:
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)
            if owner:
                self.assertIsNone(owner.handle)
        self.assertEqual(0, runtime_fixtures.LocalWorker.active)
        final = self.f.view()
        self.assertEqual(expected, final['state'])
        self.assertEqual('1', (self.f.repository / 'a.txt').read_text())
        self.assertEqual('1', (self.f.repository / 'b.txt').read_text())
        return final

    def test_route_preserves_actor_binding_and_idempotent_request_identity(self):
        body = {'actor': 'owner', 'submission_key': 'adapter-binding', 'action': 'pause',
                'expected_revision': 7, 'candidate_sha256': 'candidate',
                'run_id': 'run-A', 'session_id': 'session-A', 'control_revision': 3}
        with patch.object(self.f.runtime, 'control', return_value={'state': 'pausing'}) as control:
            self.assertEqual((200, {'state': 'pausing'}), self.call(body))
            self.assertEqual((200, {'state': 'pausing'}), self.call(copy.deepcopy(body)))
            control.assert_called_once_with(self.f.item['id'], 'pause', 'owner', 7, 'candidate',
                                            run_id='run-A', session_id='session-A', control_revision=3)
            with self.assertRaisesRegex(ValueError, 'submission_key'):
                self.call({**body, 'session_id': 'session-B'})
            with self.assertRaises(ValueError):
                self.call({**body, 'actor': '', 'submission_key': 'unsigned'})
            self.assertEqual(1, control.call_count)

    def test_progress_cannot_invalidate_bound_pause_but_legacy_revision_stays_strict(self):
        with self.held_cli() as cli:
            snapshot = self.f.view()
            progressed = self.background_progress()
            self.assertGreater(progressed['revision'], snapshot['revision'])
            self.assertEqual(snapshot['control_revision'], progressed['control_revision'])
            legacy = self.body(snapshot, key='old-legacy-pause')
            for field in ('run_id', 'session_id', 'control_revision'):
                legacy.pop(field)
            with self.assertRaises(ValueError):
                self.call(legacy)
            self.assert_live(cli)
            request = self.body(snapshot)
            code, response = self.call(request)
            self.assertEqual(200, code)
            final = self.wait_stopped(cli)
            self.assertEqual(snapshot['run_id'], final['run_id'])
            self.assertEqual(snapshot['session_id'], final['session_id'])
            self.assertEqual(snapshot['control_revision'] + 1, final['control_revision'])
            self.assertEqual((200, response), self.call(copy.deepcopy(request)))
            events = self.f.runtime.sessions.get_session(final['session_id'])['events']
            self.assertEqual(1, sum(e['kind'] == 'runtime/control' for e in events))

    def test_wrong_attempt_partial_binding_and_old_control_version_keep_cli_alive(self):
        with self.held_cli() as cli:
            snapshot = self.f.view()
            invalid = ({'run_id': 'another-run'}, {'session_id': 'another-session'},
                       {'control_revision': snapshot['control_revision'] - 1},
                       {'control_revision': True}, {'control_revision': '1'},
                       {'session_id': None}, {'run_id': None})
            for index, changed in enumerate(invalid):
                with self.subTest(binding=changed):
                    request = {**self.body(snapshot, key='invalid-binding-' + str(index)), **changed}
                    with self.assertRaises(ValueError):
                        self.call(request)
                    self.assert_live(cli)
                    self.assertEqual(snapshot['control_revision'], self.f.view()['control_revision'])
            request = self.body(self.f.view(), action='cancel', key='current-bound-cancel')
            self.assertEqual(200, self.call(request)[0])
            self.wait_stopped(cli, expected='cancelled')

    def test_resume_binding_cannot_bypass_payload_revision_compare(self):
        with self.held_cli() as cli:
            snapshot = self.f.view()
            self.assertEqual(200, self.call(self.body(snapshot))[0])
            paused = self.wait_stopped(cli)
            progressed = self.background_progress()
            self.assertGreater(progressed['revision'], paused['revision'])
            self.assertEqual(paused['control_revision'], progressed['control_revision'])
            request = self.body(paused, action='resume', key='stale-payload-resume')
            with self.assertRaises(ValueError):
                self.call(request)
            final = self.f.view()
            self.assertEqual('paused', final['state'])
            self.assertEqual(paused['run_id'], final['run_id'])
            self.assertEqual(paused['session_id'], final['session_id'])
            self.assertFalse(self.f.runtime.workers[self.f.item['id']].is_alive())


if __name__ == '__main__':
    unittest.main()
