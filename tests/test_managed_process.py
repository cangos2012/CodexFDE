"""Actual subprocesses, bounded output and startup/cleanup fault injection."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from workbench.deployment_process import OwnedCommand
from workbench.managed_process import ManagedProcess
from workbench.process_guard import WindowsJob


class ManagedProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='workbench-managed-fixture-')
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertTrue(self.root.name.startswith('workbench-managed-fixture-'))
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        deadline = time.monotonic() + 2
        while True:
            self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            self.assertTrue(self.root.name.startswith('workbench-managed-fixture-'))
            try:
                self.temporary.cleanup()
                return
            except PermissionError:
                if time.monotonic() >= deadline: raise
                time.sleep(.05)

    def command(self, code, *args):
        return [sys.executable, '-X', 'utf8', '-u', '-c', code, *map(str, args)]

    def owned(self, code, **kwargs):
        managed = ManagedProcess(self.command(code), self.root, **kwargs)
        self.addCleanup(managed.close)
        return managed

    def assert_closed(self, managed):
        self.assertIsNotNone(managed.process.poll())
        self.assertTrue(all(getattr(managed.process, label).closed for label in ('stdin', 'stdout', 'stderr')))
        self.assertFalse(any(reader.is_alive() for reader in managed.readers))
        self.assertTrue(all(log.closed for log in managed._logs.values()))

    def test_chunk_drain_preserves_large_unicode_output_without_newlines(self):
        managed = self.owned("import sys;sys.stdout.write('中'*700000+'OUT');sys.stdout.flush();sys.stderr.write('文'*700000+'ERR');sys.stderr.flush()",
                             log_dir=self.root)
        managed.start(); managed.process.wait(10)
        self.assertEqual(0, managed.receipt()['returncode'])
        managed.close(); self.assert_closed(managed)
        self.assertEqual('中'*700000+'OUT', (self.root/'stdout.log').read_text(encoding='utf-8'))
        self.assertEqual('文'*700000+'ERR', (self.root/'stderr.log').read_text(encoding='utf-8'))

    def test_owned_command_receipt_has_complete_bounded_tails_for_a_finite_command(self):
        owned = OwnedCommand(self.command("import sys;sys.stdout.write('x'*2097152+'OUT');sys.stdout.flush();sys.stderr.write('y'*2097152+'ERR');sys.stderr.flush()"), self.root)
        self.addCleanup(owned.close)
        owned.process.wait(10)
        receipt = owned.receipt()
        self.assertEqual(0, receipt['returncode'])
        self.assertEqual(('x'*100000+'OUT')[-100000:], receipt['stdout'])
        self.assertEqual(('y'*100000+'ERR')[-100000:], receipt['stderr'])
        owned.close(); owned.close(); self.assert_closed(owned)

    def test_log_open_failure_closes_earlier_handle_and_never_spawns(self):
        opened = []
        original_open = Path.open
        def open_log(path, *args, **kwargs):
            if path.name == 'stderr.log': raise OSError('fixture log open failure')
            stream = original_open(path, *args, **kwargs); opened.append(stream); return stream
        factory = Mock()
        with patch.object(Path, 'open', open_log), self.assertRaisesRegex(OSError, 'log open failure'):
            ManagedProcess(self.command('pass'), self.root, log_dir=self.root, spawn_factory=factory)
        factory.assert_not_called()
        self.assertTrue(opened); self.assertTrue(all(stream.closed for stream in opened))

    def test_spawn_failure_closes_both_prepared_log_handles(self):
        opened = []
        original_open = Path.open
        def open_log(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs); opened.append(stream); return stream
        factory = Mock(side_effect=OSError('fixture spawn failure'))
        with patch.object(Path, 'open', open_log), self.assertRaisesRegex(OSError, 'spawn failure'):
            ManagedProcess(self.command('pass'), self.root, log_dir=self.root, spawn_factory=factory)
        self.assertEqual(2, len(opened)); self.assertTrue(all(stream.closed for stream in opened))

    def test_second_reader_start_failure_closes_started_and_unstarted_resources(self):
        target = self.root/'target-executed'
        managed = self.owned(f"from pathlib import Path;Path({str(target)!r}).write_text('executed');import time;time.sleep(30)", log_dir=self.root)
        original_start = threading.Thread.start
        count = 0
        def start_reader(reader):
            nonlocal count
            count += 1
            if count == 2: raise RuntimeError('fixture second reader failure')
            return original_start(reader)
        with patch.object(threading.Thread, 'start', start_reader), self.assertRaisesRegex(RuntimeError, 'second reader failure'):
            managed.start()
        self.assert_closed(managed)
        if os.name == 'nt': self.assertFalse(target.exists(), 'failed startup must leave the Windows launch gate shut')

    def test_log_write_failure_keeps_draining_and_rejects_receipt_after_child_finishes(self):
        original_open = Path.open
        class FailedLog:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            def write(self, value): raise OSError('fixture disk full')
            def close(self): self.stream.close()
        def open_log(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return FailedLog(stream) if path.name == 'stdout.log' else stream
        done = self.root/'child-finished'
        code = f"import sys;sys.stdout.write('x'*2097152);sys.stdout.flush();sys.stderr.write('y'*2097152);sys.stderr.flush();from pathlib import Path;Path({str(done)!r}).write_text('done')"
        with patch.object(Path, 'open', open_log):
            managed = self.owned(code, log_dir=self.root)
            managed.start(); managed.process.wait(10)
            self.assertTrue(done.is_file(), 'failed log sink must not leave the child blocked on a full pipe')
            with self.assertRaisesRegex(OSError, 'disk full'): managed.receipt()
            managed.close(); self.assert_closed(managed)
        self.assertEqual(2097152, (self.root/'stderr.log').stat().st_size)

    def test_finished_reader_close_error_is_retried_without_losing_output_error(self):
        original_open = Path.open
        class FailedOnceClose:
            def __init__(self, stream): self.stream, self.failed = stream, False
            def __getattr__(self, name): return getattr(self.stream, name)
            def close(self):
                if not self.failed:
                    self.failed = True
                    raise OSError('fixture final log close failure')
                self.stream.close()
        def open_log(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return FailedOnceClose(stream) if path.name == 'stdout.log' else stream
        with patch.object(Path, 'open', open_log):
            managed = self.owned("print('actual fixture output')", log_dir=self.root)
            managed.start(); managed.process.wait(10)
            with self.assertRaisesRegex(OSError, 'final log close failure'): managed.receipt()
            managed.close(); self.assert_closed(managed)
            with self.assertRaisesRegex(OSError, 'final log close failure'): managed.check_output()
            managed.close()

    def test_owner_close_failure_retains_the_same_owner_for_a_cleanup_retry(self):
        managed = self.owned('import time;time.sleep(30)', log_dir=self.root)
        original = managed.owner
        class RetryOwner:
            calls = 0
            def close(self):
                self.calls += 1
                if self.calls == 1: raise OSError('fixture owner close failure')
                if original: original.close()
        owner = RetryOwner(); managed.owner = owner
        try:
            with self.assertRaisesRegex(RuntimeError, 'owner close failure'): managed.close()
            self.assertIs(owner, managed.owner)
            managed.close(); self.assertIsNone(managed.owner); self.assert_closed(managed)
            self.assertEqual(2, owner.calls)
        finally:
            if original: original.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows Job handle retry')
    def test_windows_job_close_failure_preserves_the_native_handle(self):
        owner = WindowsJob(); handle = owner.handle
        closed_by_owner = False
        try:
            with patch.object(owner.api, 'CloseHandle', return_value=False), self.assertRaises(OSError): owner.close()
            self.assertEqual(handle, owner.handle)
            owner.close(); self.assertIsNone(owner.handle)
            closed_by_owner = True
        finally:
            if owner.handle: owner.close()
            elif not closed_by_owner:
                # The red baseline cleared its reference without closing it.
                # Close that actual fixture handle even when its assertion fails.
                owner.api.CloseHandle(handle)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job launch gate')
    def test_close_before_start_never_opens_the_target_launch_gate(self):
        target = self.root/'target-executed'
        managed = self.owned(f"from pathlib import Path;Path({str(target)!r}).write_text('executed')", log_dir=self.root)
        time.sleep(.1)
        self.assertFalse(target.exists()); self.assertIsNone(managed.process.poll())
        managed.close(); self.assert_closed(managed)
        with self.assertRaises(InterruptedError): managed.start()
        self.assertFalse(target.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows Job descendant ownership')
    def test_close_terminates_a_real_descendant_before_returning(self):
        ready, pid_file = self.root/'child-ready', self.root/'child-pid'
        child = f"from pathlib import Path;Path({str(ready)!r}).write_text('ready');import time;time.sleep(30)"
        code = f"import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c',{child!r}]);Path({str(pid_file)!r}).write_text(str(p.pid));time.sleep(30)"
        managed = self.owned(code, capture_limit=1000)
        managed.start()
        deadline = time.monotonic() + 5
        while not ready.is_file() and time.monotonic() < deadline: time.sleep(.02)
        self.assertTrue(ready.is_file())
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, int(pid_file.read_text()))
        self.assertTrue(handle)
        try:
            self.assertEqual(258, kernel.WaitForSingleObject(handle, 0))
            managed.close(); self.assert_closed(managed)
            self.assertEqual(0, kernel.WaitForSingleObject(handle, 1000), 'owned descendant survived close')
        finally: kernel.CloseHandle(handle)
