"""Real local processes for fixture cleanup; no model or human acceptance."""
import ctypes
import json
import os
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from eval.workbench_contracts import LocalDeliveryFixture
from workbench.execution import CodexExecutionRunner


class ContractFixtureShutdownTests(unittest.TestCase):
    @contextmanager
    def running_fixture(self, *, ignore_stop=False):
        fixture = LocalDeliveryFixture()
        stop, execution_stop, ready = threading.Event(), threading.Event(), threading.Event()
        if not ignore_stop:
            execution_stop = stop
        runner = CodexExecutionRunner(fixture.source, fixture.runtime)
        runner.control_event = execution_stop
        results, failures, processes, marker = [], [], [], {}
        import workbench.execution as execution
        original_spawn = execution.spawn_owned_process
        baseline_threads = set(threading.enumerate())

        def spawn(*args, **kwargs):
            value = original_spawn(*args, **kwargs)
            processes.append(value)
            return value

        # Windows Job ownership must include the descendant as well as its parent.
        script = (
            'import json,os,subprocess,sys,time\n'
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]) if os.name=="nt" else None\n'
            'print(json.dumps({"pid":os.getpid(),"child_pid":child.pid if child else None}),flush=True)\n'
            'time.sleep(30)\n'
        )

        def observed(line):
            marker.update(json.loads(line))
            ready.set()

        def work():
            from workbench.execution_control import local
            previous = getattr(local, 'cancel_event', None)
            local.cancel_event = execution_stop
            try:
                results.append(runner._run_codex_streaming(
                    [sys.executable, '-u', '-c', script], '', 30, observed, time.monotonic()))
            except BaseException as error:
                failures.append(error)
            finally:
                local.cancel_event = previous

        worker = threading.Thread(target=work, name='contract-fixture-process', daemon=True)
        fixture.service.cancel_events['fixture-shutdown'] = stop
        fixture.service.workers['fixture-shutdown'] = worker
        try:
            with patch('workbench.execution.spawn_owned_process', side_effect=spawn):
                worker.start()
                self.assertTrue(ready.wait(10), 'real fixture process did not reach its startup marker')
                streams = [t for t in threading.enumerate()
                           if t not in baseline_threads and t is not worker]
                yield fixture, stop, execution_stop, worker, results, failures, processes, marker, streams
        finally:
            # Reclaim only processes captured from this dedicated fixture.
            execution_stop.set()
            worker.join(5)
            for process, owner, _ in processes:
                if process.poll() is None:
                    if owner:
                        owner.close()
                    else:
                        process.kill()
                    process.wait(timeout=5)
            worker.join(5)
            self.assertFalse(worker.is_alive(), 'fixture worker survived explicit recovery')
            fixture.close()

    def assert_finished(self, worker, results, failures, processes, marker, streams):
        self.assertFalse(worker.is_alive())
        self.assertEqual([], failures)
        self.assertEqual(130, results[0].returncode)
        self.assertFalse(any(t.is_alive() for t in streams), 'fixture pipe threads survived shutdown')
        for process, owner, _ in processes:
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)
            if owner:
                self.assertIsNone(owner.handle)
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            for pid in (marker['pid'], marker['child_pid']):
                handle = kernel.OpenProcess(0x1000, False, pid)
                if handle:
                    try:
                        code = ctypes.c_ulong()
                        self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                        self.assertNotEqual(259, code.value, 'owned fixture descendant survived shutdown')
                    finally:
                        kernel.CloseHandle(handle)
                else:
                    self.assertEqual(87, ctypes.get_last_error(),
                                     'PID query failed without proving the fixture process ended')

    def test_close_signals_real_process_before_waiting_and_releases_the_tree(self):
        with self.running_fixture() as value:
            fixture, stop, _, worker, results, failures, processes, marker, streams = value
            closing_errors = []

            def close():
                try:
                    fixture.close()
                except BaseException as error:
                    closing_errors.append(error)

            closer = threading.Thread(target=close, name='contract-fixture-close', daemon=True)
            try:
                started = time.monotonic()
                closer.start()
                self.assertTrue(stop.wait(2), 'fixture.close did not signal its owned execution')
                closer.join(5)
                self.assertFalse(closer.is_alive(), 'fixture.close did not finish after signalling stop')
                self.assertEqual([], closing_errors)
                self.assert_finished(worker, results, failures, processes, marker, streams)
                self.assertFalse(fixture.root.exists())
                print(json.dumps({'fixture': 'contract-close-real-process',
                                  'elapsed_seconds': round(time.monotonic() - started, 3)}), flush=True)
            finally:
                stop.set()
                closer.join(5)
                self.assertFalse(closer.is_alive(), 'fixture closer survived explicit recovery')

    def test_incomplete_close_preserves_directory_and_original_failure_until_retry(self):
        with self.running_fixture(ignore_stop=True) as value:
            fixture, stop, execution_stop, worker, results, failures, processes, marker, streams = value
            evidence = fixture.root / 'original-failure.txt'
            original_bytes = b'actual fixture failure; never rewrite as success'
            evidence.write_bytes(original_bytes)
            original_failure = RuntimeError('source delivery failed before cleanup')
            original_join = worker.join

            def incomplete_join(timeout=None):
                # Inject a join returning while a real process is still active.
                original_join(min(timeout if timeout is not None else .05, .05))

            with patch.object(worker, 'join', side_effect=incomplete_join):
                with self.assertRaises(RuntimeError) as raised:
                    with fixture:
                        raise original_failure
                self.assertIs(original_failure, raised.exception)
                self.assertTrue(stop.is_set())
                self.assertTrue(worker.is_alive())
                self.assertEqual(original_bytes, evidence.read_bytes())
                self.assertFalse(fixture.temporary._finalizer.alive,
                                 'finalizer must not delete an incomplete retained fixture')
                self.assertTrue(any('关闭未完成' in note
                                    for note in getattr(original_failure, '__notes__', [])))
            execution_stop.set()
            worker.join(5)
            self.assert_finished(worker, results, failures, processes, marker, streams)
            fixture.close()
            self.assertFalse(fixture.root.exists(), 'manual retry should clean up the finished fixture')


if __name__ == '__main__':
    unittest.main()
