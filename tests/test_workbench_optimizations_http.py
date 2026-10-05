"""HTTP contract checks in disposable runtimes; no live tasks or human evidence."""
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from workbench.maintenance import MaintenanceGate
from workbench.workbench_server import WorkbenchApp, make_handler, serve
from workbench.automation import DeliveryAutomation
from workbench.workbench_backup import RESTORE_MARKER


SPEC = '## 来源\n隔离测试\n## 目标\n检查接口\n## 非目标\n不改业务\n## 约束\n仅复验\n## 验收用例\n请求正确保存\n## 完成定义\n自动测试不代表人审\n'


class WorkbenchOptimizationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / 'runtime'
        self.app = WorkbenchApp(self.runtime)
        self.item = self.app.initiatives.create({'title': 'HTTP test', 'raw_signal': 'test', 'source': 'fixture',
            'project_id': self.app.default_project}, 'fixture')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, method=None, **headers):
        client = HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        encoded = json.dumps(body).encode() if body is not None else None
        client.request(method or ('POST' if body is not None else 'GET'), path, encoded,
                       {'Content-Type': 'application/json', **headers})
        response = client.getresponse()
        raw, status = response.read(), response.status
        content_type = response.getheader('Content-Type', '')
        client.close()
        return status, json.loads(raw) if 'json' in content_type else raw

    def test_unicode_contract_and_escaped_supplementary_characters_are_saved(self):
        service = self.app.initiative_workflow
        path = '/api/v1/initiatives/' + self.item['id'] + '/workflow/v0'
        for extra in ('中' * 12000, '😀' * 23000):
            # Actual parse/freeze/create, with execution launch suppressed.
            spec = SPEC.replace('隔离测试', '隔离测试' + extra)
            with patch.object(service, '_launch', side_effect=lambda data, *rest: service._save(data)):
                state = service.get(self.item['id'])
                status, body = self.request(path, {'actor': 'fixture', 'revision': state['revision'],
                    'spec_text': spec, 'execution_mode': 'verify', 'workspace_path': self.temp.name,
                    'write_scope': [], 'execution_timeout_seconds': 30, 'confirmed': True})
            self.assertEqual(200, status, body)
            task = self.app.tasks.get(body['active_task_id'])
            self.assertEqual(spec, Path(task['spec_path']).read_text(encoding='utf-8'))
            # Restore idle only inside this isolated fixture for the next input.
            state = service._load(self.item['id']); state['stage'] = 'idle'; state['v0'] = False
            service._save(state)

    def test_invalid_contract_and_overlimits_do_not_create_tasks(self):
        path = '/api/v1/initiatives/' + self.item['id'] + '/workflow/v0'
        common = {'actor': 'fixture', 'revision': 0, 'execution_mode': 'verify',
                  'workspace_path': self.temp.name, 'write_scope': [], 'execution_timeout_seconds': 30, 'confirmed': True}
        for spec in ('missing sections', SPEC + '中' * 24000, 'x' * 524288):
            status, _ = self.request(path, {**common, 'spec_text': spec})
            self.assertEqual(400, status)
        self.assertEqual([], self.app.tasks.list())
        status, _ = self.request('/api/v1/initiatives', {'actor': 'fixture', 'data': {'title': '中' * 12000}})
        self.assertEqual(400, status)  # Ordinary initiative limit did not expand.

    def test_backup_create_verify_download_and_cross_origin_rejection(self):
        status, backup = self.request('/api/v1/backups', {'actor': 'fixture'})
        self.assertEqual(201, status, backup)
        status, result = self.request('/api/v1/backups/' + backup['id'] + '/verify', {'actor': 'fixture'})
        self.assertEqual(200, status, result); self.assertTrue(result['ok'])
        status, content = self.request(backup['download_url'])
        self.assertEqual(200, status); self.assertTrue(content.startswith(b'PK'))
        status, _ = self.request('/api/v1/backups', {'actor': 'fixture'}, Origin='https://foreign.example')
        self.assertEqual(403, status)
        self.assertEqual(1, len(self.app.backups.list()['items']))

    def test_backup_web_verify_rejects_paths_before_reading_an_archive(self):
        with patch.object(self.app.backups, 'verify') as verifier:
            for identifier in ('external.zip', r'D:\secret.zip', 'WB-test.zip'):
                status, _ = self.request('/api/v1/backups/' + identifier + '/verify', {'actor': 'fixture'})
                self.assertEqual(400, status)
            verifier.assert_not_called()

    def test_maintenance_preserves_readonly_summary_and_rejects_writer(self):
        with MaintenanceGate(self.runtime).exclusive():
            status, body = self.request('/api/v1/initiatives/home')
            self.assertEqual(200, status, body)
            status, body = self.request('/api/v1/initiatives', {'actor': 'fixture', 'data': {'title': 'not saved'}})
            self.assertEqual(503, status, body)
        self.assertEqual(1, len(self.app.initiatives.list()))
        status, _ = self.request('/api/v1/initiatives/home?home=false')
        self.assertEqual(400, status)

    def test_web_execution_starting_window_blocks_backup_before_task_creation(self):
        self.app.code.plans['test-plan'] = {'state': 'starting'}
        status, body = self.request('/api/v1/backups', {'actor': 'fixture'})
        self.assertEqual(503, status, body)
        self.assertEqual([], self.app.backups.list()['items'])


