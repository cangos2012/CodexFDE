"""Project-configured previews of immutable, task-bound candidates."""
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import socket
import time

from .candidate_preview import CandidatePreviews
from .daily_delivery import manifest
from .deployment_process import probe
from .evidence_gate import assert_current_evidence
from .eval_harness import fingerprint
from .process_guard import spawn
from .reference_paths import resolve_reference


class ProjectPreviews(CandidatePreviews):
    def __init__(self, runtime, tasks, projects, configurations):
        super().__init__(runtime, tasks)
        self.projects, self.configurations = projects, configurations
        with tasks.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS preview_plans (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL)')
            for row in db.execute('SELECT id,payload FROM preview_plans').fetchall():
                value = json.loads(row['payload'])
                if value.get('state') == 'starting':
                    value.update(state='interrupted', automatic_replay=False)
                    db.execute('UPDATE preview_plans SET payload=? WHERE id=?', (json.dumps(value, ensure_ascii=False), row['id']))

    def _project(self, task):
        refs = [v[8:] for v in task.get('business_refs', []) if v.startswith('PROJECT:')]
        return self.projects.get(refs[0]) if refs else None

    @contextmanager
    def _configuration_guard(self, project_id, revision):
        with self.configurations.lock:
            current = self.configurations.get(project_id) if project_id else {'configuration_revision': 0}
            if current['configuration_revision'] != revision:
                raise ValueError('预览配置已变化，请重新核对方案')
            yield

    def plan(self, task_id):
        task = self.tasks.get(task_id)
        project = self._project(task)
        from .migration import assert_migration_preflight
        assert_migration_preflight(self.runtime, project['id'] if project else None)
        config = self.configurations.get(project['id']) if project else {'configuration_revision': 0, 'preview_config': None}
        if not config['preview_config']:
            package = next((e.get('evidence') or {} for e in reversed(task['events']) if e.get('detail') == '日常研发交付包已保存'), {})
            workspace = resolve_reference(package.get('workspace', self.runtime / 'course-worktrees' / task_id), self.runtime)
            return {'task_id': task_id, 'available': (workspace / 'web/index.html').is_file(), 'legacy': True,
                    'configuration_revision': config['configuration_revision'], 'command': ['内置FlowERP候选预览'],
                    'expected_candidate_sha256': '', 'notice': '使用已有FlowERP兼容预览；其他项目请登记预览配置。'}
        if task['status'] not in {'review', 'completed'}:
            raise ValueError('候选尚未完成检查')
        assert_current_evidence(task, self.runtime)
        workspace = resolve_reference((task.get('result') or {}).get('runner', {}).get('workspace', ''), self.runtime)
        if not workspace.is_absolute() or workspace.is_symlink() or not workspace.resolve().is_relative_to(self.runtime):
            raise ValueError('预览候选不属于本工作台')
        candidate_sha = fingerprint(manifest(workspace, self.runtime))
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0)); port = reserved.getsockname()[1]
        identifier = secrets.token_hex(16)
        data = self.runtime / 'candidate-previews' / task_id / identifier
        cfg = config['preview_config']
        argv = [p.replace('{workspace}', str(workspace)).replace('{runtime_dir}', str(data)).replace('{port}', str(port)) for p in cfg['command']]
        value = dict(plan_id=identifier, task_id=task_id, project_id=project['id'], available=True, legacy=False,
                     configuration_revision=config['configuration_revision'], expected_candidate_sha256=candidate_sha,
                     workspace=str(workspace), runtime_dir=str(data), command=argv, url=f'http://127.0.0.1:{port}',
                     health=cfg['health'], timeout_seconds=cfg['timeout_seconds'], expires_at=time.time() + 900, state='prepared')
        with self.tasks.connect() as db:
            db.execute('INSERT INTO preview_plans VALUES(?,?,?)', (identifier, task_id, json.dumps(value, ensure_ascii=False)))
        return value

    def start(self, task_id, actor, fields=None):
        if self._closed.is_set():
            raise ValueError('工作台正在关闭，不能启动预览')
        fields = fields or {}
        task = self.tasks.get(task_id)
        project = self._project(task)
        config = self.configurations.get(project['id']) if project else {'configuration_revision': 0, 'preview_config': None}
        if not config['preview_config']:
            if fields.get('plan_id'):
                raise ValueError('预览配置已移除，请重新核对方案')
            assert_current_evidence(task, self.runtime)
            return super().start(task_id, actor, configuration_guard=lambda: self._configuration_guard(
                project['id'] if project else None, config['configuration_revision']))
        from .initiative_workflow import InitiativeWorkflow
        actor = InitiativeWorkflow.actor(actor)
        if fields.get('confirmed') is not True:
            raise ValueError('请核对预览计划并明确确认')
        with self.lock:
            if self._closed.is_set():
                raise ValueError('工作台正在关闭，不能启动预览')
            task = self.tasks.get(task_id)
            config = self.configurations.get(project['id'])
            if task['status'] not in {'review', 'completed'}:
                raise ValueError('任务已返工或停止，请重新核对候选')
            with self.tasks.connect() as db:
                row = db.execute('SELECT payload FROM preview_plans WHERE id=? AND task_id=?', (fields.get('plan_id'), task_id)).fetchone()
            if not row:
                raise ValueError('预览计划不存在')
            plan = json.loads(row[0])
            if plan['state'] != 'prepared' or plan['expires_at'] < time.time():
                raise ValueError('预览计划已过期或已消费')
            assert_current_evidence(task, self.runtime)
            if fields.get('configuration_revision') != plan['configuration_revision'] or config['configuration_revision'] != plan['configuration_revision'] or fields.get('expected_candidate_sha256') != plan['expected_candidate_sha256'] or fingerprint(manifest(plan['workspace'], self.runtime)) != plan['expected_candidate_sha256']:
                raise ValueError('预览候选或配置已变化')
            old = self.running.get(task_id)
            if old and old[0].poll() is None:
                matched = all(old[2].get(k) == plan.get(k) for k in ('expected_candidate_sha256', 'configuration_revision', 'command', 'workspace'))
                if matched:
                    with self._configuration_guard(project['id'], plan['configuration_revision']):
                        return dict(old[2], reused=True, plan_id=plan['plan_id'])
            if old:
                self._stop_process(task_id, old[1])
                del self.running[task_id]
            data = Path(plan['runtime_dir']); data.mkdir(parents=True, exist_ok=False)
            plan.update(state='starting', authorized_by=actor)
            with self.tasks.connect() as db:
                db.execute('UPDATE preview_plans SET payload=? WHERE id=?', (json.dumps(plan, ensure_ascii=False), plan['plan_id']))
            managed = None
            try:
                # A process is owned during startup too. Shutdown can terminate
                # it without waiting for this request's health-check lock.
                with self._configuration_guard(project['id'], plan['configuration_revision']):
                    managed = self._start_process(task_id, plan['command'], plan['workspace'], data,
                                                  log_mode='w', spawn_factory=spawn)
                process = managed.process
                deadline = time.monotonic() + plan['timeout_seconds']
                health = {'passed': False}
                while not self._closed.is_set() and time.monotonic() < deadline and process.poll() is None:
                    health = probe(plan['url'], plan['health'], .5)
                    if health['passed']:
                        break
                    self._closed.wait(.1)
                if self._closed.is_set():
                    raise InterruptedError('工作台关闭，预览启动已中断；不会自动重放')
                if not health['passed'] or process.poll() is not None:
                    raise ValueError('预览健康检查未通过，日志已保留')
                managed.check_output()
                if fingerprint(manifest(plan['workspace'], self.runtime)) != plan['expected_candidate_sha256']:
                    raise ValueError('预览启动期间候选源码变化，已停止预览')
                payload = {**plan, 'state': 'running', 'health_result': health, 'human_accepted': task['status'] == 'completed',
                           'label': '本次候选成果 · 独立预览数据', 'notice': '此候选预览不代表正式发布。'}
                with self._configuration_guard(project['id'], plan['configuration_revision']):
                    with self._process_lock:
                        if self._closed.is_set():
                            raise InterruptedError('工作台关闭，预览启动已中断；不会自动重放')
                        self.running[task_id] = process, managed, payload
                    plan['state'] = 'consumed'
                    with self.tasks.connect() as db:
                        db.execute('UPDATE preview_plans SET payload=? WHERE id=?', (json.dumps(plan, ensure_ascii=False), plan['plan_id']))
                    self.tasks.append_event(task_id, '已打开本项目候选预览', actor=actor, evidence=payload)
                    return payload
            except Exception as error:
                cleanup_error = self._cleanup_failed_process(task_id, managed, error)
                plan.update(state='interrupted' if self._closed.is_set() else 'failed', error=str(error), automatic_replay=False)
                if cleanup_error:
                    plan.update(cleanup_required=True, cleanup_error=cleanup_error)
                with self.tasks.connect() as db:
                    db.execute('UPDATE preview_plans SET payload=? WHERE id=?', (json.dumps(plan, ensure_ascii=False), plan['plan_id']))
                self.tasks.append_event(task_id, '项目预览失败，保留日志且不重放', actor=actor, evidence=plan)
                raise
