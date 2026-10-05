"""Real local pipe behavior; does not contact or impersonate Codex."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workbench.execution import CodexExecutionRunner, spawn_owned_process


class ExecutionStreamTests(unittest.TestCase):
    def assert_start_failure_closes_process(self, failing_target):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CodexExecutionRunner(root, root)
            captured, started_threads = [], []
            actual_start = threading.Thread.start
            counts = {}

            def capture(*args, **kwargs):
                result = spawn_owned_process(*args, **kwargs)
                captured.append(result)
                return result

            def start(thread):
                target = thread._target.__name__
                counts[target] = counts.get(target, 0) + 1
                if (target, counts[target]) == failing_target:
                    raise RuntimeError('fixture stream thread start failure')
                actual_start(thread)
                started_threads.append(thread)

            try:
                with patch('workbench.execution.spawn_owned_process', side_effect=capture), \
                     patch.object(threading.Thread, 'start', start), \
                     self.assertRaisesRegex(RuntimeError, 'thread start failure'):
                    runner._run_codex_streaming(
                        [sys.executable, '-c', "import time;time.sleep(30)"],
                        '', 10, lambda line: None, time.monotonic())
                self.assertEqual(1, len(captured))
                process, owner, _ = captured[0]
                self.assertIsNotNone(process.poll(), 'guard survived failed reader/writer startup')
                self.assertTrue(all(getattr(process, name).closed for name in ('stdin', 'stdout', 'stderr')))
                self.assertTrue(all(not thread.is_alive() for thread in started_threads))
                if owner:
                    self.assertIsNone(owner.handle)
            finally:
                # Reclaim only this fixture's processes even when the old code fails.
                for process, owner, _ in captured:
                    if owner: owner.close()
                    if process.poll() is None: process.kill()
                    process.wait(timeout=5)
                for thread in started_threads: thread.join(5)
                for process, _, _ in captured:
                    for name in ('stdin', 'stdout', 'stderr'):
                        getattr(process, name).close()

    def test_second_reader_start_failure_closes_owned_process_and_pipes(self):
        self.assert_start_failure_closes_process(('drain', 2))

    def test_writer_start_failure_closes_owned_process_and_pipes(self):
        self.assert_start_failure_closes_process(('feed', 1))

    def test_binary_stdout_preserves_nul_crlf_and_non_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CodexExecutionRunner(root, root)
            payload = b'\x00\xff\r\nname\rfile\x00' + '中文'.encode('utf-8')
            callback = Mock()
            result = runner._run_codex_streaming(
                [sys.executable, '-c', f'import sys;sys.stdout.buffer.write({payload!r})'],
                '', 10, callback, time.monotonic(), binary_stdout=True)
            self.assertEqual(0, result.returncode)
            self.assertEqual(payload, result.stdout)
            callback.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows Job owns pipe-holding descendants')
    def test_parent_exit_closes_job_before_waiting_for_descendant_pipe_eof(self):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / 'parent-may-exit'
            runner = CodexExecutionRunner(root, root)
            captured, streams, handles = [], [], []
            actual_start = threading.Thread.start
            script = (
                'import subprocess,sys,time\nfrom pathlib import Path\n'
                'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\n'
                'print(child.pid,flush=True)\n'
                f'while not Path({str(gate)!r}).exists(): time.sleep(.01)\n'
            )

            def capture(*args, **kwargs):
                value = spawn_owned_process(*args, **kwargs)
                captured.append(value)
                return value

            def start(thread):
                actual_start(thread)
                if getattr(thread._target, '__name__', '') in {'drain', 'feed'}:
                    streams.append(thread)

            def on_line(line):
                handle = kernel.OpenProcess(0x00100000 | 0x1000, False, int(line))
                self.assertTrue(handle, 'could not retain the real pipe-holding descendant')
                handles.append(handle)
                self.assertEqual(258, kernel.WaitForSingleObject(handle, 0))
                gate.write_text('descendant was observed alive', encoding='utf-8')

            try:
                with patch('workbench.execution.spawn_owned_process', side_effect=capture), \
                     patch.object(threading.Thread, 'start', start):
                    result = runner._run_codex_streaming(
                        [sys.executable, '-u', '-c', script], '', 10, on_line, time.monotonic())
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(handles))
                self.assertEqual(0, kernel.WaitForSingleObject(handles[0], 1000),
                                 'descendant retained its pipes after the owned parent exited')
                self.assertEqual(3, len(streams))
                self.assertTrue(all(not thread.is_alive() for thread in streams))
                process, owner, _ = captured[0]
                self.assertIsNotNone(process.poll())
                self.assertIsNone(owner.handle)
                self.assertTrue(all(getattr(process, name).closed for name in ('stdin', 'stdout', 'stderr')))
            finally:
                for process, owner, _ in captured:
                    if owner: owner.close()
                    if process.poll() is None: process.kill()
                    process.wait(timeout=5)
                for thread in streams: thread.join(5)
                for process, _, _ in captured:
                    for name in ('stdin', 'stdout', 'stderr'): getattr(process, name).close()
                for handle in handles: kernel.CloseHandle(handle)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job close fault injection')
    def test_owner_close_failure_retries_cleanup_and_rejects_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CodexExecutionRunner(root, root)
            captured = []

            class FailingClose:
                def __init__(self, owner): self.owner, self.calls = owner, 0
                def close(self):
                    self.calls += 1
                    if self.calls == 1: raise OSError('fixture owner close failure')
                    self.owner.close()

            def capture(*args, **kwargs):
                process, owner, prefix = spawn_owned_process(*args, **kwargs)
                wrapped = FailingClose(owner)
                captured.append((process, wrapped))
                return process, wrapped, prefix

            try:
                with patch('workbench.execution.spawn_owned_process', side_effect=capture), \
                     self.assertRaisesRegex(RuntimeError, 'owner close failure'):
                    runner._run_codex_streaming([sys.executable, '-c', "print('done')"],
                                               '', 10, lambda line: None, time.monotonic())
                process, owner = captured[0]
                self.assertGreaterEqual(owner.calls, 2)
                self.assertIsNone(owner.owner.handle)
                self.assertIsNotNone(process.poll())
                self.assertTrue(all(getattr(process, name).closed for name in ('stdin', 'stdout', 'stderr')))
            finally:
                for process, owner in captured:
                    owner.close()
                    if process.poll() is None: process.kill()
                    process.wait(timeout=5)
                    for name in ('stdin', 'stdout', 'stderr'): getattr(process, name).close()

    def test_callback_failure_preserves_attempt_receipt_and_ends_real_fixture_process(self):
        # Engineering fixture: Python runs a local file named exec. No Codex CLI
        # or model is invoked; the real command, streams and owner are unchanged.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, runtime = root / 'candidate', root / 'runtime'
            workspace.mkdir()
            (workspace / 'exec').write_text(
                "import time\nprint('engineering fixture ready',flush=True)\ntime.sleep(30)\n",
                encoding='utf-8')
            (workspace / 'value.txt').write_text('1', encoding='utf-8')
            runner = CodexExecutionRunner(workspace, runtime, executable=sys.executable)
            task = {'id': 'TASK-callback-fixture', 'request': 'Engineering callback failure fixture',
                    'execution_mode': 'codex', 'write_scope': ['value.txt'],
                    'execution_timeout_seconds': 30, '_runtime_timeout_seconds': 10}
            failure = RuntimeError('engineering fixture callback failure')
            captured, commands, streams = [], [], []
            actual_start = threading.Thread.start

            def capture(command, *args, **kwargs):
                value = spawn_owned_process(command, *args, **kwargs)
                commands.append(list(command))
                captured.append(value)
                return value

            def start(thread):
                target = getattr(thread._target, '__name__', '')
                actual_start(thread)
                if target in {'drain', 'feed'}:
                    streams.append(thread)

            def on_line(line):
                if line == 'engineering fixture ready':
                    raise failure

            try:
                with patch('workbench.execution.spawn_owned_process', side_effect=capture), \
                     patch.object(threading.Thread, 'start', start), \
                     self.assertRaises(RuntimeError) as raised:
                    runner(task, on_codex_line=on_line)
                self.assertIs(failure, raised.exception)
                paths = list((runtime / 'delivery' / task['id']).glob('*/process.json'))
                self.assertEqual(1, len(paths))
                receipt = json.loads(paths[0].read_text(encoding='utf-8'))
                self.assertEqual(paths[0].parent.name, receipt['attempt_id'])
                self.assertEqual('failed', receipt['status'])
                self.assertFalse(receipt['success'])
                self.assertIsNone(receipt['returncode'])
                self.assertFalse(receipt['process_result_available'])
                self.assertEqual('RuntimeError', receipt['exception_type'])
                self.assertEqual(str(failure), receipt['error'])
                self.assertEqual(commands[0], receipt['command'])
                self.assertEqual([runner.executable, 'exec'], receipt['command'][:2])
                self.assertEqual(str(workspace.resolve()), receipt['workspace'])
                self.assertFalse((paths[0].parent / 'evidence.json').exists())
                self.assertEqual('1', (workspace / 'value.txt').read_text(encoding='utf-8'))
                self.assertEqual(1, len(captured))
                process, owner, _ = captured[0]
                self.assertIsNotNone(process.poll())
                self.assertTrue(all(getattr(process, name).closed for name in ('stdin', 'stdout', 'stderr')))
                self.assertEqual(3, len(streams))
                self.assertTrue(all(not thread.is_alive() for thread in streams))
                if owner:
                    self.assertIsNone(owner.handle)
            finally:
                for process, owner, _ in captured:
                    if owner: owner.close()
                    if process.poll() is None: process.kill()
                    process.wait(timeout=5)
                for thread in streams: thread.join(5)
                for process, _, _ in captured:
                    for name in ('stdin', 'stdout', 'stderr'): getattr(process, name).close()

    def test_cancelled_invocation_never_spawns_a_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CodexExecutionRunner(root, root)
            runner.control_event = threading.Event()
            runner.control_event.set()
            with patch('workbench.execution.spawn_owned_process') as spawn:
                result = runner._run_codex_streaming(
                    [sys.executable, '-c', "raise RuntimeError('must never execute')"],
                    '', 10, lambda line: None, time.monotonic())
                spawn.assert_not_called()
            self.assertEqual(130, result.returncode)
            self.assertIn('未启动进程', result.stderr)

    def test_chinese_prompt_survives_the_process_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CodexExecutionRunner(root, root)
            prompt = '按需求导出库存，不修改采购。\n第二行'
            result = runner._run_codex_streaming(
                [sys.executable, '-X', 'utf8', '-c', 'import sys;sys.stdout.write(sys.stdin.read())'],
                prompt, 10, lambda line: None, time.monotonic())
            self.assertEqual(0, result.returncode)
            self.assertEqual(prompt, result.stdout)

    def invoke(self, code, timeout=30, *, after_partial_ready=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = CodexExecutionRunner(root, root)
            lines = []
            real_clock = time.monotonic
            start = real_clock()
            ready = root / 'partial-ready'
            armed_at = None
            if after_partial_ready:
                code = code.replace('time.sleep(30)', f"open({str(ready)!r}, 'w').close();time.sleep(30)")

            def execution_clock():
                nonlocal armed_at
                now = real_clock()
                if not after_partial_ready:
                    return now
                if armed_at is None and ready.exists():
                    armed_at = now
                # Bound startup separately; only the partial-line case needs the
                # child to have emitted bytes before testing their preservation.
                if armed_at is None:
                    return start + timeout + 1 if now - start > 30 else start
                return start + now - armed_at

            with patch('workbench.execution.time.monotonic', side_effect=execution_clock):
                result = runner._run_codex_streaming(
                    [sys.executable, '-u', '-c', code], '', timeout, lines.append, start)
            return result, lines, real_clock() - (armed_at if armed_at is not None else start)

    def test_silent_process_cannot_bypass_timeout(self):
        result, _, elapsed = self.invoke('import time; time.sleep(30)', timeout=.3)
        self.assertEqual(124, result.returncode)
        self.assertLess(elapsed, 5)

    def test_partial_line_cannot_bypass_timeout_and_is_preserved(self):
        # Synchronize on the flushed bytes, not a guess about Windows startup speed.
        # The silent-process test separately enforces the deadline from launch.
        result, _, elapsed = self.invoke("import sys,time;sys.stdout.write('partial');sys.stdout.flush();time.sleep(30)",
                                         timeout=.3, after_partial_ready=True)
        self.assertEqual(124, result.returncode)
        self.assertIn('partial', result.stdout)
        self.assertLess(elapsed, 5)

    def test_full_stderr_is_drained_while_stdout_events_are_delivered(self):
        result, lines, _ = self.invoke("import sys;sys.stderr.write('x'*200000);sys.stderr.flush();print('done')")
        self.assertEqual(0, result.returncode)
        self.assertEqual(200000, len(result.stderr))
        self.assertEqual(['done'], lines)