class WorkbenchRestoreStartupTests(unittest.TestCase):
    def test_restore_marker_prevents_automatic_recovery_but_allows_new_explicit_work(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'runtime'; runtime.mkdir()
            from workbench.task_store import TaskStore
            TaskStore(runtime / 'workbench.db')  # A completed restore includes its database.
            (runtime / RESTORE_MARKER).write_text('{}', encoding='utf-8')
            with patch('workbench.workbench_server.create_http_server') as server, patch.object(DeliveryAutomation, 'recover') as recover:
                serve(port=8098, runtime_dir=runtime, enable_code_execution=True)
                recover.assert_not_called()
                server.return_value.serve_forever.assert_called_once()
            app = WorkbenchApp(runtime, enable_code_execution=True)
            self.assertTrue(app.code.enabled)
            self.assertTrue(app.health()['restored'])

    def test_failed_restore_never_creates_a_new_empty_database(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / 'workbench-restore-failed.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '恢复尚未完成'):
                WorkbenchApp(runtime)
            self.assertFalse((runtime / 'workbench.db').exists())

    def test_instance_identity_survives_restart_and_is_new_after_database_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            first = WorkbenchApp(runtime).health()['runtime_instance']
            self.assertEqual(first, WorkbenchApp(runtime).health()['runtime_instance'])
            (runtime / 'workbench.db').unlink()
            with self.assertRaisesRegex(ValueError, '缺少原数据库'):
                WorkbenchApp(runtime)
            self.assertFalse((runtime / 'workbench.db').exists())
            # Replacing the database is explicit; ordinary startup never does it.
            from workbench.task_store import TaskStore
            TaskStore(runtime / 'workbench.db')
            self.assertNotEqual(first, WorkbenchApp(runtime).health()['runtime_instance'])

    def test_restart_missing_database_preserves_retained_history(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            WorkbenchApp(runtime)
            database = runtime / 'workbench.db'
            retained = runtime / 'workbench-retained.db'
            database.rename(retained)
            original = retained.read_bytes()
            with self.assertRaisesRegex(ValueError, '缺少原数据库'):
                WorkbenchApp(runtime)
            self.assertFalse(database.exists())
            self.assertEqual(original, retained.read_bytes())
            retained.rename(database)
            self.assertTrue(WorkbenchApp(runtime).health()['ready'])

    def test_restore_or_journal_without_database_cannot_bootstrap_empty_history(self):
        for name in (RESTORE_MARKER, 'workbench.db-wal', 'workbench.db-shm', 'workbench.db-journal'):
            with self.subTest(marker=name), tempfile.TemporaryDirectory() as directory:
                runtime = Path(directory)
                marker = runtime / name
                marker.write_bytes(b'preserved fixture evidence')
                with self.assertRaisesRegex(ValueError, '缺少原数据库'):
                    WorkbenchApp(runtime)
                self.assertEqual(b'preserved fixture evidence', marker.read_bytes())
                self.assertFalse((runtime / 'workbench.db').exists())
