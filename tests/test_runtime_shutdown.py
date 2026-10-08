"""Shutdown signals precede persistence and cover the daily workflow owner."""
import contextlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from workbench.delivery_runtime import DeliveryRuntime
from workbench.execution import CodexExecutionRunner
from workbench.initiative import InitiativeStore
from workbench.initiative_workflow import InitiativeWorkflow
from workbench.maintenance import MaintenanceBusy, MaintenanceGate
from workbench.task_store import TaskStore


class RuntimeShutdownTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'runtime'
        self.tasks = TaskStore(self.directory / 'workbench.db')
        self.items = InitiativeStore(self.tasks.path)
        self.item = self.items.create({'title': 'shutdown fixture', 'raw_signal': 'local process control',
                                      'source': 'automated fixture', 'success_metric': 'process stopped'}, 'fixture-owner')
        self.workflow = InitiativeWorkflow(self.root, self.directory, self.items, self.tasks, enabled=True)
        self.runtime = DeliveryRuntime(self.root, self.directory, self.tasks, None, self.items, self.workflow)
        self.addCleanup(self.stop_fixture)

    def stop_fixture(self):
        for event in [*self.runtime.events.copy().values(), *self.workflow.cancel_events.copy().values()]:
            event.set()
        for worker in [*self.runtime.workers.copy().values(), *self.workflow.workers.copy().values()]:
            worker.join(5)
        self.runtime.close()

    @contextlib.contextmanager
    def workflow_process(self):
        ready, results = threading.Event(), []
        runner = CodexExecutionRunner(self.root, self.directory)

        def work(_):
            results.append(runner._run_codex_streaming(
                [sys.executable, '-u', '-c', "import time;print('ready',flush=True);time.sleep(30)"],
                '', 30, lambda line: ready.set(), time.monotonic()))

        self.workflow._launch(self.workflow._load(self.item['id']), work)
        worker = self.workflow.workers[self.item['id']]
        try:
            self.assertTrue(ready.wait(10), 'owned CLI did not reach its real startup marker')
            yield worker, results
        finally:
            self.workflow.cancel_events[self.item['id']].set()
            worker.join(5)

    def test_close_signals_daily_workflow_and_ends_its_real_cli(self):
        with self.workflow_process() as (worker, results):
            receipt = self.runtime.close()
            self.assertFalse(worker.is_alive())
            self.assertEqual(0, receipt['workers_still_stopping'])
            self.assertEqual(130, results[0].returncode)
            self.assertEqual('cancelled', self.workflow._load(self.item['id'])['stage'])
            with self.assertRaisesRegex(ValueError, '关闭'):
                self.workflow._launch(self.workflow._load(self.item['id']), lambda _: None)

    def test_close_stops_daily_cli_even_when_database_was_removed(self):
        database = Path(self.tasks.path)
        retained = self.directory / 'retained.db'
        with self.workflow_process() as (worker, results):
            database.replace(retained)
            try:
                with self.assertLogs(level='WARNING'):
                    receipt = self.runtime.close()
                self.assertFalse(worker.is_alive())
                self.assertEqual(130, results[0].returncode)
                self.assertEqual(0, receipt['workers_still_stopping'])
                self.assertTrue(receipt['errors'])
                self.assertFalse(database.exists(), 'shutdown must not recreate the lost database')
            finally:
                retained.replace(database)

    def test_shutdown_signal_is_sent_before_waiting_for_runtime_lock(self):
        event, stopped = threading.Event(), threading.Event()
        self.runtime.events['fixture-lock'] = event
        worker = threading.Thread(target=lambda: (event.wait(10), stopped.set()), daemon=True)
        self.runtime.workers['fixture-lock'] = worker
        worker.start()
        result, errors = [], []

        def close():
            try: result.append(self.runtime.close())
            except Exception as error: errors.append(error)

        closer = threading.Thread(target=close, daemon=True)
        try:
            with self.runtime.lock:
                closer.start()
                self.assertTrue(event.wait(1), 'shutdown waited for state lock before signalling the process')
                self.assertTrue(stopped.wait(1))
            closer.join(6)
            self.assertFalse(closer.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(0, result[0]['workers_still_stopping'])
        finally:
            event.set()
            worker.join(5)
            closer.join(6)

    def test_shutdown_during_session_creation_never_opens_a_new_attempt(self):
        plan = {'actor': 'fixture-owner', 'plan_id': 'shutdown-attempt', 'spec_text': 'local fixture'}
        self.runtime.freeze_profile(self.item['id'], plan)
        started, release = threading.Event(), threading.Event()
        original = self.runtime.sessions.create_session
        errors, results = [], []

        def session(*args, **kwargs):
            started.set()
            if not release.wait(5): raise RuntimeError('fixture session barrier timed out')
            return original(*args, **kwargs)

        def begin():
            try: results.append(self.runtime._begin(self.item['id'], plan))
            except Exception as error: errors.append(error)

        worker = threading.Thread(target=begin, daemon=True)
        try:
            with patch.object(self.runtime.sessions, 'create_session', side_effect=session):
                worker.start()
                self.assertTrue(started.wait(3))
                with self.assertLogs('workbench.delivery_runtime', level='WARNING'):
                    receipt = self.runtime.close(timeout=.1)
                self.assertTrue(receipt['errors'])
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual([], results)
            self.assertEqual(1, len(errors))
            self.assertIn('关闭', str(errors[0]))
            self.assertFalse(self.runtime.events)
            self.assertFalse(self.runtime.timers)
            self.assertEqual('idle', self.runtime._load(self.item['id'])['state'])
        finally:
            release.set()
            worker.join(5)

    def test_cancel_during_maintenance_wait_never_enters_delivery(self):
        attempted, executed = threading.Event(), threading.Event()
        actual_write = MaintenanceGate.write

        @contextlib.contextmanager
        def write(gate):
            try:
                with actual_write(gate): yield
            except MaintenanceBusy:
                attempted.set()
                raise

        with MaintenanceGate(self.directory).exclusive(), patch.object(MaintenanceGate, 'write', write):
            self.workflow._launch(self.workflow._load(self.item['id']), lambda _: executed.set())
            worker = self.workflow.workers[self.item['id']]
            self.assertTrue(attempted.wait(3))
            with self.assertLogs('workbench.initiative_workflow', level='WARNING'):
                self.workflow.cancel_events[self.item['id']].set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(executed.is_set())
            self.assertTrue(self.workflow.shutdown_errors)


if __name__ == '__main__':
    unittest.main()
