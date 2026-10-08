import json
import hashlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from workbench.file_io import open_read
from workbench.maintenance import MaintenanceBusy, MaintenanceGate, runtime_write_guard
from workbench.runtime_lease import WorkbenchRuntimeInUse, WorkbenchRuntimeLease
from workbench.task_store import TaskStore
from workbench.workbench_backup import BackupService, RESTORE_MARKER, restore_backup, verify_backup


class WorkbenchBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.store = TaskStore(self.runtime / 'workbench.db')
        task = self.store.create('retain failure evidence', task_id='TASK-ABCD123456')
        self.store.transition(task['id'], 'failed', 'actual fixture failure', actor='tester')
        report = self.runtime / 'reports' / 'failure.json'
        report.parent.mkdir()
        report.write_text('{"decision":"fail"}', encoding='utf-8')
        workspace = self.runtime / 'daily-delivery' / 'plan' / 'workspace'
        workspace.mkdir(parents=True)
        (workspace / 'value.py').write_text('value = 1\n', encoding='utf-8')
        (workspace / '.env').write_text('secret is excluded', encoding='utf-8')
        self.store.append_event(task['id'], 'original report', evidence={'report_path': 'reports/failure.json', 'workspace': str(workspace)})
        self.service = BackupService(self.runtime)

    def tearDown(self):
        self.temp.cleanup()

    def archived(self):
        result = self.service.create('tester')
        archive = self.root / 'saved.zip'
        shutil.copyfile(result['archive_path'], archive)
        return result, archive

    def test_backup_verify_restore_preserve_bytes_and_failure_history(self):
        external = self.root / 'project'; external.mkdir()
        with self.store.connect() as db:
            db.execute('CREATE TABLE projects_fixture(id TEXT, root_path TEXT)')
            db.execute('INSERT INTO projects_fixture VALUES(?,?)', ('project', str(external)))
        result, archive = self.archived()
        original = (self.runtime / 'reports' / 'failure.json').read_bytes()
        verified = verify_backup(archive)
        self.assertTrue(verified['ok'])
        self.assertGreater(verified['files_verified'], 2)
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            self.assertNotIn('payload/daily-delivery/plan/workspace/.env', bundle.namelist())
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertTrue(any(row['path'] == str(external) for row in manifest['external_dependencies']))
        self.runtime.rename(self.root / 'retained-original')
        restored = restore_backup(archive, self.runtime)
        self.assertTrue(restored['ok'])
        self.assertEqual('restored', restored['evidence_restore']['status'])
        self.assertEqual(verified['files_verified'], restored['evidence_restore']['files_verified'])
        self.assertEqual(verified['table_counts'], restored['evidence_restore']['table_counts'])
        self.assertEqual('not_verified', restored['execution_environment']['status'])
        self.assertEqual(original, (self.runtime / 'reports' / 'failure.json').read_bytes())
        self.assertTrue((self.runtime / RESTORE_MARKER).is_file())
        task = TaskStore(self.runtime / 'workbench.db').get('TASK-ABCD123456')
        self.assertEqual('failed', task['status'])
        self.assertEqual('actual fixture failure', task['events'][1]['detail'])
        self.assertFalse(restored['automatic_replay'])

    def test_owned_git_receipts_and_raw_source_listing_survive_restore(self):
        folder = self.runtime / 'git-processes' / 'manifest-call'
        folder.mkdir(parents=True)
        raw = '中文文件'.encode('utf-8') + b'\x00\xff\r\n'
        (folder / 'stdout.bin').write_bytes(raw)
        receipt = json.dumps({'command': ['git', 'ls-files', '-z'], 'returncode': 130,
                              'stdout_sha256': hashlib.sha256(raw).hexdigest(), 'success': False}).encode('utf-8')
        (folder / 'process.json').write_bytes(receipt)
        _, archive = self.archived()
        verified = verify_backup(archive)
        self.assertTrue(verified['ok'])
        self.runtime.rename(self.root / 'retained-original')
        restored = restore_backup(archive, self.runtime)
        self.assertTrue(restored['ok'])
        self.assertEqual(raw, (folder / 'stdout.bin').read_bytes())
        self.assertEqual(receipt, (folder / 'process.json').read_bytes())

    def test_busy_gate_rejects_writes_in_thread_and_other_process(self):
        errors = []
        with MaintenanceGate(self.runtime).exclusive():
            def write():
                try:
                    self.store.append_event('TASK-ABCD123456', 'must not persist')
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=write); thread.start(); thread.join(2)
            self.assertIsInstance(errors[0], MaintenanceBusy)
            script = 'from workbench.maintenance import runtime_write_guard, MaintenanceBusy\nimport sys\ntry:\n with runtime_write_guard(sys.argv[1]): pass\nexcept MaintenanceBusy:\n sys.exit(7)\n'
            completed = subprocess.run([sys.executable, '-c', script, str(self.runtime / 'workbench.db')], capture_output=True)
            self.assertEqual(7, completed.returncode, completed.stderr.decode())
        with runtime_write_guard(self.runtime / 'workbench.db'):
            self.store.append_event('TASK-ABCD123456', 'nested same-thread write works')

    def test_busy_writer_and_busy_tasks_prevent_publishing(self):
        with runtime_write_guard(self.runtime / 'workbench.db'):
            with self.assertRaises(MaintenanceBusy):
                self.service.create('tester')
        with self.assertRaises(MaintenanceBusy):
            self.service.create('tester', busy_check=lambda: True)
        self.store.create('waiting')
        with self.assertRaises(MaintenanceBusy):
            self.service.create('tester')
        self.assertFalse(self.service.list()['items'])

    def test_web_plan_starting_without_task_blocks_backup(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE web_execution_plans(plan_id TEXT PRIMARY KEY, repository TEXT, payload TEXT)')
            db.execute('INSERT INTO web_execution_plans VALUES(?,?,?)',
                       ('pre-task', str(self.root), json.dumps({'state': 'starting', 'task_id': None})))
        with self.assertRaisesRegex(MaintenanceBusy, '网页执行方案'):
            self.service.create('tester')
        self.assertEqual([], self.service.list()['items'])

    def test_busy_callback_is_checked_before_freezing_live_work(self):
        def busy():
            # If exclusive were acquired first, another thread's DB write
            # would be rejected while this supposedly harmless check runs.
            result = []
            def write():
                try:
                    self.store.append_event('TASK-ABCD123456', 'finishing worker')
                    result.append(True)
                except MaintenanceBusy:
                    result.append(False)
            thread = threading.Thread(target=write); thread.start(); thread.join(2)
            self.assertEqual([True], result)
            return True
        with self.assertRaises(MaintenanceBusy):
            self.service.create('tester', busy_check=busy)
        self.assertEqual([], self.service.list()['items'])

    def test_mutation_during_copy_fails_without_final_archive(self):
        original = zipfile.ZipFile.write
        changed = False
        def changing(bundle, filename, *args, **kwargs):
            nonlocal changed
            result = original(bundle, filename, *args, **kwargs)
            if str(filename).endswith('value.py') and not changed:
                Path(filename).write_text('value = 2\n', encoding='utf-8'); changed = True
            return result
        with patch.object(zipfile.ZipFile, 'write', changing):
            with self.assertRaises(MaintenanceBusy):
                self.service.create('tester')
        self.assertEqual([], self.service.list()['items'])

    def test_corrupt_hash_and_path_traversal_are_rejected(self):
        _, archive = self.archived()
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            content = {name: bundle.read(name) for name in bundle.namelist()}
        manifest = json.loads(content['manifest.json'])
        manifest['files']['reports/failure.json']['sha256'] = '0' * 64
        content['manifest.json'] = json.dumps(manifest).encode()
        bad = self.root / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as bundle:
            for name, data in content.items(): bundle.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '校验失败'):
            verify_backup(bad)
        with zipfile.ZipFile(bad, 'a') as bundle:
            bundle.writestr('../escape', b'not allowed')
        with self.assertRaisesRegex(ValueError, '越界'):
            verify_backup(bad)
        self.assertFalse((self.root / 'escape').exists())

    def test_restore_rejects_nonempty_wrong_path_and_running_service(self):
        _, archive = self.archived()
        with self.assertRaisesRegex(ValueError, '必须为空'):
            restore_backup(archive, self.runtime)
        with self.assertRaisesRegex(ValueError, '原绝对路径'):
            restore_backup(archive, self.root / 'different')
        with WorkbenchRuntimeLease(self.runtime):
            with self.assertRaises(WorkbenchRuntimeInUse):
                restore_backup(archive, self.runtime)
        self.assertTrue((self.runtime / 'workbench.db').is_file())

    def test_missing_external_dependency_is_explicit_and_does_not_rewrite_evidence(self):
        missing = self.root / 'missing' / '.git' / 'worktrees' / 'task'
        workspace = self.runtime / 'course-worktrees' / 'TASK-OTHER'
        workspace.mkdir(parents=True)
        (workspace / '.git').write_text('gitdir: ' + str(missing), encoding='utf-8')
        _, archive = self.archived()
        result = verify_backup(archive)
        self.assertIn(str(missing), result['missing_external_dependencies'])
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            self.assertEqual(('gitdir: ' + str(missing)).encode(), bundle.read('payload/course-worktrees/TASK-OTHER/.git'))

    def test_restore_copy_failure_keeps_partial_database_unavailable(self):
        _, archive = self.archived()
        self.runtime.rename(self.root / 'retained-original')
        with patch('workbench.workbench_backup.shutil.copyfile', side_effect=OSError('disk fixture failure')):
            with self.assertRaises(OSError):
                restore_backup(archive, self.runtime)
        self.assertFalse((self.runtime / 'workbench.db').exists())
        self.assertTrue((self.runtime / 'workbench-restore-failed.json').exists())

    def test_missing_internal_reference_blocks_creation(self):
        (self.runtime / 'reports' / 'failure.json').unlink()
        with self.assertRaisesRegex(ValueError, '内部引用缺失'):
            self.service.create('tester')
        self.assertEqual([], self.service.list()['items'])

    def test_original_report_patch_artifact_and_learning_hashes_block_corrupt_source(self):
        path = str(self.runtime / 'reports' / 'failure.json')
        payloads = [
            {'report_path': path, 'report_sha256': '0' * 64},
            {'patch_path': path, 'patch_sha256': '0' * 64},
            {'artifacts': {'stdout': path}, 'artifact_sha256': {'stdout': '0' * 64}},
            {'artifacts': {'report': path}, 'report_sha256': '0' * 64},
            {'source': {'report': {'path': path, 'sha256': '0' * 64}}},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.store.connect() as db:
                    db.execute('CREATE TABLE IF NOT EXISTS learning_assets(id TEXT PRIMARY KEY, payload TEXT)')
                    db.execute('INSERT OR REPLACE INTO learning_assets VALUES(?,?)', ('hash-fixture', json.dumps(payload)))
                with self.assertRaisesRegex(ValueError, '数据库原始哈希不一致'):
                    self.service.create('tester')
                self.assertEqual([], self.service.list()['items'])

    def test_original_hash_binding_is_checked_after_archive_hash_is_recalculated(self):
        report = self.runtime / 'reports' / 'failure.json'
        sha = hashlib.sha256(report.read_bytes()).hexdigest()
        self.store.append_event('TASK-ABCD123456', 'bound original report',
                                evidence={'report_path': str(report), 'report_sha256': sha})
        with self.store.connect() as db:
            db.execute('CREATE TABLE learning_assets(id TEXT PRIMARY KEY, payload TEXT)')
            db.execute('INSERT INTO learning_assets VALUES(?,?)',
                       ('source-fixture', json.dumps({'source': {'report': {'path': str(report), 'sha256': sha}}})))
        _, archive = self.archived()
        self.assertTrue(verify_backup(archive)['ok'])
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            content = {name: bundle.read(name) for name in bundle.namelist()}
        manifest = json.loads(content['manifest.json'])
        corrupted = b'{"decision":"changed after recorded acceptance"}'
        content['payload/reports/failure.json'] = corrupted
        manifest['files']['reports/failure.json'] = {'size': len(corrupted), 'sha256': hashlib.sha256(corrupted).hexdigest()}
        # A rewritten archive manifest must not hide the original DB binding.
        for ref in manifest['references']:
            ref.pop('expected_sha256', None); ref.pop('hash_field', None)
        content['manifest.json'] = json.dumps(manifest).encode()
        bad = self.root / 'rehashed-corruption.zip'
        with zipfile.ZipFile(bad, 'w') as bundle:
            for name, data in content.items(): bundle.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '数据库原始哈希不一致'):
            verify_backup(bad)
        self.runtime.rename(self.root / 'retained')
        with self.assertRaisesRegex(ValueError, '数据库原始哈希不一致'):
            restore_backup(bad, self.runtime)
        self.assertFalse(self.runtime.exists())

    def test_customer_database_inside_owned_candidate_is_external_dependency(self):
        customer = self.runtime / 'daily-delivery' / 'plan' / 'workspace' / 'flowerp.db'
        with sqlite3.connect(customer) as db:
            db.execute('CREATE TABLE inventory(sku TEXT, quantity INTEGER)')
            db.execute("INSERT INTO inventory VALUES('REAL-CUSTOMER-FIXTURE',12)")
        db.close()
        preview = self.runtime / 'candidate-previews' / 'TASK-ABCD123456'
        preview.mkdir(parents=True)
        (preview / 'flowerp.db').write_bytes(b'preview fixture')
        self.store.append_event('TASK-ABCD123456', 'customer data ownership',
                                evidence={'customer_database': str(customer), 'preview_runtime': str(preview)})
        _, archive = self.archived()
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertNotIn('payload/daily-delivery/plan/workspace/flowerp.db', bundle.namelist())
            self.assertTrue(any(row.get('ownership') == 'other_database_not_restored' and row['path'] == str(customer)
                                for row in manifest['external_dependencies']))
            self.assertTrue(any(row.get('ownership') == 'candidate_preview_data_not_restored'
                                for row in manifest['external_dependencies']))
        self.runtime.rename(self.root / 'retained-original')
        result = verify_backup(archive)
        self.assertIn(str(customer), result['missing_external_dependencies'])
        restored = restore_backup(archive, self.runtime)
        self.assertEqual('restored', restored['evidence_restore']['status'])
        self.assertEqual('missing_dependencies', restored['execution_environment']['status'])
        self.assertIn(str(customer), restored['execution_environment']['missing_external_dependencies'])
        self.assertEqual('missing_dependencies', result['execution_environment']['status'])
        self.assertFalse(customer.exists())
        self.assertFalse(preview.exists())

    def test_empty_referenced_directory_is_registered_and_restored_twice(self):
        empty = self.runtime / 'initiative-research' / 'empty-attempt'
        empty.mkdir(parents=True)
        self.store.append_event('TASK-ABCD123456', 'empty attempt retained', evidence={'path': str(empty)})
        _, archive = self.archived()
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
        self.assertIn('initiative-research/empty-attempt', manifest['directories'])
        for iteration in range(2):
            self.runtime.rename(self.root / ('retained-' + str(iteration)))
            restore_backup(archive, self.runtime)
            self.assertTrue(empty.is_dir())
            self.assertEqual([], list(empty.iterdir()))
            self.assertTrue((self.runtime / RESTORE_MARKER).is_file())

    def test_verify_and_restore_rederive_internal_references_from_database(self):
        _, archive = self.archived()
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            content = {name: bundle.read(name) for name in bundle.namelist()}
        manifest = json.loads(content['manifest.json'])
        del content['payload/reports/failure.json']
        del manifest['files']['reports/failure.json']
        # Deleting the reported references must not hide the DB's actual link.
        manifest['references'] = []
        content['manifest.json'] = json.dumps(manifest).encode()
        bad = self.root / 'missing-reference.zip'
        with zipfile.ZipFile(bad, 'w') as bundle:
            for name, data in content.items(): bundle.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '内部引用缺失'):
            verify_backup(bad)
        self.runtime.rename(self.root / 'retained')
        with self.assertRaisesRegex(ValueError, '内部引用缺失'):
            restore_backup(bad, self.runtime)
        self.assertFalse(self.runtime.exists())

    def test_unsafe_directory_metadata_is_rejected(self):
        _, archive = self.archived()
        with open_read(archive, 'rb') as archive_stream, zipfile.ZipFile(archive_stream) as bundle:
            content = {name: bundle.read(name) for name in bundle.namelist()}
        manifest = json.loads(content['manifest.json'])
        manifest['directories'].append('../escape')
        content['manifest.json'] = json.dumps(manifest).encode()
        bad = self.root / 'unsafe-directory.zip'
        with zipfile.ZipFile(bad, 'w') as bundle:
            for name, data in content.items(): bundle.writestr(name, data)
        with self.assertRaisesRegex(ValueError, '越界'):
            verify_backup(bad)

    def test_cli_gate_blocks_file_side_effects_and_bootstrap_before_dispatch(self):
        with self.store.connect() as db:
            original_tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        commands = [
            ['course-prepare', '--runtime-dir', str(self.runtime), '--lesson', '4', '--source', 'working-tree'],
            ['workbench-init', '--runtime-dir', str(self.runtime), '--owner', 'tester'],
            ['course-spec', '--lesson', '4', '--output', str(self.runtime / 'course' / 'blocked.md')],
        ]
        with MaintenanceGate(self.runtime).exclusive():
            for arguments in commands:
                completed = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'workbench.cli', *arguments],
                                           capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(2, completed.returncode, completed.stderr)
                self.assertIn('工作台命令未执行', completed.stderr)
                self.assertNotIn('Traceback', completed.stderr)
        self.assertFalse((self.runtime / 'course-worktrees').exists())
        self.assertFalse((self.runtime / 'course' / 'blocked.md').exists())
        with self.store.connect() as db:
            self.assertEqual(original_tables, db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())


if __name__ == '__main__':
    unittest.main()
