"""Real worker spans exclude backup while files and database are between writes."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from workbench.automation import DeliveryAutomation
from workbench.initiative import InitiativeStore
from workbench.initiative_workflow import InitiativeWorkflow
from workbench.maintenance import MaintenanceBusy, MaintenanceGate
from workbench.task_store import TaskStore
from workbench.web_execution import WebExecution
from workbench.workbench_backup import BackupService, verify_backup


class MaintenanceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='maintenance-workers-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        self.tasks = TaskStore(self.runtime / 'workbench.db')
        self.backups = BackupService(self.runtime)

    def blocked_span(self, name):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        path = self.runtime / 'reports' / (name + '.txt')
        path.parent.mkdir(exist_ok=True)
        return entered, release, path

    def review(self, task):
        for status in ('spec_ready', 'executing', 'evaluating', 'review'):
            task = self.tasks.transition(task['id'], status, 'automated maintenance fixture',
                result={'summary': {'decision': 'pass', 'blocking_failed': 0},
                        'results': [{'name': 'fixture', 'level': 'blocking', 'passed': True}]} if status == 'review' else None)
        return task

    def backup_stays_out(self):
        # Task state can already be review/ready: only the worker span closes
        # this gap between database completion and final file/queue writes.
        with self.assertRaises(MaintenanceBusy):
            with MaintenanceGate(self.runtime).exclusive():
                self.fail('backup acquired exclusivity while worker still owned files')
        with self.assertRaises(MaintenanceBusy):
            self.backups.create('fixture-backup')
        self.assertEqual([], self.backups.list()['items'])
        self.assertEqual([], list(self.backups.directory.glob('*.zip')))

    def complete_backup(self, relative):
        backup = self.backups.create('fixture-backup')
        self.assertTrue(verify_backup(backup['archive_path'])['ok'])
        with zipfile.ZipFile(backup['archive_path']) as archive:
            self.assertEqual(b'complete', archive.read('payload/' + relative))

    def thread(self, target, *args):
        errors = []
        def invoke():
            try:
                target(*args)
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        self.addCleanup(lambda: worker.join(3))
        return worker, errors

    def test_automation_holds_span_after_review_until_file_and_cleanup_finish(self):
        entered, release, path = self.blocked_span('automation')
        def run(task_id, actor):
            task = self.review(self.tasks.get(task_id))
            path.write_text('half', encoding='utf-8')
            self.tasks.append_event(task_id, 'file evidence', evidence={'path': str(path)})
            entered.set()
            if not release.wait(3):
                raise TimeoutError('fixture worker was not released')
            path.write_text('complete', encoding='utf-8')
            return task
        automation = DeliveryAutomation(self.tasks, self.runtime, agent_runner=run, max_attempts=1)
        task = automation.submit('maintenance fixture')
        self.assertTrue(entered.wait(3))
        worker = automation._threads[task['id']]
        try:
            self.assertEqual('review', self.tasks.get(task['id'])['status'])
            self.backup_stays_out()
        finally:
            release.set()
        self.assertEqual('review', automation.wait(task['id'], 3)['status'])
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.complete_backup('reports/automation.txt')

    def test_automation_queue_handoff_is_inside_span_and_next_task_is_not_lost(self):
        first_entered, first_release, first_path = self.blocked_span('first')
        second_entered, second_release, second_path = self.blocked_span('second')
        handoff_entered, handoff_release = threading.Event(), threading.Event()
        self.addCleanup(handoff_release.set)
        first_id = None
        def run(task_id, actor):
            task = self.review(self.tasks.get(task_id))
            entered, release, path = (first_entered, first_release, first_path) if task_id == first_id else (second_entered, second_release, second_path)
            path.write_text('half', encoding='utf-8')
            entered.set()
            if not release.wait(3):
                raise TimeoutError('queued fixture worker was not released')
            path.write_text('complete', encoding='utf-8')
            return task
        automation = DeliveryAutomation(self.tasks, self.runtime, agent_runner=run, max_workers=1, max_attempts=1)
        first = automation.submit('first queued fixture', auto_start=False)
        first_id = first['id']
        automation.start(first_id)
        self.assertTrue(first_entered.wait(3))
        first_worker = automation._threads[first_id]
        second = automation.submit('second queued fixture')
        original_start = automation.start
        def start(task_id, actor='automation'):
            if task_id == second['id']:
                handoff_entered.set()
                if not handoff_release.wait(3):
                    raise TimeoutError('queue handoff was not released')
            return original_start(task_id, actor)
        try:
            with patch.object(automation, 'start', side_effect=start):
                first_release.set()
                self.assertTrue(handoff_entered.wait(3))
                self.assertEqual({}, automation._threads)
                self.assertEqual([], automation._pending)
                self.backup_stays_out()
                handoff_release.set()
                self.assertTrue(second_entered.wait(3))
                second_worker = automation._threads[second['id']]
                self.backup_stays_out()
                second_release.set()
                first_worker.join(3)
                self.assertEqual('review', automation.wait(second['id'], 3)['status'])
                second_worker.join(3)
                self.assertFalse(second_worker.is_alive())
        finally:
            first_release.set(); handoff_release.set(); second_release.set()
            first_worker.join(3)
            automation.wait(second['id'], 3)
        self.assertEqual('review', self.tasks.get(first_id)['status'])
        self.complete_backup('reports/first.txt')
        self.assertEqual('complete', second_path.read_text(encoding='utf-8'))

    def test_initiative_worker_holds_span_with_ready_state_between_file_writes(self):
        entered, release, path = self.blocked_span('initiative')
        items = InitiativeStore(self.tasks.path)
        item = items.create({'title': 'maintenance fixture', 'raw_signal': 'fixture', 'source': 'test',
                             'project_id': 'fixture-project'}, 'fixture-owner')
        workflow = InitiativeWorkflow(self.root, self.runtime, items, self.tasks, enabled=True)
        workflow.cancel_events[item['id']] = threading.Event()
        def operation(item_id):
            data = workflow._load(item_id)
            data['stage'] = 'ready'
            workflow._save(data)
            path.write_text('half', encoding='utf-8')
            entered.set()
            if not release.wait(3):
                raise TimeoutError('initiative fixture worker was not released')
            path.write_text('complete', encoding='utf-8')
        worker, errors = self.thread(workflow._worker, item['id'], operation, ())
        self.assertTrue(entered.wait(3))
        try:
            self.backup_stays_out()
        finally:
            release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], errors)
        self.complete_backup('reports/initiative.txt')

    def test_web_worker_holds_span_before_and_after_task_creation(self):
        entered, release, path = self.blocked_span('web')
        before_creation, create_task = threading.Event(), threading.Event()
        self.addCleanup(create_task.set)
        def submit(**kwargs):
            path.write_text('half-before-task', encoding='utf-8')
            before_creation.set()
            if not create_task.wait(3):
                raise TimeoutError('web fixture task creation was not released')
            task = self.tasks.create('web maintenance fixture', execution_mode='codex', write_scope=['workbench'])
            kwargs['on_task_created'](task)
            task = self.review(task)
            path.write_text('half', encoding='utf-8')
            entered.set()
            if not release.wait(3):
                raise TimeoutError('web fixture worker was not released')
            path.write_text('complete', encoding='utf-8')
            return {'task': task}
        web = WebExecution(self.root, self.runtime, self.tasks, enabled=True, submitter=submit)
        plan = {'plan_id': 'maintenance-plan', 'state': 'starting', 'actor': 'fixture-owner', 'task_id': None,
                'lesson': 1, 'additional_eval_cases': [], 'session_commit': 'fixture', 'baseline_commit': 'fixture'}
        web.plans[plan['plan_id']] = plan
        web._save(plan)
        worker, errors = self.thread(web._run, plan['plan_id'])
        try:
            self.assertTrue(before_creation.wait(3))
            self.assertEqual([], self.tasks.list())
            self.backup_stays_out()
            create_task.set()
            self.assertTrue(entered.wait(3))
            self.backup_stays_out()
        finally:
            create_task.set()
            release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], errors)
        self.assertEqual('finished', web.get(plan['plan_id'])['state'])
        self.complete_backup('reports/web.txt')

    def test_worker_start_waits_for_exclusive_then_executes_once(self):
        entered = threading.Event()
        calls = []
        def run(task_id, actor):
            calls.append(task_id)
            entered.set()
            return self.review(self.tasks.get(task_id))
        automation = DeliveryAutomation(self.tasks, self.runtime, agent_runner=run, max_attempts=1)
        task = automation.submit('startup race fixture', auto_start=False)
        with MaintenanceGate(self.runtime).exclusive():
            automation.start(task['id'])
            worker = automation._threads[task['id']]
            self.assertFalse(entered.wait(.15))
            self.assertTrue(automation.is_active(task['id']))
        self.assertTrue(entered.wait(3))
        self.assertEqual('review', automation.wait(task['id'], 3)['status'])
        worker.join(3)
        self.assertEqual([task['id']], calls)

    def test_body_maintenance_error_is_recorded_without_replaying_body(self):
        calls = []
        workers = []
        def run(task_id, actor):
            calls.append(task_id)
            workers.append(threading.current_thread())
            raise MaintenanceBusy('injected body error')
        automation = DeliveryAutomation(self.tasks, self.runtime, agent_runner=run, max_attempts=1)
        task = automation.submit('body error fixture')
        result = automation.wait(task['id'], 3)
        workers[0].join(3)
        self.assertEqual('dead_letter', result['status'])
        self.assertEqual([task['id']], calls)
        self.assertIn('injected body error', result['error'])


if __name__ == '__main__':
    unittest.main()
