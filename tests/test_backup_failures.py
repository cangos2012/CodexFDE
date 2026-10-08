"""Temporary-directory failures; never touch a live runtime or invoke the CLI."""
from datetime import datetime, timezone
import errno
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from workbench.migration import restore_migration
from workbench.reference_paths import unload_reference_mappings
from workbench.task_store import TaskStore
from workbench.workbench_backup import BackupService, RESTORE_MARKER, restore_backup, verify_backup


class BackupFailureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='backup-failures-')
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        self.tasks = TaskStore(self.runtime / 'workbench.db')
        task = self.tasks.create('original failure fixture', task_id='TASK-ABCD123456')
        self.tasks.transition(task['id'], 'failed', 'original failure retained', actor='fixture-user')
        report = self.runtime / 'reports' / 'original.json'
        report.parent.mkdir()
        report.write_bytes(b'{"result":"original failure"}')
        self.tasks.append_event(task['id'], 'original evidence', evidence={'report_path': str(report)})
        self.service = BackupService(self.runtime)

    def tearDown(self):
        self.temporary.cleanup()

    def preserved_original(self):
        backup = self.service.create('fixture-user')
        archive = self.root / 'saved.zip'
        shutil.copyfile(backup['archive_path'], archive)
        retained = self.root / 'retained-original'
        self.runtime.rename(retained)
        original = {path.relative_to(retained).as_posix(): path.read_bytes()
                    for path in retained.rglob('*') if path.is_file()}
        return archive, retained, original

    def assert_retained(self, retained, original):
        for relative, content in original.items():
            self.assertEqual(content, (retained / relative).read_bytes(), relative)

    def assert_startup_blocked(self, runtime):
        from workbench.workbench_server import WorkbenchApp
        database = runtime / 'workbench.db'
        original = database.read_bytes() if database.is_file() else None
        with self.assertRaisesRegex(ValueError, '恢复尚未完成'):
            WorkbenchApp(runtime)
        self.assertEqual(original, database.read_bytes() if database.is_file() else None)

    def test_restore_marker_failure_and_cleanup_denial_still_block_partial_runtime(self):
        archive, retained, original = self.preserved_original()
        original_write = Path.write_text
        original_unlink = Path.unlink
        def full_disk(path, *args, **kwargs):
            if path.parent == self.runtime and path.name.startswith(RESTORE_MARKER):
                raise OSError(errno.ENOSPC, 'fixture disk full')
            return original_write(path, *args, **kwargs)
        def denied_cleanup(path, *args, **kwargs):
            if path == self.runtime / 'workbench.db':
                raise PermissionError(errno.EACCES, 'fixture database cleanup denied')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'write_text', full_disk), patch.object(Path, 'unlink', denied_cleanup):
            with self.assertRaises(OSError) as failure:
                restore_backup(archive, self.runtime)
        self.assertEqual(errno.ENOSPC, failure.exception.errno)
        marker = self.runtime / 'workbench-restore-failed.json'
        self.assertTrue(marker.is_file(), 'Cleanup failure must not remove the startup block')
        recorded = json.loads(marker.read_text(encoding='utf-8'))
        self.assertFalse(recorded['complete'])
        self.assertTrue(any('workbench.db' in error for error in recorded['cleanup_errors']))
        self.assertFalse((self.runtime / 'reports' / 'original.json').exists())
        self.assert_startup_blocked(self.runtime)
        self.assert_retained(retained, original)

    def test_backup_identifier_collision_never_replaces_existing_archive(self):
        class FixedClock:
            @staticmethod
            def now(tz):
                return datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)
        with patch('workbench.workbench_backup.datetime', FixedClock), \
                patch('workbench.workbench_backup.secrets.token_hex', return_value='abcdef012345'):
            first = self.service.create('fixture-first')
            archive = Path(first['archive_path'])
            original = archive.read_bytes()
            with self.assertRaises(FileExistsError):
                self.service.create('fixture-second')
        self.assertEqual(original, archive.read_bytes())
        self.assertEqual('fixture-first', self.service.get(first['id'])['actor'])

    def test_archive_publication_disk_failure_preserves_sources_and_previous_backup(self):
        first = self.service.create('fixture-first')
        archive = Path(first['archive_path'])
        original = archive.read_bytes()
        database = (self.runtime / 'workbench.db').read_bytes()
        report = (self.runtime / 'reports/original.json').read_bytes()
        with patch('workbench.workbench_backup.os.link', side_effect=OSError(errno.ENOSPC, 'fixture disk full')):
            with self.assertRaises(OSError) as failure:
                self.service.create('fixture-second')
        self.assertEqual(errno.ENOSPC, failure.exception.errno)
        self.assertEqual(original, archive.read_bytes())
        self.assertEqual(database, (self.runtime / 'workbench.db').read_bytes())
        self.assertEqual(report, (self.runtime / 'reports/original.json').read_bytes())
        self.assertEqual(1, len(self.service.list()['items']))
        self.assertEqual([], list((self.runtime / 'backups').glob('.WB-*.tmp')))

    def test_success_marker_rename_denial_rolls_back_and_preserves_old_directory(self):
        archive, retained, original = self.preserved_original()
        original_replace = Path.replace
        def denied_marker(path, destination):
            if Path(destination) == self.runtime / RESTORE_MARKER:
                raise PermissionError(errno.EACCES, 'fixture marker rename denied')
            return original_replace(path, destination)
        with patch.object(Path, 'replace', denied_marker):
            with self.assertRaises(PermissionError):
                restore_backup(archive, self.runtime)
        self.assertFalse((self.runtime / 'workbench.db').exists())
        self.assertFalse((self.runtime / RESTORE_MARKER).exists())
        self.assertFalse(json.loads((self.runtime / 'workbench-restore-failed.json').read_text())['complete'])
        self.assert_startup_blocked(self.runtime)
        self.assert_retained(retained, original)

    def test_disk_failure_cannot_remove_preinstalled_startup_block(self):
        archive, retained, original = self.preserved_original()
        original_copy = shutil.copyfile
        original_write = Path.write_text
        def partial_copy(source, destination, *args, **kwargs):
            result = original_copy(source, destination, *args, **kwargs)
            if Path(destination) == self.runtime / 'reports/original.json':
                raise OSError(errno.ENOSPC, 'fixture partial copy disk full')
            return result
        def no_diagnostic_space(path, *args, **kwargs):
            marker = self.runtime / 'workbench-restore-failed.json'
            if path.parent == self.runtime and path.name.startswith(marker.name) and marker.exists():
                raise OSError(errno.ENOSPC, 'fixture diagnostic disk full')
            return original_write(path, *args, **kwargs)
        with patch('workbench.workbench_backup.shutil.copyfile', partial_copy), \
                patch.object(Path, 'write_text', no_diagnostic_space):
            with self.assertRaises(OSError) as failure:
                restore_backup(archive, self.runtime)
        self.assertEqual(errno.ENOSPC, failure.exception.errno)
        marker = json.loads((self.runtime / 'workbench-restore-failed.json').read_text())
        self.assertFalse(marker['complete'])
        self.assertEqual('installing', marker['phase'])
        self.assertFalse((self.runtime / 'workbench.db').exists())
        self.assert_startup_blocked(self.runtime)
        self.assert_retained(retained, original)

    def test_migration_cleanup_denial_keeps_startup_block_and_original_bytes(self):
        archive, retained, original = self.preserved_original()
        target = self.root / 'migration-target'
        original_write = Path.write_text
        original_unlink = Path.unlink
        def full_disk(path, *args, **kwargs):
            if path.parent == target and path.name.startswith(RESTORE_MARKER):
                raise OSError(errno.ENOSPC, 'fixture migration marker disk full')
            return original_write(path, *args, **kwargs)
        def denied_cleanup(path, *args, **kwargs):
            if path == target / 'workbench.db':
                raise PermissionError(errno.EACCES, 'fixture migration cleanup denied')
            return original_unlink(path, *args, **kwargs)
        try:
            with patch.object(Path, 'write_text', full_disk), patch.object(Path, 'unlink', denied_cleanup):
                with self.assertRaises(OSError) as failure:
                    restore_migration(archive, target, {})
            self.assertEqual(errno.ENOSPC, failure.exception.errno)
            marker = json.loads((target / 'workbench-restore-failed.json').read_text())
            self.assertFalse(marker['complete'])
            self.assertTrue(any('workbench.db' in error for error in marker['cleanup_errors']))
            self.assertFalse((target / 'reports/original.json').exists())
            self.assert_startup_blocked(target)
            self.assert_retained(retained, original)
        finally:
            unload_reference_mappings(target)

    def test_duplicate_and_traversal_zip_members_never_modify_original_runtime(self):
        backup = self.service.create('fixture-user')
        database = (self.runtime / 'workbench.db').read_bytes()
        report = (self.runtime / 'reports/original.json').read_bytes()
        with zipfile.ZipFile(backup['archive_path']) as bundle:
            content = {name: bundle.read(name) for name in bundle.namelist()}
        for suffix, unsafe_name in (('duplicate', 'payload/reports/original.json'),
                                    ('traversal', '../escape.txt')):
            with self.subTest(kind=suffix):
                bad = self.root / (suffix + '.zip')
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(bad, 'w') as bundle:
                        for name, data in content.items():
                            bundle.writestr(name, data)
                        bundle.writestr(unsafe_name, b'unsafe fixture')
                for operation in (lambda: verify_backup(bad), lambda: restore_backup(bad, self.runtime)):
                    with self.assertRaisesRegex(ValueError, '重复|越界'):
                        operation()
                self.assertEqual(database, (self.runtime / 'workbench.db').read_bytes())
                self.assertEqual(report, (self.runtime / 'reports/original.json').read_bytes())
                self.assertFalse((self.root / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
