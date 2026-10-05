"""Real owned preview processes in isolated folders; no production service."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from workbench.generic_preview import ProjectPreviews
from workbench.project_configuration import ProjectConfiguration
from workbench.project_delivery import CandidateProjectEval
from workbench.project_store import ProjectStore
from workbench.task_store import TaskStore
from workbench.process_guard import spawn
from workbench.managed_process import ManagedProcess


LOGGING_SERVICE = r'''
import json,sys
from http.server import BaseHTTPRequestHandler,HTTPServer
sys.stdout.write('o'*2097152+'\n');sys.stdout.flush()
sys.stderr.write('e'*2097152+'\n');sys.stderr.flush()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({'status':'ok'}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass
HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
'''


class GenericPreviewReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        source = self.root / 'registered-project'
        source.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=source, check=True, capture_output=True)
        self.tasks = TaskStore(self.runtime / 'workbench.db')
        self.projects = ProjectStore(self.tasks.path)
        command = [sys.executable, '-c', "import json;print(json.dumps({'summary':{'decision':'pass','total':1,'passed':1,'blocking_failed':0},'results':[{'name':'fixture','level':'blocking','passed':True}]}))"]
        project = self.projects.create('preview fixture', source, command)
        task = self.tasks.create('preview candidate', business_refs=['PROJECT:' + project['id']])
        self.task_id = task['id']
        workspace = self.runtime / 'candidate'
        workspace.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=workspace, check=True, capture_output=True)
        (workspace / 'value.txt').write_text('checked', encoding='utf-8')
        for status in ('spec_ready', 'executing', 'evaluating'):
            self.tasks.transition(self.task_id, status)
        report = CandidateProjectEval(workspace, self.runtime, self.task_id, command, 'fixture')()
        self.tasks.transition(self.task_id, 'review', result=report)
        self.configurations = ProjectConfiguration(self.projects)
        self.configurations.save(project['id'], dict(expected_configuration_revision=0, preview_config={
            'command': [sys.executable, '-u', '-c', "import time;print('preview process ready',flush=True);time.sleep(30)"],
            'health': {'path': '/health', 'expected': {'status': 'ok'}}, 'timeout_seconds': 10}), 'fixture-owner')
        self.previews = ProjectPreviews(self.runtime, self.tasks, self.projects, self.configurations)
        self.addCleanup(self.previews.close)
        self.plan = self.previews.plan(self.task_id)

    def test_shutdown_interrupts_startup_and_terminates_its_real_process(self):
        entered = threading.Event()
        handles, results, errors = [], [], []
        def observed_spawn(*args, **kwargs):
            value = spawn(*args, **kwargs)
            handles.append(value)
            return value
        def unhealthy(*args, **kwargs):
            entered.set()
            return {'passed': False, 'fixture': True}
        def starting():
            try:
                results.append(self.previews.start(self.task_id, 'fixture-owner', {**self.plan, 'confirmed': True}))
            except Exception as error:
                errors.append(error)
        with patch('workbench.generic_preview.spawn', observed_spawn), patch('workbench.generic_preview.probe', unhealthy):
            worker = threading.Thread(target=starting)
            worker.start()
            closing = None
            try:
                self.assertTrue(entered.wait(3))
                self.assertIsNone(handles[0][0].poll())
                closing = threading.Thread(target=self.previews.close)
                started = time.monotonic()
                closing.start()
                closing.join(1.5)
                self.assertFalse(closing.is_alive(), 'shutdown waited for the whole startup health timeout')
                self.assertLess(time.monotonic() - started, 1.5)
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertIsNotNone(handles[0][0].poll())
                self.assertFalse(results)
                self.assertTrue(errors)
                with self.tasks.connect() as db:
                    stored = json.loads(db.execute('SELECT payload FROM preview_plans WHERE id=?', (self.plan['plan_id'],)).fetchone()[0])
                self.assertEqual('interrupted', stored['state'])
                self.assertFalse(stored['automatic_replay'])
            finally:
                for process, owner, _ in handles:
                    if owner:
                        owner.close()
                    if process.poll() is None:
                        process.kill()
                    process.wait(5)
                worker.join(3)
                if closing:
                    closing.join(3)

    def test_shutdown_refuses_new_start_before_spawn(self):
        self.previews.close()
        with patch('workbench.generic_preview.spawn') as process:
            with self.assertRaisesRegex(ValueError, '关闭'):
                self.previews.start(self.task_id, 'fixture-owner', {**self.plan, 'confirmed': True})
            process.assert_not_called()

    def test_ready_preview_shutdown_waits_for_log_handles_after_large_output(self):
        project_id = self.plan['project_id']
        self.configurations.save(project_id, dict(expected_configuration_revision=1, preview_config={
            'command': [sys.executable, '-u', '-c', LOGGING_SERVICE, '{port}'],
            'health': {'path': '/health', 'expected': {'status': 'ok'}}, 'timeout_seconds': 5}), 'fixture-owner')
        plan = self.previews.plan(self.task_id)
        finishing, release = threading.Event(), threading.Event()
        original_open = Path.open
        class DelayedClose:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def close(self):
                finishing.set()
                if not release.wait(3): raise RuntimeError('fixture did not release log cleanup')
                self.stream.close()
        def open_log(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return DelayedClose(stream) if path.name in {'stdout.log', 'stderr.log'} else stream
        errors = []
        def close():
            try: self.previews.close()
            except Exception as error: errors.append(error)
        closer = threading.Thread(target=close)
        with patch.object(Path, 'open', open_log):
            try:
                result = self.previews.start(self.task_id, 'fixture-owner', {**plan, 'confirmed': True})
                self.assertTrue(result['health_result']['passed'])
                managed = self.previews._owned[self.task_id]
                self.assertIs(managed, self.previews.running[self.task_id][1])
                self.assertEqual(2, len(managed.readers))
                closer.start()
                self.assertTrue(finishing.wait(2))
                closer.join(.1)
                self.assertTrue(closer.is_alive(), 'close returned while successful preview log handles were still open')
            finally:
                release.set()
                if closer.ident: closer.join(5)
                self.previews.close()
        self.assertFalse(closer.is_alive()); self.assertFalse(errors)
        self.assertFalse(self.previews.running); self.assertFalse(self.previews._owned)
        self.assertFalse(any(reader.is_alive() for reader in managed.readers))
        self.assertTrue(managed.process.stdout.closed); self.assertTrue(managed.process.stderr.closed)
        for label, character in (('stdout', 'o'), ('stderr', 'e')):
            text = (Path(plan['runtime_dir']) / (label + '.log')).read_text(encoding='utf-8')
            expected = character*2097152+'\n'
            self.assertTrue(text.startswith(expected), label + ' lost the known large output')
            if text[len(expected):]:
                print(json.dumps({'fixture': 'generic_preview_extra_log', 'stream': label,
                                  'extra': text[len(expected):][:800]}, ensure_ascii=False), flush=True)

    def test_log_failure_keeps_failed_plan_and_allows_a_new_manual_preview(self):
        self.configurations.save(self.plan['project_id'], dict(expected_configuration_revision=1, preview_config={
            'command': [sys.executable, '-u', '-c', LOGGING_SERVICE, '{port}'],
            'health': {'path': '/health', 'expected': {'status': 'ok'}}, 'timeout_seconds': 5}), 'fixture-owner')
        plan = self.previews.plan(self.task_id)
        original_open = Path.open
        class FailedLog:
            def __init__(self, stream): self.stream = stream
            def __getattr__(self, name): return getattr(self.stream, name)
            def write(self, text): raise OSError('fixture preview disk full')
            def close(self): self.stream.close()
        def open_log(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return FailedLog(stream) if path.name == 'stdout.log' else stream
        with patch.object(Path, 'open', open_log), self.assertRaisesRegex(OSError, 'preview disk full'):
            self.previews.start(self.task_id, 'fixture-owner', {**plan, 'confirmed': True})
        with self.tasks.connect() as db:
            failed = json.loads(db.execute('SELECT payload FROM preview_plans WHERE id=?', (plan['plan_id'],)).fetchone()[0])
        self.assertEqual('failed', failed['state']); self.assertIn('preview disk full', failed['error'])
        self.assertFalse(failed['automatic_replay']); self.assertFalse(self.previews._owned)
        self.assertTrue((Path(plan['runtime_dir'])/'stderr.log').is_file())
        retry = self.previews.plan(self.task_id)
        result = self.previews.start(self.task_id, 'fixture-owner', {**retry, 'confirmed': True})
        self.assertTrue(result['health_result']['passed']); self.assertNotEqual(plan['plan_id'], retry['plan_id'])
        self.previews.close(); self.assertFalse(self.previews._owned)

    def test_configuration_change_while_waiting_for_preview_lock_prevents_spawn(self):
        read, errors = threading.Event(), []
        original_get = self.configurations.get
        def get(project_id):
            result = original_get(project_id); read.set(); return result
        def starting():
            try: self.previews.start(self.task_id, 'fixture-owner', {**self.plan, 'confirmed': True})
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=starting)
        self.previews.lock.acquire()
        with patch.object(self.configurations, 'get', side_effect=get), patch('workbench.generic_preview.spawn', side_effect=RuntimeError('stale configuration spawned')) as launch:
            try:
                worker.start(); self.assertTrue(read.wait(2))
                self.configurations.save(self.plan['project_id'], {'expected_configuration_revision':1}, 'fixture-owner')
            finally: self.previews.lock.release()
            worker.join(3); self.assertFalse(worker.is_alive())
            launch.assert_not_called(); self.assertTrue(errors); self.assertIsInstance(errors[0], ValueError)
            self.assertIn('配置', str(errors[0]))

    def test_configuration_change_during_health_wait_stops_without_success(self):
        checking, release, errors, results = threading.Event(), threading.Event(), [], []
        def healthy(*args, **kwargs):
            checking.set()
            if not release.wait(3): raise RuntimeError('fixture health release missing')
            return {'passed': True, 'actual': {'status': 'ok'}}
        def starting():
            try: results.append(self.previews.start(self.task_id, 'fixture-owner', {**self.plan, 'confirmed': True}))
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=starting)
        with patch('workbench.generic_preview.probe', side_effect=healthy):
            try:
                worker.start(); self.assertTrue(checking.wait(3)); managed = self.previews._owned[self.task_id]
                self.configurations.save(self.plan['project_id'], {'expected_configuration_revision':1}, 'fixture-owner')
                release.set(); worker.join(3)
                self.assertFalse(worker.is_alive()); self.assertFalse(results); self.assertTrue(errors)
                self.assertIn('配置', str(errors[0])); self.assertIsNotNone(managed.process.poll())
                self.assertFalse(self.previews._owned)
                self.assertFalse(any(e['detail']=='已打开本项目候选预览' for e in self.tasks.get(self.task_id)['events']))
                with self.tasks.connect() as db:
                    failed=json.loads(db.execute('SELECT payload FROM preview_plans WHERE id=?',(self.plan['plan_id'],)).fetchone()[0])
                self.assertEqual('failed', failed['state']); self.assertIn('配置', failed['error'])
            finally:
                release.set(); worker.join(3); self.previews.close()

    def assert_legacy_config_install_rejects_old_launch(self, *, reuse):
        preview = self.configurations.get(self.plan['project_id'])['preview_config']
        self.configurations.save(self.plan['project_id'], {'expected_configuration_revision':1,'preview_config':None}, 'fixture-owner')
        web=self.runtime/'course-worktrees'/self.task_id/'web';web.mkdir(parents=True);(web/'index.html').write_bytes(b'checked')
        self.tasks.append_event(self.task_id,'课程红绿差分判定已完成',evidence={'accepted':True})
        self.tasks.append_event(self.task_id,'受控执行阶段完成',evidence={'change_manifest':[
            {'path':'web/index.html','after_sha256':hashlib.sha256(b'checked').hexdigest()}]})
        if reuse:
            managed=ManagedProcess([sys.executable,'-c','import time;time.sleep(30)'],self.runtime)
            managed.start();self.previews._owned[self.task_id]=managed
            self.previews.running[self.task_id]=(managed.process,managed,{'task_id':self.task_id,'fixture':'existing legacy'})
        read,errors,results=threading.Event(),[],[]
        original_get=self.configurations.get
        def get(project_id):
            result=original_get(project_id);read.set();return result
        def starting():
            try:results.append(self.previews.start(self.task_id,'fixture-owner'))
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=starting)
        self.previews.lock.acquire()
        with patch.object(self.configurations,'get',side_effect=get),patch('workbench.candidate_preview.spawn') as launch:
            try:
                worker.start();self.assertTrue(read.wait(2))
                self.configurations.save(self.plan['project_id'],{'expected_configuration_revision':2,'preview_config':preview},'fixture-owner')
            finally:self.previews.lock.release()
            worker.join(3);self.assertFalse(worker.is_alive());launch.assert_not_called()
            self.assertFalse(results);self.assertTrue(errors);self.assertIn('配置',str(errors[0]))
        self.previews.close()

    def test_legacy_config_install_while_waiting_prevents_the_old_spawn(self):
        self.assert_legacy_config_install_rejects_old_launch(reuse=False)

    def test_legacy_config_install_while_waiting_prevents_old_service_reuse(self):
        self.assert_legacy_config_install_rejects_old_launch(reuse=True)

    def test_cleanup_failure_cannot_skip_the_original_failed_plan(self):
        managed = None
        try:
            with patch.object(ManagedProcess,'close',side_effect=RuntimeError('fixture preview cleanup failure')):
                with patch('workbench.generic_preview.probe',side_effect=ValueError('fixture original health failure')):
                    with self.assertRaisesRegex(ValueError,'original health failure'):
                        self.previews.start(self.task_id,'fixture-owner',{**self.plan,'confirmed':True})
                managed=self.previews._owned[self.task_id]
                with self.tasks.connect() as db:
                    failed=json.loads(db.execute('SELECT payload FROM preview_plans WHERE id=?',(self.plan['plan_id'],)).fetchone()[0])
                self.assertEqual('failed',failed['state']);self.assertIn('original health failure',failed['error'])
                self.assertTrue(failed['cleanup_required']);self.assertIn('cleanup failure',failed['cleanup_error'])
                self.assertTrue(self.previews.busy());self.assertIs(managed,self.previews._owned[self.task_id])
                retry=self.previews.plan(self.task_id)
                with patch('workbench.generic_preview.spawn') as launch, self.assertRaisesRegex(RuntimeError,'cleanup failure'):
                    self.previews.start(self.task_id,'fixture-owner',{**retry,'confirmed':True})
                launch.assert_not_called();self.assertIs(managed,self.previews._owned[self.task_id])
        finally:
            if managed:managed.close()
            self.previews.close()
        self.assertFalse(self.previews.busy())


if __name__ == '__main__':
    unittest.main()
