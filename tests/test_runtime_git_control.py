"""Real, isolated Git-stage lifetime fixtures; no Codex or customer source."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from workbench.delivery_runtime import DeliveryRuntime
from workbench.execution_control import local
from workbench.file_io import read_text
from workbench import process_guard


_GIT_FIXTURE = """import json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]); args=sys.argv[2:]
stage=(root/'stage').read_text()
blocked=(stage=='snapshot' and 'init' in args) or (stage=='apply' and 'apply' in args)
if blocked:
    child=subprocess.Popen([sys.executable,'-u','-c',
        'import json,os,sys,time;from pathlib import Path;'
        'root=Path(sys.argv[1]);'
        '(root/"grandchild.json").write_text(json.dumps({"pid":os.getpid(),"parent":os.getppid()}));'
        '\\nwhile not (root/"release").exists(): time.sleep(.02)',str(root)])
    (root/'command.json').write_text(json.dumps({'pid':os.getpid(),'parent':os.getppid(),'argv':args}))
    while not (root/'release').exists(): time.sleep(.02)
    child.wait(timeout=5)
raise SystemExit(0)
"""


def _manifest(root, runtime):
    return {path.relative_to(root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and '.git' not in path.parts}


class RuntimeGitControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='runtime-git-control-')
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'; self.source.mkdir()
        for name in ('a.txt', 'b.txt'):
            (self.source / name).write_text('before', encoding='utf-8')
        self.script = self.root / 'fixture_git.py'
        self.script.write_text(_GIT_FIXTURE, encoding='utf-8')
        self.runtime = DeliveryRuntime.__new__(DeliveryRuntime)
        self.runtime.runtime = self.root / 'runtime'; self.runtime.runtime.mkdir()
        self.runtime.lock = threading.RLock(); self.runtime.closed = False
        self.runtime.events = {'item': threading.Event()}
        self.runtime.runner_factory = lambda *a, **k: self.fail('Internal Git must not use the coding runner factory')
        self.state = {'initiative_id':'item', 'run_id':'plan', 'state':'prepared', 'session_id':'session',
            'task_id':None, 'started_at':time.time(), 'budget':{'time_budget_seconds':30,
                'tokens_used':0, 'token_budget':30000, 'max_workers':2},
            'subtasks':[{'id':'a', 'name':'a', 'prompt':'a', 'write_set':['a.txt']},
                        {'id':'b', 'name':'b', 'prompt':'b', 'write_set':['b.txt']}]}
        self.events = []
        self.runtime._load = lambda item: copy.deepcopy(self.state)
        self.runtime._save = lambda state: self.state.update(copy.deepcopy(state))
        self.runtime._event = lambda data, kind, actor, payload: self.events.append((kind, copy.deepcopy(payload)))
        self.runtime._begin = lambda item, plan: self.runtime._load(item)
        self.runtime.sessions = SimpleNamespace(bind_task=lambda *a: None, sync_task=lambda *a: None)
        plan = {'plan_id':'plan', 'source_manifest':_manifest(self.source, self.runtime.runtime),
                'spec_text':'fixture', 'request':'fixture', 'write_scope':['a.txt','b.txt'],
                'project':{'id':'project', 'eval_command':['fixture-eval']}}
        self.work = {'plan':plan, 'workspace':str(self.source)}
        self.runtime.workflow = SimpleNamespace(lock=threading.RLock(),
            _load=lambda item: copy.deepcopy(self.work), _save=lambda work: self.work.update(copy.deepcopy(work)),
            learning=SimpleNamespace(finish=lambda *a, **k: None))
        self.tasks = {}
        def create(request, **fields):
            task = {'id':'task-' + str(len(self.tasks)), 'status':'queued', **fields}
            self.tasks[task['id']] = task
            return task
        def transition(task, status, *a, **k): self.tasks[task]['status'] = status
        self.runtime.tasks = SimpleNamespace(create=create, append_event=lambda *a, **k: None,
            get=lambda task: self.tasks[task], transition=transition)
        self.runtime._runner = lambda *a: None
        self.handles = None
        if os.name == 'nt':
            from tests.test_process_guard import _FixtureHandles
            self.handles = _FixtureHandles(self)

    def tearDown(self):
        (self.root / 'release').touch()
        if self.handles:
            self.assertEqual([], self.handles.terminate())
            self.handles.close()
        self.temporary.cleanup()

    def wait_marker(self, path):
        deadline = time.monotonic() + 5
        while not path.is_file() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.is_file(), 'real Git fixture did not reach ' + path.name)
        return json.loads(path.read_text())

    def retain_fixture(self):
        command = self.wait_marker(self.root / 'command.json')
        child = self.wait_marker(self.root / 'grandchild.json')
        self.assertEqual(command['pid'], child['parent'])
        if self.handles:
            self.handles.retain('git-command', command['pid'], command['parent'])
            self.handles.retain('git-grandchild', child['pid'], child['parent'])

    def invoke_stage(self, stage, action):
        (self.root / 'stage').write_text(stage)
        real_run = subprocess.run
        def command(argv):
            return [sys._base_executable, '-X', 'utf8', '-u', str(self.script), str(self.root), *argv[1:]]
        def old_git(argv, **options):
            return real_run(command(argv), **options)
        def owned_git(argv, cwd, **options):
            return process_guard.spawn(command(argv), cwd, **options)
        def snapshot(source, workspace, files, **options):
            workspace.mkdir(parents=True)
            for relative in files:
                (workspace / relative).write_bytes((source / relative).read_bytes())
        def task_run(tasks, task, actor, **options):
            record = self.tasks[task]; record['status'] = 'review'
            return record
        patches = [patch('workbench.delivery_runtime.subprocess.run', side_effect=old_git),
                   patch('workbench.execution.spawn_owned_process', side_effect=owned_git),
                   patch('workbench.delivery_runtime.manifest', side_effect=_manifest),
                   patch('workbench.delivery_runtime.CandidateProjectEval', side_effect=lambda *a, **k: lambda: {}),
                   patch('workbench.delivery_runtime.run_task', side_effect=task_run)]
        if stage == 'apply':
            patches += [patch.object(DeliveryRuntime, '_snapshot', side_effect=snapshot),
                        patch.object(DeliveryRuntime, '_patch', return_value=b'fixture patch\x00\xff')]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for replacement in patches: stack.enter_context(replacement)
            worker = threading.Thread(target=self.runtime._run_subtasks_owned, args=('item','fixture-owner'))
            worker.start()
            try:
                self.retain_fixture()
                self.state['requested_control'] = action
                self.runtime.events['item'].set()
                worker.join(2)
                self.assertFalse(worker.is_alive(), 'Git stage ignored ' + action + ' cancellation')
                self.assertEqual('paused' if action == 'pause' else 'cancelled', self.state['state'])
                self.assertEqual('before', (self.source / 'a.txt').read_text())
                if self.handles:
                    self.assertTrue(all(result == 0 for result in self.handles.waits().values()))
            finally:
                (self.root / 'release').touch()
                worker.join(5)
                if self.handles: self.handles.terminate()
                self.assertFalse(worker.is_alive(), 'fixture cleanup must finish its own worker')

    @unittest.skipUnless(os.name == 'nt', 'Windows Job process-tree ownership fixture')
    def test_pause_interrupts_real_snapshot_git_and_descendant(self):
        self.invoke_stage('snapshot', 'pause')

    @unittest.skipUnless(os.name == 'nt', 'Windows Job process-tree ownership fixture')
    def test_cancel_interrupts_real_apply_git_and_descendant(self):
        self.invoke_stage('apply', 'cancel')

    @unittest.skipUnless(os.name == 'nt', 'Windows Job process-tree ownership fixture')
    def test_remaining_budget_terminates_real_git_and_descendant(self):
        (self.root / 'stage').write_text('snapshot')
        self.state['budget']['time_budget_seconds'] = 3
        self.state['started_at'] = time.time()
        errors = []
        command = [sys._base_executable, '-X', 'utf8', '-u', str(self.script), str(self.root), 'init']
        def invoke():
            local.cancel_event = self.runtime.events['item']
            try:
                self.runtime._git('item', 'parent.snapshot', command, cwd=self.source)
            except subprocess.CalledProcessError as error:
                errors.append(error)
            finally:
                local.cancel_event = None
        worker = threading.Thread(target=invoke)
        worker.start()
        try:
            self.retain_fixture()
            worker.join(5)
            self.assertFalse(worker.is_alive(), 'the frozen remaining budget must stop Git')
            self.assertEqual([124], [error.returncode for error in errors])
            if self.handles:
                self.assertTrue(all(result == 0 for result in self.handles.waits().values()))
            receipt = json.loads(read_text(next(self.runtime.runtime.rglob('process.json'))))
            self.assertFalse(receipt['success'])
            self.assertEqual('failed', receipt['status'])
            self.assertLessEqual(receipt['timeout_seconds'], 3)
            self.assertEqual(command, receipt['executed_command'])
        finally:
            (self.root / 'release').touch(); worker.join(5)
            if self.handles: self.handles.terminate()
            self.assertFalse(worker.is_alive())

    def test_each_git_step_consumes_same_parent_time_without_model_tokens(self):
        self.state['started_at'] = time.time() - 20
        self.state['budget'].update(tokens_used=30000, usage_unavailable=True)
        command = [sys._base_executable, '-X', 'utf8', '-c', "print('local diagnostic')"]
        for phase in ('parent.snapshot', 'subtask.a.snapshot'):
            result = self.runtime._git('item', phase, command, cwd=self.source)
            self.assertEqual(0, result.returncode)
        receipts = sorted((json.loads(read_text(path))
                           for path in self.runtime.runtime.rglob('process.json')), key=lambda value:value['requested_at'])
        self.assertEqual(2, len(receipts))
        self.assertLessEqual(receipts[0]['timeout_seconds'], 10)
        self.assertLess(receipts[1]['timeout_seconds'], receipts[0]['timeout_seconds'])
        self.assertEqual(30000, self.state['budget']['tokens_used'])
        self.assertFalse(any(kind.startswith('tool/') for kind, _ in self.events))
        self.assertEqual(2, sum(kind == 'runtime/git-result' for kind, _ in self.events))

    def test_static_snapshot_default_refuses_cancelled_thread_before_git_spawn(self):
        event = threading.Event(); event.set()
        previous = getattr(local, 'cancel_event', None); local.cancel_event = event
        try:
            with patch('workbench.execution.spawn_owned_process') as spawn:
                with self.assertRaisesRegex(RuntimeError, '取消'):
                    DeliveryRuntime._snapshot(self.source, self.root / 'cancelled' / 'workspace', _manifest(self.source, None))
                spawn.assert_not_called()
        finally:
            local.cancel_event = previous

    def test_real_git_binary_and_chinese_diff_apply_preserve_bytes(self):
        original = {'中文.txt':'第一行\r\n第二行\n'.encode('utf-8'), 'binary.dat':bytes(range(256)) + b'\x00\xff'}
        for name, value in original.items(): (self.source / name).write_bytes(value)
        baseline = _manifest(self.source, None)
        child = self.root / 'child' / 'workspace'; parent = self.root / 'parent' / 'workspace'
        DeliveryRuntime._snapshot(self.source, child, baseline)
        DeliveryRuntime._snapshot(self.source, parent, baseline)
        updated = {'中文.txt':'第一行\r\n新内容：库存\n'.encode('utf-8'), 'binary.dat':b'\xff\x00\x80' + bytes(range(255,-1,-1))}
        for name, value in updated.items(): (child / name).write_bytes(value)
        diff = DeliveryRuntime._patch(child, list(updated))
        self.assertIn(b'GIT binary patch', diff)
        patch_path = child.parent / 'changes.patch'; patch_path.write_bytes(diff)
        for flags in (['--check'], []):
            DeliveryRuntime._git_process(['git','apply',*flags,str(patch_path)], cwd=parent)
        for name, value in updated.items(): self.assertEqual(value, (parent / name).read_bytes())
        for name, value in original.items(): self.assertEqual(value, (self.source / name).read_bytes())
        receipts = [json.loads(read_text(path)) for path in self.root.rglob('process.json')]
        diff_receipt = next(value for value in receipts if 'diff' in value['command'])
        self.assertEqual(hashlib.sha256(diff).hexdigest(), diff_receipt['output_patch']['sha256'])
        apply_receipts = [value for value in receipts if 'apply' in value['command']]
        self.assertEqual(2, len(apply_receipts))
        self.assertTrue(all(value['input_patch']['sha256'] == hashlib.sha256(diff).hexdigest() for value in apply_receipts))
        self.assertTrue(all(value['success'] and value['command'] == value['executed_command'] for value in receipts))
        init_receipts = [value for value in receipts if 'init' in value['command']]
        self.assertEqual(2, len(init_receipts))
        self.assertFalse(any(value['command'][1:2] == ['config'] for value in receipts))
        for value in init_receipts:
            template = Path(value['template_config']['path'])
            candidate = Path(value['cwd'])
            self.assertNotIn(candidate, template.parents)
            self.assertEqual(hashlib.sha256(template.read_bytes()).hexdigest(), value['template_config']['sha256'])
            self.assertEqual('false', value['candidate_config']['core.autocrlf'])
            self.assertEqual(hashlib.sha256((candidate / '.git/config').read_bytes()).hexdigest(),
                             value['candidate_config']['sha256'])

    def test_template_write_denial_never_starts_git_or_modifies_source(self):
        before = _manifest(self.source, None)
        candidate = self.root / 'denied' / 'workspace'
        with patch('workbench.file_io.atomic_write_text', side_effect=PermissionError('fixture template denied')), \
             patch('workbench.execution.spawn_owned_process') as spawn:
            with self.assertRaisesRegex(PermissionError, 'template denied'):
                DeliveryRuntime._snapshot(self.source, candidate, before)
            spawn.assert_not_called()
        self.assertFalse((candidate / '.git').exists())
        self.assertEqual(before, _manifest(self.source, None))

    def test_failed_apply_is_rejected_with_independent_actual_receipt(self):
        candidate = self.root / 'candidate' / 'workspace'
        DeliveryRuntime._snapshot(self.source, candidate, _manifest(self.source, None))
        bad_patch = candidate.parent / 'invalid.patch'; bad_patch.write_bytes(b'not a valid patch\x00\xff')
        command = ['git','apply','--check',str(bad_patch)]
        with self.assertRaises(subprocess.CalledProcessError):
            self.runtime._git('item', 'parent.apply-check', command, cwd=candidate)
        receipt = json.loads(read_text(next(self.runtime.runtime.rglob('process.json'))))
        self.assertFalse(receipt['success']); self.assertNotEqual(0, receipt['returncode'])
        self.assertEqual(command, receipt['executed_command'])
        self.assertEqual(hashlib.sha256(bad_patch.read_bytes()).hexdigest(), receipt['input_patch']['sha256'])
        self.assertEqual('before', (candidate / 'a.txt').read_text())
        self.assertEqual('runtime/git-result', self.events[-1][0])

    def test_exhausted_parent_budget_never_starts_another_git_process(self):
        self.state['started_at'] = time.time() - 31
        with patch('workbench.execution.spawn_owned_process') as spawn:
            with self.assertRaisesRegex(RuntimeError, '时间预算'):
                self.runtime._git('item','subtask.a.snapshot',['git','init'],cwd=self.source)
            spawn.assert_not_called()

    def test_changed_patch_between_check_and_apply_blocks_parent_acceptance(self):
        phases = []
        def snapshot(source, workspace, files, **options):
            workspace.mkdir(parents=True)
            for relative in files: (workspace / relative).write_bytes((source / relative).read_bytes())
        def task_run(tasks, task, actor, **options):
            self.tasks[task]['status'] = 'review'; return self.tasks[task]
        def git(item, phase, command, **options):
            phases.append(phase)
            self.assertEqual('parent.apply-check',phase)
            Path(command[-1]).write_bytes(b'tampered patch')
            return subprocess.CompletedProcess(command,0)
        with patch('workbench.delivery_runtime.manifest',side_effect=_manifest), \
             patch.object(DeliveryRuntime,'_snapshot',side_effect=snapshot), \
             patch.object(DeliveryRuntime,'_patch',return_value=b'original patch'), \
             patch.object(self.runtime,'_git',side_effect=git), \
             patch('workbench.delivery_runtime.run_task',side_effect=task_run), \
             patch('workbench.delivery_runtime.CandidateProjectEval',side_effect=lambda *a, **k:lambda:{}):
            self.runtime._run_subtasks_owned('item','fixture-owner')
        self.assertEqual(['parent.apply-check'],phases)
        self.assertEqual('failed',self.state['state'])
        self.assertIn('补丁文件已变化',self.state['error'])
        self.assertEqual('failed',self.tasks['task-0']['status'])
        self.assertEqual('before',(self.source / 'a.txt').read_text())
