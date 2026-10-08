"""A sharing lock may clear; missing files and persistent denial must fail."""
import errno
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench import file_io

REAL_SLEEP = time.sleep


class FileReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'evidence.txt'
        self.path.write_text('真实证据', encoding='utf-8')

    def test_windows_lock_retry_reads_current_disk_content(self):
        original = Path.open
        calls = []

        def locked(target, *args, **kwargs):
            calls.append(target)
            if len(calls) == 1:
                # A change during the wait must be observed, not replaced by
                # the bytes that happened to be present before the lock.
                with original(target, 'w', encoding='utf-8') as output:
                    output.write('已改变的证据')
                raise PermissionError(errno.EACCES, 'temporary sharing lock')
            return original(target, *args, **kwargs)

        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', locked), \
                patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep:
            self.assertEqual('已改变的证据', file_io.read_text(self.path))
        self.assertEqual(2, len(calls))
        sleep.assert_called_once_with(file_io._READ_DELAYS[0])

    def test_permanent_permission_denial_has_a_finite_budget(self):
        denied = PermissionError(errno.EACCES, 'permanent denial')
        with patch.object(file_io, '_WINDOWS', True), \
                patch.object(Path, 'open', side_effect=denied) as opened, \
                patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep:
            with self.assertRaises(PermissionError) as raised:
                file_io.read_bytes(self.path)
        self.assertIs(denied, raised.exception)
        self.assertEqual(len(file_io._READ_DELAYS) + 1, opened.call_count)
        self.assertEqual(len(file_io._READ_DELAYS), sleep.call_count)

    def test_posix_permission_denial_is_not_retried(self):
        with patch.object(file_io, '_WINDOWS', False), \
                patch.object(Path, 'open', side_effect=PermissionError('denied')) as opened, \
                patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep:
            with self.assertRaises(PermissionError):
                file_io.read_bytes(self.path)
        opened.assert_called_once()
        sleep.assert_not_called()

    def test_missing_file_and_other_io_errors_are_not_retried(self):
        for error in (FileNotFoundError('missing'), OSError(errno.EIO, 'device error')):
            with self.subTest(error=type(error).__name__), patch.object(file_io, '_WINDOWS', True), \
                    patch.object(Path, 'open', side_effect=error) as opened, \
                    patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep:
                with self.assertRaises(type(error)):
                    file_io.read_bytes(self.path)
                opened.assert_called_once()
                sleep.assert_not_called()

    def test_unrelated_windows_error_is_not_retried(self):
        denied = PermissionError('invalid operation')
        denied.winerror = 87
        with patch.object(file_io, '_WINDOWS', True), \
                patch.object(Path, 'open', side_effect=denied) as opened, \
                patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep:
            with self.assertRaises(PermissionError):
                file_io.read_bytes(self.path)
        opened.assert_called_once()
        sleep.assert_not_called()

    def test_write_modes_are_rejected_without_opening_the_file(self):
        for mode in ('w', 'a', 'r+', 'w+b'):
            with self.subTest(mode=mode), patch.object(Path, 'open') as opened:
                with self.assertRaises(ValueError):
                    file_io.open_read(self.path, mode)
                opened.assert_not_called()

    def test_metadata_replacement_retries_without_truncating_previous_file(self):
        original = Path.replace
        calls = []
        def locked(source, target):
            calls.append(source)
            self.assertEqual('真实证据', self.path.read_text(encoding='utf-8'))
            if len(calls) == 1:
                raise PermissionError(errno.EACCES, 'sharing lock on old control file')
            return original(source, target)
        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'replace', locked):
            file_io.atomic_write_text(self.path, '完整的新版本')
        self.assertEqual(2, len(calls))
        self.assertEqual('完整的新版本', self.path.read_text(encoding='utf-8'))

    def test_persistent_metadata_denial_preserves_old_file(self):
        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'replace', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                file_io.atomic_write_text(self.path, '不应安装')
        self.assertEqual('真实证据', self.path.read_text(encoding='utf-8'))
        self.assertEqual([self.path], list(self.path.parent.iterdir()))


if __name__ == '__main__':
    unittest.main()
