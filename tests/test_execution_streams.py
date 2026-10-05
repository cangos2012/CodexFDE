"""Real local pipe behavior; does not contact or impersonate Codex."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.execution import CodexExecutionRunner


class ExecutionStreamTests(unittest.TestCase):
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
