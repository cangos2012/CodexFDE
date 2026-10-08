"""Prepared local releases, explicit authorization and independent business review."""
import copy
import hashlib
import json
import logging
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlparse

from .daily_delivery import manifest
from .eval_harness import fingerprint
from .file_io import read_bytes, read_text
from .maintenance import MaintenanceGate
from .deployment_process import probe


class Deployments:
    def __init__(self, runtime, tasks, projects, workflow, configurations, *, executor=None):
        self.runtime, self.tasks = Path(runtime), tasks
        self.projects, self.workflow, self.configurations = projects, workflow, configurations
        self.executor = executor
        self.workers, self.processes, self.cancel_events = {}, {}, {}
        self.lock = threading.RLock()
        self.closed = False
        self.shutdown_errors = []
        with tasks.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS deployment_plans (id TEXT PRIMARY KEY, initiative_id TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS deployments (id TEXT PRIMARY KEY, initiative_id TEXT NOT NULL, payload TEXT NOT NULL)')
            for row in db.execute('SELECT id,payload FROM deployments').fetchall():
                value = json.loads(row['payload'])
                if value['status'] in {'running', 'rolling_back'} or value.get('managed_process_running'):
                    value.update(status='interrupted', automatic_replay=False, business_verified=False,
                                 managed_process_running=False, error='工作台重启，部署进程所有权已失效；未自动重放')
                    db.execute('UPDATE deployments SET payload=? WHERE id=?', (json.dumps(value, ensure_ascii=False), row['id']))

    def _save(self, table, value, *, create=True):
        with self.tasks.connect(create=create) as db:
            db.execute('INSERT OR REPLACE INTO ' + table + ' VALUES(?,?,?)', (value['id'], value['initiative_id'], json.dumps(value, ensure_ascii=False)))

    def _get(self, table, identifier):
        with self.tasks.connect() as db:
            row = db.execute('SELECT payload FROM ' + table + ' WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        return json.loads(row['payload'])

    def list(self, item_id):
        self.workflow.initiatives.get(item_id)
        with self.tasks.connect() as db:
            plans = [json.loads(r[0]) for r in db.execute('SELECT payload FROM deployment_plans WHERE initiative_id=?', (item_id,))]
            items = [json.loads(r[0]) for r in db.execute('SELECT payload FROM deployments WHERE initiative_id=?', (item_id,))]
        return {'plans': plans, 'items': items}

    def _state(self, item_id, revision):
        data = copy.deepcopy(self.workflow._load(item_id))
        if data['revision'] != revision or data['stage'] not in {'integrated', 'released', 'observed'}:
            raise ValueError('请先完成源码集成并读取最新事项版本')
        return data

    @staticmethod
    def _sha(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _accepted(self, data):
        from .evidence_gate import assert_current_evidence
        task = self.tasks.get(data['active_task_id'])
        if task['status'] != 'completed' or task.get('review_decision') != 'approve' or task.get('reviewed_by') != data.get('reviewer'):
            raise ValueError('本次制品缺少指定验收人的接受结果')
        assert_current_evidence(task, self.runtime)
        return task, self._sha({k: task.get(k) for k in ('id', 'status', 'reviewed_by', 'review_decision', 'review_note', 'result')})

    def _plan_hash(self, plan):
        keys = ('plan_id', 'initiative_id', 'profile_id', 'profile_snapshot', 'configuration_revision', 'candidate_sha256',
                'source_manifest', 'workspace', 'origin', 'runtime_dir', 'command', 'rollback_command', 'environment',
                'url', 'health', 'timeout_seconds', 'task_id', 'accepted_evidence_sha256', 'prepared_by', 'prepared_at', 'expires_at')
        return self._sha({k: plan.get(k) for k in keys})

    def _validate_plan(self, plan, data, *, source=True, accepted=True, configuration=True):
        if self._plan_hash(plan) != plan.get('plan_sha256'):
            raise ValueError('冻结部署计划变化，请重新准备')
        if plan['task_id'] != data['active_task_id']:
            raise ValueError('部署计划与本事项当前交付不一致')
        project = self.workflow.project(plan['initiative_id'])
        if Path(project['root_path']).resolve() != Path(plan['origin']).resolve():
            raise ValueError('项目目录变化，请重新准备')
        if configuration:
            current = self.configurations.get(project['id'])
            profile = next((p for p in current['deployment_profiles'] if p['id'] == plan['profile_id']), None)
            if current['configuration_revision'] != plan['configuration_revision'] or self._sha(profile) != self._sha(plan['profile_snapshot']):
                raise ValueError('已消费的部署配置变化，请重新准备')
        if source and manifest(plan['origin'], self.runtime) != plan['source_manifest']:
            raise ValueError('集成源码变化，请重新交付或复验')
        if manifest(plan['workspace'], self.runtime) != plan['source_manifest'] or fingerprint(plan['source_manifest']) != plan['candidate_sha256']:
            raise ValueError('部署制品变化，请重新准备')
        if accepted:
            _, digest = self._accepted(data)
            if digest != plan['accepted_evidence_sha256']:
                raise ValueError('已接受的交付证据变化，请重新准备')

    def prepare(self, item_id, actor, revision, profile_id):
        with self.workflow.lock, self.lock, MaintenanceGate(self.runtime).write():
            if self.closed:
                raise ValueError('工作台正在关闭')
            return self._prepare(item_id, actor, revision, profile_id)

    def _prepare(self, item_id, actor, revision, profile_id):
        actor = self.workflow.actor(actor)
        data = self._state(item_id, revision)
        project = self.workflow.project(item_id)
        from .migration import assert_migration_preflight
        assert_migration_preflight(self.runtime, project['id'])
        config = self.configurations.get(project['id'])
        profile = next((p for p in config['deployment_profiles'] if p['id'] == profile_id), None)
        if not profile:
            raise ValueError('请先登记本项目的部署配置')
        # Recheck accepted evidence and integrated source before preparing a release.
        task, accepted_hash = self._accepted(data)
        root = Path(project['root_path'])
        source = manifest(root, self.runtime)
        internal = self.workflow._load(item_id)
        if source != internal.get('candidate_manifest'):
            raise ValueError('集成后源码已变化，请重新交付或复验')
        identifier = secrets.token_hex(16)
        folder = self.runtime / 'deployments' / identifier
        workspace = folder / 'artifact'
        workspace.mkdir(parents=True)
        for name, digest in source.items():
            raw = read_bytes(root / name)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('制品复制期间源码变化')
            target = workspace / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        from .course_snapshot import _git
        _git(workspace, 'init', '--quiet'); _git(workspace, 'add', '--force', '--all')
        _git(workspace, '-c', 'user.name=Workbench release', '-c', 'user.email=workbench@localhost', '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'Frozen accepted artifact')
        if manifest(root, self.runtime) != source:
            raise ValueError('制品准备期间源码变化')
        runtime_dir = folder / '.runtime'
        def expand(parts):
            return [p.replace('{workspace}', str(workspace)).replace('{runtime_dir}', str(runtime_dir)).replace('{port}', str(__import__('urllib.parse', fromlist=['urlparse']).urlparse(profile['url']).port or 80)) for p in parts]
        value = dict(id=identifier, plan_id=identifier, initiative_id=item_id, profile_id=profile_id,
                     profile_snapshot=copy.deepcopy(profile), accepted_evidence_sha256=accepted_hash,
                     configuration_revision=config['configuration_revision'], candidate_sha256=fingerprint(source),
                     source_manifest=source, workspace=str(workspace), origin=str(root), runtime_dir=str(runtime_dir),
                     command=expand(profile['command']), rollback_command=expand(profile['rollback_command']),
                     environment=profile['environment'], url=profile['url'], health=profile['health'],
                     timeout_seconds=profile['timeout_seconds'], task_id=task['id'],
                     status='prepared', prepared_by=actor, prepared_at=time.time(), expires_at=time.time() + 900,
                     workflow_revision=revision)
        value['plan_sha256'] = self._plan_hash(value)
        self._validate_plan(value, self._state(item_id, revision))
        self._save('deployment_plans', value)
        return value

    def start(self, item_id, actor, revision, plan_id, confirmed):
        actor = self.workflow.actor(actor)
        if confirmed is not True:
            raise ValueError('请核对具体部署计划后明确授权')
        with self.workflow.lock, self.lock, MaintenanceGate(self.runtime).write():
            if self.closed:
                raise ValueError('工作台正在关闭')
            data = self._state(item_id, revision)
            from .migration import assert_migration_preflight
            assert_migration_preflight(self.runtime, self.workflow.project(item_id)['id'])
            plan = self._get('deployment_plans', plan_id)
            if plan['initiative_id'] != item_id or plan['status'] != 'prepared' or plan['expires_at'] < time.time():
                raise ValueError('部署计划已失效或已消费')
            self._validate_plan(plan, data)
            if any(self._get('deployments', k)['initiative_id'] == item_id for k in self.processes) or any(t.is_alive() and self._get('deployments', k)['initiative_id'] == item_id for k, t in self.workers.items()):
                raise ValueError('本事项仍有受管部署，请先明确回退或关闭')
            value = {**plan, 'id': secrets.token_hex(16), 'deployment_id': None, 'status': 'running',
                     'authorized_by': actor, 'started_at': time.time(), 'business_verified': False, 'automatic_replay': False}
            value['deployment_id'] = value['id']
            plan['status'] = 'consumed'; self._save('deployment_plans', plan); self._save('deployments', value)
            self._launch(value, False)
            return value

    def _launch(self, value, rollback):
        self.cancel_events[value['id']] = threading.Event()
        worker = threading.Thread(target=self._execute, args=(copy.deepcopy(value), rollback), daemon=True, name='deployment-' + value['id'])
        self.workers[value['id']] = worker; worker.start()

    def _stop_process(self, identifier):
        with self.lock:
            process = self.processes.get(identifier)
        if process:
            process.close()
            with self.lock:
                if self.processes.get(identifier) is process:
                    self.processes.pop(identifier)

    def _cleanup_process(self, value):
        """Cleanup failure is evidence, and cannot suppress the execution result."""
        try:
            self._stop_process(value['id'])
            value.update(cleanup_required=False, managed_process_running=False)
            return True
        except Exception as error:
            with self.lock:
                owned = self.processes.get(value['id'])
            process = owned.process if owned else None
            receipt = dict(deployment_id=value['id'], status='failed', error=str(error), captured_at=time.time(),
                           process_id=process.pid if process else None, returncode=process.poll() if process else None,
                           owner_pending=bool(owned and getattr(owned, 'owner', None)),
                           readers_alive=sum(r.is_alive() for r in getattr(owned, 'readers', [])))
            value.update(cleanup_required=True, cleanup_error=str(error), business_verified=False,
                         managed_process_running=bool(process and process.poll() is None))
            try:
                path = self.runtime / 'deployments' / value['plan_id'] / 'cleanup' / (value['id'] + '-' + secrets.token_hex(8) + '.json')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
                sha = hashlib.sha256(read_bytes(path)).hexdigest()
                value.update(cleanup_path=str(path), cleanup_sha256=sha)
                value.setdefault('cleanup_history', []).append(dict(path=str(path), sha256=sha, error=str(error)))
            except Exception as receipt_error:
                value['cleanup_receipt_error'] = str(receipt_error)
            return False

    def _execute(self, value, rollback):
        with MaintenanceGate(self.runtime).write():
            event = self.cancel_events[value['id']]
            owned = None
            try:
                if event.is_set():
                    raise InterruptedError('部署已中断，未执行命令')
                folder = self.runtime / 'deployments' / value['plan_id']
                Path(value['runtime_dir']).mkdir(parents=True, exist_ok=True)
                argv = value['rollback_command'] if rollback else value['command']
                if self.executor:
                    process = self.executor(argv, value['workspace'], value['timeout_seconds'])
                    result = dict(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
                    health = probe(value['url'], value['profile_snapshot']['health']) if process.returncode == 0 else {'passed': False}
                else:
                    target = urlparse(value['url'])
                    with socket.socket(socket.AF_INET6 if ':' in target.hostname else socket.AF_INET) as port_check:
                        port_check.settimeout(.2)
                        if port_check.connect_ex((target.hostname, target.port or 80)) == 0:
                            raise ValueError('目标端口已被其他服务占用，不能把旧服务的健康结果作为本次部署证据')
                    from .deployment_process import OwnedCommand
                    with self.lock:
                        if self.closed or event.is_set():
                            raise InterruptedError('工作台关闭，未启动部署进程')
                        owned = OwnedCommand(argv, value['workspace'])
                        self.processes[value['id']] = owned
                    deadline, health = time.monotonic() + value['timeout_seconds'], {'passed': False}
                    while not event.is_set():
                        code = owned.process.poll()
                        if code is not None and code != 0:
                            break
                        health = probe(value['url'], value['profile_snapshot']['health'], timeout=min(1, max(.05, deadline-time.monotonic())))
                        if health['passed'] or time.monotonic() >= deadline:
                            break
                        event.wait(.05)
                    if health['passed']:
                        event.wait(.05)
                    result = owned.receipt()
                receipt = dict(command=argv, cwd=value['workspace'], deployment_id=value['id'],
                               plan_sha256=value['plan_sha256'], started_at=value['started_at'], captured_at=time.time(),
                               managed_service=result['returncode'] is None, **result)
                path = folder / ('rollback-' if rollback else 'process-') / (value['id'] + '.json')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
                value.update(process_path=str(path), process_sha256=hashlib.sha256(read_bytes(path)).hexdigest())
                if event.is_set():
                    raise InterruptedError('工作台关闭或部署中断；未自动重放')
                if result['returncode'] not in (None, 0):
                    value.update(status='rollback_failed' if rollback else 'failed', health={'passed': False}, error='部署命令未成功，未自动重放')
                elif not health['passed']:
                    value.update(health=health, status='rollback_failed' if rollback else 'failed', error='当前健康检查未通过，须明确回退')
                else:
                    data = copy.deepcopy(self.workflow._load(value['initiative_id']))
                    self._validate_plan(self._get('deployment_plans', value['plan_id']), data,
                                        source=not rollback, accepted=not rollback, configuration=not rollback)
                    value.update(health=health, status='rolled_back' if rollback else 'awaiting_business_review')
                keep = owned and result['returncode'] is None and health['passed'] and value['status'] in {'awaiting_business_review', 'rolled_back'}
                value.update(finished_at=time.time(), managed_process_running=bool(keep))
                if not keep:
                    if not self._cleanup_process(value):
                        value.update(status='rollback_failed' if rollback else 'failed',
                                     error=value.get('error') or '部署进程清理未完成，须人工重试清理')
            except InterruptedError as exc:
                value.update(status='interrupted', business_verified=False, error=str(exc), finished_at=time.time())
                self._cleanup_process(value)
            except Exception as exc:
                value.update(status='rollback_failed' if rollback else 'failed', error=str(exc), finished_at=time.time())
                self._cleanup_process(value)
            with self.lock:
                if self.closed or event.is_set():
                    value.update(status='interrupted', business_verified=False, managed_process_running=False, automatic_replay=False)
                try:
                    self._save('deployments', value, create=False)
                except Exception as error:
                    self.shutdown_errors.append(str(error))
                    logging.getLogger(__name__).warning('Deployment result could not be persisted: %s', error)
                    return
                closing = self.closed
            if not closing:
                self.tasks.append_event(value['task_id'], '本机部署回退完成' if rollback else '本机部署执行完成', actor=value['authorized_by'], evidence=value)

    def verify(self, item_id, actor, revision, deployment_id, evidence, conclusion):
        with self.workflow.lock, self.lock, MaintenanceGate(self.runtime).write():
            return self._verify(item_id, actor, revision, deployment_id, evidence, conclusion)

    def _verify(self, item_id, actor, revision, deployment_id, evidence, conclusion):
        actor = self.workflow.actor(actor)
        state = self._state(item_id, revision)
        value = self._get('deployments', deployment_id)
        if value['initiative_id'] != item_id or value['status'] != 'awaiting_business_review':
            raise ValueError('部署尚未通过健康检查或已审核')
        if actor != state.get('reviewer'):
            raise ValueError('请由本事项指定验收人核对发布后的业务结果')
        if conclusion not in {'pass', 'fail'} or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 4000:
            raise ValueError('请填写实际业务复核证据与结论')
        plan = self._get('deployment_plans', value['plan_id'])
        self._validate_plan(plan, state)
        if plan['status'] != 'consumed':
            raise ValueError('本次部署尚未消费冻结计划')
        receipt = Path(value['process_path'])
        if hashlib.sha256(read_bytes(receipt)).hexdigest() != value['process_sha256']:
            raise ValueError('部署回执变化')
        received = json.loads(read_text(receipt))
        if received['command'] != plan['command'] or received['cwd'] != plan['workspace'] or received.get('plan_sha256') != plan['plan_sha256'] or received['returncode'] not in (None, 0):
            raise ValueError('部署回执与冻结命令不一致或命令未通过')
        if received.get('managed_service'):
            process = self.processes.get(value['id'])
            if not process or process.process.poll() not in (None, 0):
                raise ValueError('受管部署进程已终止，请明确回退或重新准备')
            if process.process.poll() == 0:
                # A finite deployment command may complete just after the startup probe.
                exit_path = receipt.with_name(receipt.stem + '-exit.json')
                exit_path.write_text(json.dumps(process.receipt(), ensure_ascii=False), encoding='utf-8')
                value.update(exit_process_path=str(exit_path), exit_process_sha256=hashlib.sha256(read_bytes(exit_path)).hexdigest(),
                             managed_process_running=False)
                self._stop_process(value['id'])
        current_health = probe(value['url'], plan['health'])
        if conclusion == 'pass' and not current_health['passed']:
            raise ValueError('当前健康检查未通过')
        self._validate_plan(plan, self._state(item_id, revision))
        value.update(business_verified=conclusion == 'pass', business_evidence=evidence, reviewed_by=actor,
                     reviewed_at=time.time(), status='released' if conclusion == 'pass' else 'business_failed', health=current_health)
        if conclusion == 'pass':
            self.workflow.record_delivery(item_id, actor, revision, 'release',
                {'version': value['plan_id'], 'environment': value['environment'], 'evidence': str(receipt) + '\n' + evidence})
        self._save('deployments', value)
        self.tasks.append_event(value['task_id'], '发布后业务复核通过' if conclusion == 'pass' else '发布后业务复核失败', actor=actor, evidence=value)
        return value

    def rollback(self, item_id, actor, revision, deployment_id, confirmed):
        actor = self.workflow.actor(actor)
        if confirmed is not True:
            raise ValueError('请核对登记的回退命令后明确授权')
        with self.workflow.lock, self.lock, MaintenanceGate(self.runtime).write():
            if self.closed:
                raise ValueError('工作台正在关闭')
            state = self._state(item_id, revision)
            value = self._get('deployments', deployment_id)
            plan = self._get('deployment_plans', value['plan_id'])
            if value['initiative_id'] != item_id or value['status'] in {'running', 'rolling_back', 'rolled_back'} or not value['rollback_command']:
                raise ValueError('本次部署不可回退或没有登记回退命令')
            # Source/config drift must not prevent an explicitly authorized recovery.
            self._validate_plan(plan, state, source=False, accepted=False, configuration=False)
            self._stop_process(value['id'])
            value.update(status='rolling_back', authorized_by=actor, business_verified=False,
                         managed_process_running=False, rollback_authorized_at=time.time(), started_at=time.time(),
                         rollback_command=plan['rollback_command'])
            current = self.workflow._load(item_id)
            current.update(stage='integrated', current_release=None, observation_status='回退已授权，待重新发布并业务复核')
            self.workflow._event(current, 'user', '明确授权本机部署回退，原发布记录保留；不再作为当前发布',
                                 actor=actor, deployment_id=value['id'], plan_id=value['plan_id'])
            self.workflow._save(current)
            self._save('deployments', value); self._launch(value, True)
            return value

    def busy(self):
        with self.lock:
            return any(t.is_alive() for t in self.workers.values()) or bool(self.processes)

    def close(self):
        with self.lock:
            self.closed = True
            for event in self.cancel_events.values():
                event.set()
            identifiers, workers = list(self.processes), list(self.workers.values())
        for identifier in identifiers:
            try:
                self._stop_process(identifier)
            except Exception as error:
                self.shutdown_errors.append(str(error))
                logging.getLogger(__name__).warning('Deployment process shutdown failed: %s', error)
        deadline = time.monotonic() + 5
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(max(0, deadline-time.monotonic()))
        with self.lock:
            if self.cancel_events:
                try:
                    with self.tasks.connect(create=False) as db:
                        for identifier in self.cancel_events:
                            row = db.execute('SELECT payload FROM deployments WHERE id=?', (identifier,)).fetchone()
                            if not row:
                                continue
                            value = json.loads(row['payload'])
                            pending = self.processes.get(identifier)
                            if value['status'] in {'running', 'rolling_back'} or value.get('managed_process_running') or value.get('cleanup_required'):
                                value.update(status='interrupted', business_verified=False,
                                             managed_process_running=bool(pending and pending.process.poll() is None),
                                             cleanup_required=bool(pending), automatic_replay=False,
                                             error='工作台关闭，进程清理尚未完成；未自动重放' if pending else '工作台关闭，受管部署进程已停止；未自动重放')
                                db.execute('UPDATE deployments SET payload=? WHERE id=?',
                                           (json.dumps(value, ensure_ascii=False), identifier))
                except Exception as error:
                    self.shutdown_errors.append(str(error))
                    logging.getLogger(__name__).warning('Deployment shutdown could not persist state: %s', error)
        return {'closed': True, 'workers_remaining': sum(t.is_alive() for t in workers),
                'processes_remaining': len(self.processes), 'errors': list(self.shutdown_errors)}

    shutdown = close
