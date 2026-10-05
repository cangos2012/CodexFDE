"""Read-only draft generation with its own lifecycle, never delivery acceptance."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .file_io import read_bytes, read_text
from .learning import LearningStore, canonical, digest, human, required, strings
from .maintenance import MaintenanceGate, MaintenanceBusy
from .reference_paths import resolve_reference, reference_mapping_scope


def _initialize(tasks):
    with tasks.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS learning_generations (
            id TEXT PRIMARY KEY, initiative_id TEXT NOT NULL, status TEXT NOT NULL,
            actor TEXT NOT NULL, input_payload TEXT NOT NULL, input_sha256 TEXT NOT NULL,
            output_payload TEXT, output_sha256 TEXT, artifacts TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, finished_at REAL)''')


def collect_input(tasks, initiative_id, fields):
    learning = LearningStore(tasks.path)
    kind = fields.get('kind')
    if kind not in {'memory', 'workflow'}:
        raise ValueError('请选择记忆或流程草稿')
    task_id = required(fields.get('task_id'), '来源任务')
    options = learning.source_options(initiative_id)
    source = next((s for s in options['tasks'] if s['id'] == task_id), None)
    if not source:
        raise ValueError('生成来源必须是本事项已验收任务或已具名接受失败反馈')
    feedback_id = str(fields.get('feedback_id') or '')
    feedback = None
    if feedback_id:
        if not any(f['id'] == feedback_id and f['task_id'] == task_id for f in options['feedback']):
            raise ValueError('失败反馈不属于本事项来源任务或尚未具名接受')
        with tasks.connect() as db:
            feedback = dict(db.execute('SELECT * FROM feedback WHERE id=?', (feedback_id,)).fetchone())
    if not source['eligible_success'] and not feedback:
        raise ValueError('失败来源必须指定已具名接受的反馈')
    supersedes = str(fields.get('supersedes') or '')
    if supersedes:
        previous = learning.get(supersedes)
        if previous['project'] != learning.project(initiative_id) or previous['kind'] != kind:
            raise ValueError('替代版本必须属于同一项目和类型')
    task = tasks.get(task_id)
    learning.report(task, passing=source['eligible_success'])
    snapshot = {k: task.get(k) for k in ('id', 'status', 'request', 'spec', 'error',
                'reviewed_by', 'review_decision', 'review_note', 'result', 'events')}
    runtime = Path(tasks.path).resolve().parent
    evidence = [{'id': 'source', 'kind': 'task', 'sha256': digest(snapshot), 'content': snapshot}]
    if feedback:
        evidence.append({'id': 'feedback', 'kind': 'accepted_failure', 'sha256': digest(feedback), 'content': feedback})
    files = {}
    report = learning.report(task)
    if report:
        files[report['path']] = report['sha256']
    runner = (task.get('result') or {}).get('runner') or {}
    if runner.get('process_path') and runner.get('process_sha256'):
        files[runner['process_path']] = runner['process_sha256']
    for event in task['events']:
        item = event.get('evidence') or {}
        if item.get('patch_path') and item.get('patch_sha256'):
            files[item['patch_path']] = item['patch_sha256']
        for key, path in (item.get('artifacts') or {}).items():
            sha = (item.get('artifact_sha256') or {}).get(key)
            if path and sha:
                files[path] = sha
    for index, (path, sha) in enumerate(sorted(files.items())):
        file = Path(path)
        file = resolve_reference(file, runtime).resolve() if file.is_absolute() else (runtime / file).resolve()
        if not file.is_relative_to(runtime) or not file.is_file() or file.stat().st_size > 5_000_000:
            raise ValueError('来源证据文件缺失、过大或越过运行目录')
        with reference_mapping_scope(runtime, {}):
            raw = read_bytes(file)
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('来源证据文件已被替换')
        evidence.append({'id': 'file-' + str(index + 1), 'kind': 'artifact', 'path': str(file),
                         'sha256': sha, 'content': raw.decode('utf-8', errors='replace')[:8000],
                         'truncated': len(raw) > 8000})
    return {'initiative_id': initiative_id, 'project': learning.project(initiative_id),
            'kind': kind, 'task_id': task_id, 'feedback_id': feedback_id, 'supersedes': supersedes,
            'guidance': required(fields['guidance'], '补充说明', 4000) if fields.get('guidance') else '',
            'evidence': evidence}


def _record(tasks, generation_id, initiative_id=None):
    with tasks.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_generations'").fetchone():
            raise ValueError('生成记录不存在')
        row = db.execute('SELECT * FROM learning_generations WHERE id=?', (generation_id,)).fetchone()
    if not row or initiative_id is not None and row['initiative_id'] != initiative_id:
        raise ValueError('生成记录不属于本事项或不存在')
    result = dict(row)
    result['input'] = json.loads(result.pop('input_payload'))
    if digest(result['input']) != result['input_sha256']:
        raise ValueError('生成输入快照被修改')
    payload = result.pop('output_payload')
    result['output'] = json.loads(payload) if payload else None
    if result['output'] is not None and digest(result['output']) != result['output_sha256']:
        raise ValueError('生成输出快照被修改')
    result['artifacts'] = json.loads(result['artifacts'])
    return result


def _citations(value, packet):
    if not isinstance(value, list) or not value or len(value) > 20:
        raise ValueError('生成结论必须逐项引用已采集证据（最多 20 项）')
    known = {e['id'] for e in packet['evidence']}
    citations = []
    for item in value:
        if not isinstance(item, dict) or item.get('evidence_id') not in known:
            raise ValueError('生成引用不在来源证据清单中')
        citations.append({'claim': required(item.get('claim'), '引用结论', 1000), 'evidence_id': item['evidence_id']})
    if not any(c['evidence_id'] == 'source' for c in citations):
        raise ValueError('生成草稿必须引用原始任务证据')
    return citations


def validate_output(value, packet):
    if not isinstance(value, dict) or set(value) != {'candidate', 'evidence_refs'}:
        raise ValueError('Codex 草稿结构不完整')
    candidate = value['candidate']
    expected = {'title', 'content', 'applies', 'excludes', 'boundary', 'conflict_key', 'recipe'}
    if not isinstance(candidate, dict) or set(candidate) != expected:
        raise ValueError('Codex 候选字段不完整')
    result = {k: required(candidate.get(k), k, 200 if k in {'title', 'conflict_key'} else 4000)
              for k in ('title', 'content', 'boundary', 'conflict_key')}
    result['applies'] = strings(candidate.get('applies'), '适用关键词')
    result['excludes'] = strings(candidate.get('excludes'), '排除关键词', empty=True)
    if packet['kind'] == 'workflow':
        result['recipe'] = LearningStore.recipe(candidate.get('recipe'))
        if result['recipe'].get('schema_version') != 2:
            raise ValueError('生成流程必须使用可执行的 v2 四阶段约束')
        LearningStore.expanded_recipe({'recipe': result['recipe']},
            {p: 'parameter-value' for p in result['recipe']['parameters']})
    else:
        if candidate.get('recipe') is not None:
            raise ValueError('记忆候选不得包含流程执行定义')
        result['recipe'] = None
    return {'candidate': result, 'evidence_refs': _citations(value['evidence_refs'], packet)}


def validate_generated_candidate(tasks, initiative_id, fields):
    record = _record(tasks, fields['generation_id'], initiative_id)
    if record['status'] != 'succeeded' or record['output'] is None:
        raise ValueError('生成草稿尚未成功，不能保存候选')
    packet = record['input']
    for key in ('kind', 'task_id', 'feedback_id', 'supersedes'):
        if str(fields.get(key) or '') != str(packet.get(key) or ''):
            raise ValueError('候选来源或类型与生成快照不一致')
    if digest(collect_input(tasks, initiative_id, packet)) != record['input_sha256']:
        raise ValueError('生成所依据的来源已变化，请重新生成')
    refs = _citations(fields.get('evidence_refs'), packet)
    _validate_artifacts(tasks, record)
    original = record['output']['candidate']
    edited = [key for key, value in original.items() if fields.get(key) != value]
    return {'id': record['id'], 'input_sha256': record['input_sha256'],
            'output_sha256': record['output_sha256'], 'evidence_refs': refs,
            'human_edited_fields': edited, 'generated_by': 'codex', 'saved_as_unreviewed_candidate': True}


def _validate_artifacts(tasks, record):
    runtime = Path(tasks.path).resolve().parent
    entries = list(record['artifacts'].values()) + [e for e in record['input']['evidence'] if e.get('path')]
    for artifact in entries:
        file = resolve_reference(artifact['path'], runtime).resolve()
        if not file.is_relative_to(runtime) or not file.is_file():
            raise ValueError('生成过程文件丢失或被替换')
        with reference_mapping_scope(runtime, {}):
            if hashlib.sha256(read_bytes(file)).hexdigest() != artifact['sha256']:
                raise ValueError('生成过程文件丢失或被替换')


def validate_generation_reference(tasks, reference):
    record = _record(tasks, reference['id'])
    if (record['status'] != 'succeeded' or reference['input_sha256'] != record['input_sha256']
            or reference['output_sha256'] != record['output_sha256']):
        raise ValueError('生成来源快照不一致')
    _validate_artifacts(tasks, record)


def _generation_view(record):
    """Project one already-validated snapshot without querying other history."""
    record = dict(record)
    packet = record.pop('input')
    output = record.pop('output')
    record.update({key: packet[key] for key in ('kind', 'task_id', 'feedback_id', 'supersedes')})
    record['candidate'] = (output['candidate'] | {key: packet[key] for key in ('kind', 'task_id', 'feedback_id', 'supersedes')}
        | {'generation_id': record['id'], 'evidence_refs': output['evidence_refs']}) if output else None
    record['evidence_refs'] = output['evidence_refs'] if output else []
    record['evidence'] = [{k: e[k] for k in ('id', 'kind', 'sha256', 'path', 'truncated') if k in e} for e in packet['evidence']]
    return record


def generation_view(tasks, initiative_id, limit=20):
    with tasks.connect() as db:
        present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_generations'").fetchone()
        if not present:
            return []
        ids = [row['id'] for row in db.execute('SELECT id FROM learning_generations WHERE initiative_id=? ORDER BY created_at DESC LIMIT ?',
                                             (initiative_id, limit))]
    return [_generation_view(_record(tasks, generation_id, initiative_id)) for generation_id in ids]


class CodexLearningGenerator:
    def __call__(self, repository, runtime, folder, packet, cancel_event):
        from .codex_options import headless_options
        from .daily_delivery import manifest
        from .execution import CodexExecutionRunner
        from .execution_control import local
        runner = CodexExecutionRunner(repository, runtime)
        capability = runner.capabilities()
        if not capability['codex_available']:
            raise ValueError(capability['reason'])
        string = {'type': 'string'}
        array = {'type': 'array', 'items': string}
        def obj(fields):
            return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
        check = obj({'kind': {'type': 'string', 'enum': ['file_exists', 'file_contains']}, 'path': string, 'text': string})
        recipe = obj({'schema_version': {'type': 'integer', 'enum': [2]}, 'parameters': array,
            'preconditions': {'type': 'array', 'items': check},
            'steps': {'type': 'array', 'items': obj({'phase': string, 'role': string, 'depends_on': array, 'instruction': string})},
            'authorization': {'type': 'string', 'enum': ['confirmed_plan']}, 'eval_entry': {'type': 'string', 'enum': ['project_blocking']},
            'outputs': array, 'stop': string, 'rollback': string,
            'stage_checks': obj({p: {'type': 'array', 'items': check} for p in ('precheck', 'implement', 'eval')}),
            'required_files': {'type': 'array', 'items': obj({'phase': {'type': 'string', 'enum': ['implement', 'eval']}, 'path': string})},
            'required_evidence': array, 'recovery': {'type': 'string', 'enum': ['retain_candidate_new_plan']}})
        candidate = obj({'title': string, 'content': string, 'applies': array, 'excludes': array,
            'boundary': string, 'conflict_key': string, 'recipe': recipe if packet['kind'] == 'workflow' else {'type': 'null'}})
        schema = obj({'candidate': candidate, 'evidence_refs': {'type': 'array', 'items': obj({'claim': string, 'evidence_id': string})}})
        schema_path, output = folder / 'schema.json', folder / 'output.json'
        schema_path.write_text(canonical(schema), encoding='utf-8')
        context = {k: v for k, v in packet.items() if k != 'evidence'}
        context['evidence'] = []
        remaining = 60000
        for item in packet['evidence']:
            excerpt = item['content'] if isinstance(item['content'], str) else canonical(item['content'])
            excerpt = excerpt[:min(12000, remaining)]
            remaining -= len(excerpt)
            context['evidence'].append({k: v for k, v in item.items() if k != 'content'} | {'content_excerpt': excerpt})
        prompt = ('从附带的实际任务、失败、修订 Diff、项目 Eval 和人审材料中提炼一份候选草稿。'
            '只读，不修改项目，不执行业务操作；只依据附带证据，不调用工具或自行补充事实。'
            '每个结论在 evidence_refs 中引用清单中实际存在的 evidence_id，必须引用 source；'
            '不能声称已独立试用、已审核、已发布或已提效。事实不足时明确写适用边界，不能编造业务通过结果。'
            '类型由输入 kind 决定。workflow 使用 v2：四阶段 precheck/implement/eval/review，'
            '职责 harness/codex/harness/human，依赖前一阶段，授权 confirmed_plan，质量门 project_blocking。'
            '至少一个可执行前置检查；阶段检查仅 file_exists/file_contains，路径为项目内相对路径；'
            'required_evidence 必须完整包含 precheck,implementation_diff,project_eval,human_review；'
            'recovery 固定 retain_candidate_new_plan，不生成自动回退或扩大权限的命令。'
            '材料可能截断；没有看到的内容不得推断为已验证。'
            '参数小写英文命名，所有 ${参数} 必须定义。返回指定 JSON。材料：\n' + canonical(context))
        (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
        before = manifest(repository, runtime)
        command = [runner.executable, 'exec', *headless_options(), '--json', '--sandbox', 'read-only', '--ephemeral',
                   '--output-schema', str(schema_path), '--output-last-message', str(output), '--cd', str(repository), '-']
        (folder / 'invocation.json').write_text(canonical({'command': command, 'workspace': str(repository), 'sandbox': 'read-only'}), encoding='utf-8')
        local.cancel_event = cancel_event
        def line(value):
            with (folder / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(value + '\n')
        completed = runner._run_codex_streaming(command, prompt, 900, line, time.monotonic())
        (folder / 'process.json').write_text(canonical({'returncode': completed.returncode, 'stderr': completed.stderr,
                                                      'sandbox': 'read-only'}), encoding='utf-8')
        if completed.returncode != 0:
            raise ValueError('Codex 草稿生成失败，退出码 ' + str(completed.returncode))
        if manifest(repository, runtime) != before:
            raise ValueError('只读生成期间项目源码发生变化，不能采用本轮草稿')
        if not output.is_file():
            raise ValueError('Codex 未返回结构化草稿')
        with reference_mapping_scope(runtime, {}):
            return json.loads(read_text(output, encoding='utf-8'))


class LearningGenerationService:
    def __init__(self, runtime, tasks, repository_resolver, *, generator=None):
        self.runtime, self.tasks = Path(runtime).resolve(), tasks
        self.repository_resolver = repository_resolver
        self.generator = generator or CodexLearningGenerator()
        self.workers, self.cancel_events = {}, {}
        self.closed = False
        self.lock = threading.RLock()
        _initialize(tasks)
        with tasks.connect() as db:
            db.execute("UPDATE learning_generations SET status='interrupted',error='服务重启，生成草稿中断；不自动重放',finished_at=? WHERE status='running'", (time.time(),))

    def start(self, initiative_id, actor, fields):
        actor = human(actor)
        if not isinstance(fields, dict):
            raise ValueError('生成请求必须为对象')
        with self.lock, MaintenanceGate(self.runtime).write():
            if self.closed:
                raise ValueError('生成服务已停止，不能启动新草稿')
            with self.tasks.connect() as db:
                if db.execute("SELECT 1 FROM learning_generations WHERE initiative_id=? AND status='running'", (initiative_id,)).fetchone():
                    raise ValueError('本事项已有草稿正在生成')
            packet = collect_input(self.tasks, initiative_id, fields)
            generation_id = 'GEN-' + uuid.uuid4().hex[:16]
            with self.tasks.connect() as db:
                db.execute('INSERT INTO learning_generations(id,initiative_id,status,actor,input_payload,input_sha256,created_at) VALUES(?,?,?,?,?,?,?)',
                           (generation_id, initiative_id, 'running', actor, canonical(packet), digest(packet), time.time()))
            self.cancel_events[generation_id] = threading.Event()
            thread = threading.Thread(target=self._run, args=(generation_id,), daemon=True)
            self.workers[generation_id] = thread
            thread.start()
        return self.get(initiative_id, generation_id)

    def get(self, initiative_id, generation_id):
        return _generation_view(_record(self.tasks, generation_id, initiative_id))

    def list(self, initiative_id):
        return generation_view(self.tasks, initiative_id)

    def cancel(self, initiative_id, generation_id, actor):
        human(actor)
        record = _record(self.tasks, generation_id, initiative_id)
        if record['status'] != 'running':
            raise ValueError('此生成记录已经结束')
        event = self.cancel_events.get(generation_id)
        if event:
            event.set()
        with MaintenanceGate(self.runtime).write(), self.tasks.connect() as db:
            db.execute("UPDATE learning_generations SET status='cancelled',error='用户取消生成，原始过程保留',finished_at=? WHERE id=? AND status='running'", (time.time(), generation_id))
        return self.get(initiative_id, generation_id)

    def busy(self):
        return any(thread.is_alive() for thread in self.workers.values())

    def close(self, timeout=10):
        """Stop owned read-only processes and retain interrupted drafts."""
        with self.lock:
            self.closed = True
            for event in self.cancel_events.values():
                event.set()
            workers = list(self.workers.items())
            storage_error = None
            if workers:
                try:
                    with MaintenanceGate(self.runtime).write(), self.tasks.connect(create=False) as db:
                        for generation_id, _ in workers:
                            db.execute("UPDATE learning_generations SET status='interrupted',error='服务停止，生成中断；不自动重放',finished_at=? WHERE id=? AND status='running'",
                                       (time.time(), generation_id))
                except (OSError, sqlite3.Error, MaintenanceBusy) as error:
                    storage_error = type(error).__name__
        deadline = time.monotonic() + timeout
        for _, worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        return {'closed': True, 'live_generations': [key for key, worker in workers if worker.is_alive()],
                'automatic_replay': False, 'storage_error': storage_error}

    def _run(self, generation_id):
        folder = self.runtime / 'learning-generation' / generation_id
        gate = MaintenanceGate(self.runtime)
        while True:
            try:
                with gate.write():
                    self._run_owned(generation_id, folder)
                return
            except MaintenanceBusy:
                time.sleep(.05)

    def _run_owned(self, generation_id, folder):
        error, output = '', None
        event = self.cancel_events[generation_id]
        try:
            record = _record(self.tasks, generation_id)
            packet = record['input']
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'input.json').write_text(canonical(packet), encoding='utf-8')
            if event.is_set():
                raise ValueError('生成已取消')
            result = self.generator(Path(self.repository_resolver(record['initiative_id'])), self.runtime, folder, packet, event)
            if event.is_set():
                raise ValueError('生成已取消')
            output = validate_output(result, packet)
            if digest(collect_input(self.tasks, record['initiative_id'], packet)) != record['input_sha256']:
                raise ValueError('生成所依据的来源已变化，请重新生成')
            (folder / 'draft.json').write_text(canonical(output), encoding='utf-8')
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        artifacts, artifact_errors = {}, []
        try:
            # These new files are physical paths, not historical references.
            with reference_mapping_scope(self.runtime, {}):
                for file in folder.glob('*'):
                    if file.is_file():
                        try:
                            artifacts[file.name] = {'path': str(file), 'sha256': hashlib.sha256(read_bytes(file)).hexdigest()}
                        except OSError as exc:
                            artifact_errors.append(str(exc))
        except OSError as exc:
            artifact_errors.append(str(exc))
        if artifact_errors:
            error = '\n'.join(filter(None, [error, '生成过程证据无法完整保存：' + '\n'.join(artifact_errors)]))
            output = None
        with self.tasks.connect() as db:
            db.execute('UPDATE learning_generations SET status=?,output_payload=?,output_sha256=?,artifacts=?,error=?,finished_at=? WHERE id=? AND status=\'running\'',
                ('failed' if error else 'succeeded', canonical(output) if output else None,
                 digest(output) if output else None, canonical(artifacts), error, time.time(), generation_id))
            # Cancel retains all process artifacts but cannot become successful.
            if event.is_set():
                db.execute("UPDATE learning_generations SET artifacts=? WHERE id=? AND status IN ('cancelled','interrupted')", (canonical(artifacts), generation_id))
