"""Evidence-bound, project-scoped memories and executable delivery recipes.

Content and adoption snapshots are append-only. Status changes never rewrite
historical snapshots. Recipes orchestrate the existing Harness, not shell code.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from .task_store import TaskStore


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def human(value):
    value = required(value, '操作人', 80)
    if value.lower() in {'ai', 'codex', 'system', '待确认', '待定', 'tbd', 'pending'} or value.lower().startswith('agent:'):
        raise ValueError('需要真实具名人审核或采用')
    return value


def required(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(label + '必须是非空文本且不超过 ' + str(limit) + ' 字')
    return value.strip()


def strings(value, label, *, empty=False):
    if not isinstance(value, list) or len(value) > 20 or (not empty and not value):
        raise ValueError(label + '需要文本列表（最多 20 项）')
    return list(dict.fromkeys(required(v, label, 300) for v in value))


class LearningStore:
    def __init__(self, path):
        self.tasks = TaskStore(path)
        self.path = self.tasks.path
        with self.tasks.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS learning_assets (
                    id TEXT PRIMARY KEY, family TEXT NOT NULL, version INTEGER NOT NULL,
                    project TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
                    trial_approved INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                    UNIQUE(family, version));
                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY, asset_id TEXT NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, note TEXT NOT NULL, evidence TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_recalls (
                    id TEXT PRIMARY KEY, initiative_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_bindings (
                    id TEXT PRIMARY KEY, initiative_id TEXT NOT NULL, plan_id TEXT NOT NULL UNIQUE,
                    task_id TEXT UNIQUE, payload TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_runs (
                    id INTEGER PRIMARY KEY, binding_id TEXT NOT NULL, phase TEXT NOT NULL,
                    payload TEXT NOT NULL, at REAL NOT NULL, UNIQUE(binding_id, phase));
                CREATE INDEX IF NOT EXISTS learning_project ON learning_assets(project,state);
            ''')

    @staticmethod
    def _event(db, asset_id, actor, action, note, evidence=None):
        db.execute('INSERT INTO learning_events(asset_id,actor,action,note,evidence,at) VALUES(?,?,?,?,?,?)',
                   (asset_id, actor, action, note, canonical(evidence or {}), time.time()))

    @staticmethod
    def _asset(db, asset_id):
        row = db.execute('SELECT * FROM learning_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise ValueError('经验或流程版本不存在')
        content = json.loads(row['payload'])
        if digest(content) != row['sha256']:
            raise ValueError('经验或流程内容校验失败')
        return {**content, 'state': row['state'], 'trial_approved': bool(row['trial_approved']), 'sha256': row['sha256']}

    def get(self, asset_id):
        with self.tasks.connect() as db:
            item = self._asset(db, asset_id)
            item['history'] = [dict(r) | {'evidence': json.loads(r['evidence'])} for r in db.execute(
                'SELECT * FROM learning_events WHERE asset_id=? ORDER BY id', (asset_id,))]
        return item

    def project(self, initiative_id):
        with self.tasks.connect() as db:
            row = db.execute('SELECT project_id FROM initiatives WHERE id=?', (initiative_id,)).fetchone()
        if not row or not row['project_id']:
            raise ValueError('事项没有项目归属')
        return row['project_id']

    def _task_ids(self, initiative_id):
        with self.tasks.connect() as db:
            row = db.execute('SELECT linked_task_id FROM initiatives WHERE id=?', (initiative_id,)).fetchone()
            has_workflows = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='initiative_workflows'").fetchone()
            flow = db.execute('SELECT payload FROM initiative_workflows WHERE id=?', (initiative_id,)).fetchone() if has_workflows else None
        data = json.loads(flow['payload']) if flow else {}
        ids = {data.get('active_task_id'), row['linked_task_id'] if row else None}
        ids.update(i.get('task_id') for i in data.get('iterations', []))
        for cycle in data.get('completed_cycles', []):
            ids.add(cycle.get('active_task_id'))
            ids.update(i.get('task_id') for i in cycle.get('iterations') or [])
        return ids - {None, ''}

    def _belongs(self, initiative_id, task_id):
        if task_id not in self._task_ids(initiative_id):
            raise ValueError('来源任务不属于指定事项')

    def source_options(self, initiative_id):
        """Eligible original tasks and named accepted failure feedback for this item."""
        task_ids = self._task_ids(initiative_id)
        if not task_ids:
            return {'tasks': [], 'feedback': []}
        with self.tasks.connect() as db:
            has_feedback = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone()
            feedback = [dict(row) for row in db.execute(
                "SELECT id,task_id,conclusion FROM feedback WHERE status='accepted' AND COALESCE(reviewed_by,'')<>'' "
                "AND task_id IN (" + ','.join('?' for _ in task_ids) + ') ORDER BY id', tuple(task_ids))] if has_feedback else []
        tasks, failures = [], set()
        for task_id in sorted(task_ids):
            try:
                task = self.tasks.get(task_id)
            except KeyError:
                continue
            success = task['status'] == 'completed' and task.get('review_decision') == 'approve' and bool(task.get('reviewed_by'))
            if success:
                try:
                    self.report(task, passing=True)
                except (ValueError, OSError):
                    success = False
            failed = task['status'] in {'rework', 'failed', 'dead_letter'}
            if failed and any(f['task_id'] == task_id for f in feedback):
                failures.add(task_id)
            if success or task_id in failures:
                tasks.append({'id': task_id, 'status': task['status'], 'eligible_success': success,
                              'label': task_id + ' · ' + task['status'] + ' · ' + task['request']})
        return {'tasks': tasks, 'feedback': [{'id': f['id'], 'task_id': f['task_id'],
            'label': f['id'] + ' · ' + f['conclusion']} for f in feedback if f['task_id'] in failures]}

    def report(self, task, *, passing=False):
        report = task.get('result') or {}
        if passing:
            rows = [r for r in report.get('results', []) if r.get('level') == 'blocking']
            if (report.get('summary', {}).get('decision') != 'pass' or
                    report.get('summary', {}).get('blocking_failed') != 0 or
                    not rows or any(r.get('passed') is not True for r in rows)):
                raise ValueError('必须有逐项通过的阻断 Eval')
        path, sha = report.get('report_path'), report.get('report_sha256')
        if not path or not sha:
            if passing or report:
                raise ValueError('缺少不可替换的任务报告')
            return None
        root = Path(self.path).resolve().parent
        file = Path(path)
        file = file.resolve() if file.is_absolute() else (root / file).resolve()
        if file.parent != (root / 'reports').resolve() or not file.is_file():
            raise ValueError('任务报告不在受控目录或已经丢失')
        if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
            raise ValueError('来源或验证报告已被替换')
        return {'path': str(file), 'sha256': sha}

    def source(self, initiative_id, task_id, evolution_id=''):
        self._belongs(initiative_id, task_id)
        task = self.tasks.get(task_id)
        accepted = task['status'] == 'completed' and task.get('review_decision') == 'approve' and task.get('reviewed_by')
        if not accepted:
            if not evolution_id:
                raise ValueError('来源需要已验收任务，或已接受失败反馈对应的 Evolution')
            from .evolution import EvolutionStore
            evo = EvolutionStore(self.path).get(evolution_id)
            if evo['source_task_id'] != task_id or evo['status'] in {'rejected', 'deferred'}:
                raise ValueError('Evolution 来源不一致或已拒绝')
        elif evolution_id:
            from .evolution import EvolutionStore
            if EvolutionStore(self.path).get(evolution_id)['source_task_id'] != task_id:
                raise ValueError('Evolution 来源不一致')
        report = self.report(task, passing=bool(accepted))
        if not accepted and not task.get('error') and not any(e.get('to_status') in {'rework', 'failed', 'dead_letter'} for e in task['events']):
            raise ValueError('失败经验缺少实际失败轨迹')
        evidence = {'task_id': task_id, 'initiative_id': initiative_id, 'project': self.project(initiative_id),
                    'evolution_id': evolution_id, 'report': report, 'result_sha256': digest(task.get('result')),
                    'events': task['events'], 'spec': task.get('spec'), 'error': task.get('error'),
                    'reviewed_by': task.get('reviewed_by'), 'review_note': task.get('review_note')}
        evidence['sha256'] = digest(evidence)
        return evidence

    def check_source(self, asset):
        source = dict(asset['source'])
        sha = source.pop('sha256')
        if digest(source) != sha:
            raise ValueError('来源快照校验失败')
        if self.project(source['initiative_id']) != asset['project']:
            raise ValueError('来源项目已变化')
        self._belongs(source['initiative_id'], source['task_id'])
        task = self.tasks.get(source['task_id'])
        if digest(task.get('result')) != source['result_sha256']:
            raise ValueError('来源任务报告内容已变化')
        original = source['events']
        if task['events'][:len(original)] != original:
            raise ValueError('原始轨迹已变化')
        self.report(task)

    @staticmethod
    def recipe(value):
        if not isinstance(value, dict):
            raise ValueError('流程定义必须是对象')
        parameters = strings(value.get('parameters', []), '参数名', empty=True)
        if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', p) for p in parameters):
            raise ValueError('参数名应为小写英文字母、数字、下划线')
        checks = value.get('preconditions')
        if not isinstance(checks, list) or not checks or len(checks) > 20:
            raise ValueError('流程至少需要一项可执行前置检查，最多 20 项')
        normalized = []
        for c in checks:
            if not isinstance(c, dict) or c.get('kind') not in {'file_exists', 'file_contains'}:
                raise ValueError('前置检查支持 file_exists 或 file_contains')
            entry = {'kind': c['kind'], 'path': required(c.get('path'), '检查路径', 300)}
            if c['kind'] == 'file_contains':
                entry['text'] = required(c.get('text'), '应包含内容', 1000)
            normalized.append(entry)
        steps = value.get('steps')
        phases = ['precheck', 'implement', 'eval', 'review']
        roles = ['harness', 'codex', 'harness', 'human']
        if not isinstance(steps, list) or len(steps) != 4:
            raise ValueError('首版流程必须包含前置检查、实现、Eval、人审四个阶段')
        clean = []
        for i, step in enumerate(steps):
            if (not isinstance(step, dict) or step.get('phase') != phases[i] or step.get('role') != roles[i]
                    or step.get('depends_on') != ([] if i == 0 else [phases[i - 1]])):
                raise ValueError('流程步骤、职责或依赖不符合受控交付顺序')
            clean.append({'phase': phases[i], 'role': roles[i], 'depends_on': step['depends_on'],
                          'instruction': required(step.get('instruction'), '步骤说明', 1500)})
        if value.get('eval_entry') != 'project_blocking' or value.get('authorization') != 'confirmed_plan':
            raise ValueError('流程必须使用已确认方案授权和既有项目阻断 Eval')
        return {'parameters': parameters, 'preconditions': normalized, 'steps': clean,
                'authorization': 'confirmed_plan', 'eval_entry': 'project_blocking',
                'outputs': strings(value.get('outputs'), '输出证据'),
                'stop': required(value.get('stop'), '停止条件'), 'rollback': required(value.get('rollback'), '回退方式')}

    def create(self, initiative_id, actor, fields):
        actor = human(actor)
        if not isinstance(fields, dict) or fields.get('kind') not in {'memory', 'workflow'}:
            raise ValueError('请选择记忆或流程候选')
        project = self.project(initiative_id)
        if fields.get('feedback_id') and not fields.get('evolution_id'):
            from .evolution import EvolutionStore
            evolutions = EvolutionStore(self.path)
            existing = next((e for e in evolutions.list() if e['feedback_id'] == fields['feedback_id']), None)
            evo = existing or evolutions.create(fields['feedback_id'], required(fields.get('title'), '失败签名', 200),
                                               'workbench_control', actor=actor)
            fields = {**fields, 'evolution_id': evo['id']}
        source = self.source(initiative_id, required(fields.get('task_id'), '来源任务'), fields.get('evolution_id', ''))
        previous = fields.get('supersedes', '')
        old = self.get(previous) if previous else None
        if old and (old['project'] != project or old['kind'] != fields['kind']):
            raise ValueError('替代版本必须属于同一项目和类型')
        asset_id = 'LEARN-' + uuid.uuid4().hex[:16]
        payload = {'id': asset_id, 'family': old['family'] if old else asset_id,
                   'project': project, 'kind': fields['kind'], 'supersedes': previous,
                   'title': required(fields.get('title'), '标题', 200),
                   'content': required(fields.get('content'), '提炼结论'),
                   'applies': strings(fields.get('applies'), '适用关键词'),
                   'excludes': strings(fields.get('excludes', []), '排除关键词', empty=True),
                   'boundary': required(fields.get('boundary'), '适用与不适用边界'),
                   'conflict_key': required(fields.get('conflict_key', fields.get('title')), '冲突主题', 200),
                   'source': source, 'created_by': actor, 'created_at': time.time(),
                   'recipe': self.recipe(fields.get('recipe')) if fields['kind'] == 'workflow' else None}
        with self.tasks.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            payload['version'] = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM learning_assets WHERE family=?', (payload['family'],)).fetchone()[0]
            db.execute('INSERT INTO learning_assets(id,family,version,project,kind,state,payload,sha256) VALUES(?,?,?,?,?,?,?,?)',
                       (asset_id, payload['family'], payload['version'], project, payload['kind'], 'candidate', canonical(payload), digest(payload)))
            self._event(db, asset_id, actor, 'candidate', '从真实任务轨迹提炼候选', {'source_sha256': source['sha256']})
        return self.get(asset_id)

    def govern(self, initiative_id, asset_id, actor, decision, note):
        actor, note = human(actor), required(note, '审核理由')
        asset = self.get(asset_id)
        if asset['project'] != self.project(initiative_id):
            raise ValueError('不能跨项目治理经验')
        if decision not in {'approve', 'publish', 'revoke'}:
            raise ValueError('审核决定须为 approve、publish 或 revoke')
        if decision != 'revoke':
            self.check_source(asset)
            if actor == asset['created_by']:
                raise ValueError('请由非提炼者独立审核候选')
            if asset['source'].get('evolution_id'):
                from .evolution import EvolutionStore
                store = EvolutionStore(self.path)
                evo = store.get(asset['source']['evolution_id'])
                if evo['status'] == 'proposed':
                    evo = store.review(evo['id'], actor, 'approve', note)
                if evo['status'] not in {'approved', 'asset_changed', 'verified'}:
                    raise ValueError('关联 Evolution 尚未批准')
                ref = 'learning/' + asset_id
                if evo['status'] != 'verified' and not any(a['path'] == ref for a in evo['asset_changes']):
                    store.record_assets(evo['id'], [{'type': 'skill' if asset['kind'] == 'workflow' else 'rule',
                                                    'path': ref, 'reason': note}], actor)
        with self.tasks.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._asset(db, asset_id)
            if decision == 'revoke':
                if current['state'] in {'revoked', 'superseded'}:
                    raise ValueError('该版本已停用')
                db.execute("UPDATE learning_assets SET state='revoked' WHERE id=?", (asset_id,))
            else:
                if current['state'] != 'candidate':
                    raise ValueError('只能审核候选版本')
                if decision == 'approve' and current['kind'] == 'workflow':
                    db.execute('UPDATE learning_assets SET trial_approved=1 WHERE id=?', (asset_id,))
                else:
                    if current['kind'] == 'workflow':
                        passing = []
                        for row in db.execute("SELECT b.payload,r.payload AS outcome FROM learning_bindings b JOIN learning_runs r ON r.binding_id=b.id AND r.phase='outcome'"):
                            binding, outcome = json.loads(row['payload']), json.loads(row['outcome'])
                            if outcome.get('passed') and any(s['id'] == asset_id for s in binding['assets']):
                                passing.append(outcome)
                        if not current['trial_approved'] or not passing:
                            raise ValueError('流程发布前必须在独立事项显式试用并完成隔离 Eval 和人审')
                        # Files may have changed since the independent trial was accepted.
                        for outcome in passing:
                            self.report(self.tasks.get(outcome['task_id']), passing=True)
                    db.execute("UPDATE learning_assets SET state='active' WHERE id=?", (asset_id,))
                    # Publishing a family version retires every older default version atomically.
                    for old in db.execute("SELECT id FROM learning_assets WHERE family=? AND id<>? AND state='active'", (current['family'], asset_id)).fetchall():
                        db.execute("UPDATE learning_assets SET state='superseded' WHERE id=?", (old['id'],))
                        self._event(db, old['id'], actor, 'superseded', note, {'replacement': asset_id})
            self._event(db, asset_id, actor, decision, note)
        return self.get(asset_id)

    def recall(self, initiative_id, query, *, trials=False, budget=12000):
        project = self.project(initiative_id)
        query = required(query, '召回问题', 30000).lower()
        with self.tasks.connect() as db:
            rows = db.execute("SELECT id FROM learning_assets WHERE project=? AND (state='active' OR (state='candidate' AND trial_approved=1)) ORDER BY version DESC,id", (project,)).fetchall()
        matches, excluded, used = [], [], 0
        for row in rows:
            a = self.get(row['id'])
            reason = ''
            if a['source']['initiative_id'] == initiative_id:
                reason = '同一来源事项，不能作为独立复用'
            elif a['state'] != 'active' and not trials:
                reason = '候选流程尚未发布，需显式选择试用召回'
            elif any(t.lower() in query for t in a['excludes']):
                reason = '命中不适用条件'
            tags = [t for t in a['applies'] if t.lower() in query]
            if not reason and not tags:
                reason = '未命中适用关键词'
            if not reason:
                try:
                    self.check_source(a)
                except (ValueError, OSError, KeyError) as error:
                    reason = str(error)
            # Limit model context; source trajectories remain in the evidence store.
            summary = {k: a[k] for k in ('id', 'version', 'kind', 'title', 'content', 'boundary', 'conflict_key', 'state', 'sha256')}
            summary['source'] = {k: a['source'][k] for k in ('task_id', 'initiative_id', 'sha256')}
            summary['reason'] = '匹配适用关键词：' + '、'.join(tags)
            size = len(canonical(summary))
            if not reason and used + size > budget:
                reason = '超过本轮上下文预算'
            if reason:
                excluded.append({'id': a['id'], 'reason': reason})
            else:
                matches.append(summary)
                used += size
        conflicts = []
        for key in sorted({m['conflict_key'] for m in matches}):
            group = [m['id'] for m in matches if m['conflict_key'] == key]
            if len(group) > 1:
                conflicts.append({'topic': key, 'ids': group, 'reason': '同主题多个结论，请逐项判断，不自动合并'})
        packet = {'id': 'RECALL-' + uuid.uuid4().hex[:16], 'initiative_id': initiative_id, 'project': project,
                  'query': query, 'matches': matches, 'excluded': excluded, 'conflicts': conflicts,
                  'trials': trials, 'budget_chars': budget, 'used_chars': used, 'at': time.time()}
        with self.tasks.connect() as db:
            db.execute('INSERT INTO learning_recalls VALUES(?,?,?)', (packet['id'], initiative_id, canonical(packet)))
        return packet

    def decide(self, initiative_id, recall_id, choices, actor):
        actor = human(actor)
        with self.tasks.connect() as db:
            row = db.execute('SELECT payload FROM learning_recalls WHERE id=? AND initiative_id=?', (recall_id, initiative_id)).fetchone()
        if not row:
            raise ValueError('召回记录不属于本事项')
        packet = json.loads(row['payload'])
        if not isinstance(choices, list) or len(choices) != len(packet['matches']):
            raise ValueError('请逐项记录采用或不采用及理由')
        indexed = {c.get('id'): c for c in choices if isinstance(c, dict)}
        if set(indexed) != {m['id'] for m in packet['matches']}:
            raise ValueError('采用决定必须与本轮召回版本逐项对应')
        result = []
        workflows = 0
        for match in packet['matches']:
            choice = indexed[match['id']]
            if type(choice.get('adopt')) is not bool:
                raise ValueError('请明确采用或不采用')
            if choice['adopt']:
                asset = self.get(match['id'])
                self._eligible(asset, initiative_id)
                if asset['sha256'] != match['sha256']:
                    raise ValueError('召回版本发生变化')
                workflows += asset['kind'] == 'workflow'
            result.append({'id': match['id'], 'adopt': choice['adopt'], 'reason': required(choice.get('reason'), '采用或不采用理由'),
                           'parameters': choice.get('parameters', {}), 'actor': actor})
        if workflows > 1:
            raise ValueError('一次交付只能绑定一个受控流程')
        return {'recall_id': recall_id, 'choices': result, 'actor': actor, 'at': time.time()}

    def _eligible(self, asset, initiative_id):
        if asset['project'] != self.project(initiative_id) or asset['source']['initiative_id'] == initiative_id:
            raise ValueError('禁止跨项目采用或把源事项算作独立复用')
        if asset['state'] != 'active' and not (asset['kind'] == 'workflow' and asset['state'] == 'candidate' and asset['trial_approved']):
            raise ValueError('经验已撤回、被替代或未经审核')
        self.check_source(asset)

    @staticmethod
    def preconditions(asset, parameters, root):
        recipe = asset['recipe']
        if not isinstance(parameters, dict) or set(parameters) != set(recipe['parameters']):
            raise ValueError('流程参数必须与定义完全一致')
        parameters = {k: required(v, '参数 ' + k, 300) for k, v in parameters.items()}
        def expand(text):
            for key, value in parameters.items():
                text = text.replace('${' + key + '}', value)
            if '${' in text:
                raise ValueError('流程引用未定义参数')
            return text
        root = Path(root).resolve()
        checks = []
        for check in recipe['preconditions']:
            path = expand(check['path'])
            file = (root / path).resolve()
            if Path(path).is_absolute() or '\\' in path or not file.is_relative_to(root) or file == root or any(p in {'.git', '.env'} for p in Path(path).parts):
                raise ValueError('流程检查路径越过项目边界')
            if not file.is_file() or file.stat().st_size > 2_000_000:
                raise ValueError('流程前置检查失败：文件不存在或过大：' + path)
            raw = file.read_bytes()
            if check['kind'] == 'file_contains' and expand(check['text']) not in raw.decode('utf-8', errors='replace'):
                raise ValueError('流程前置检查失败：内容不满足：' + path)
            checks.append({'path': path, 'kind': check['kind'], 'sha256': hashlib.sha256(raw).hexdigest(), 'passed': True})
        return {'checks': checks, 'steps': [{**s, 'instruction': expand(s['instruction'])} for s in recipe['steps']]}

    def bind(self, initiative_id, plan_id, decision, root, actor):
        actor = human(actor)
        if not decision:
            return None
        checked = self.decide(initiative_id, decision['recall_id'], decision['choices'], decision['actor'])
        selected = []
        for c in checked['choices']:
            if c['adopt']:
                asset = self.get(c['id'])
                selected.append({'id': asset['id'], 'sha256': asset['sha256'], 'snapshot': asset,
                                 'parameters': c['parameters'], 'reason': c['reason'],
                                 'prepared': self.preconditions(asset, c['parameters'], root) if asset['recipe'] else None})
        payload = {'id': 'BIND-' + uuid.uuid4().hex[:16], 'initiative_id': initiative_id, 'plan_id': plan_id,
                   'project': self.project(initiative_id), 'decision': checked, 'assets': selected,
                   'actor': actor, 'at': time.time()}
        with self.tasks.connect() as db:
            db.execute('INSERT INTO learning_bindings(id,initiative_id,plan_id,payload,sha256) VALUES(?,?,?,?,?)',
                       (payload['id'], initiative_id, plan_id, canonical(payload), digest(payload)))
        return payload | {'sha256': digest(payload)}

    def binding(self, binding_id):
        with self.tasks.connect() as db:
            row = db.execute('SELECT * FROM learning_bindings WHERE id=?', (binding_id,)).fetchone()
        if not row:
            raise ValueError('采用快照不存在')
        payload = json.loads(row['payload'])
        if digest(payload) != row['sha256']:
            raise ValueError('采用快照被修改')
        return payload | {'sha256': row['sha256'], 'task_id': row['task_id']}

    def validate_binding(self, binding_id, root):
        binding = self.binding(binding_id)
        for entry in binding['assets']:
            asset = self.get(entry['id'])
            self._eligible(asset, binding['initiative_id'])
            if asset['sha256'] != entry['sha256']:
                raise ValueError('已采用版本内容发生变化')
            if asset['recipe']:
                if self.preconditions(asset, entry['parameters'], root) != entry['prepared']:
                    raise ValueError('流程前置检查依据已变化，请重新确认方案')
        return binding

    def attach(self, binding_id, task_id):
        with self.tasks.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task_id FROM learning_bindings WHERE id=?', (binding_id,)).fetchone()
            if not row or (row['task_id'] and row['task_id'] != task_id):
                raise ValueError('采用快照已绑定其他任务')
            db.execute('UPDATE learning_bindings SET task_id=? WHERE id=?', (task_id, binding_id))
        binding = self.binding(binding_id)
        self.tasks.append_event(task_id, '记忆与流程采用快照已绑定', actor=binding['actor'],
                                evidence={'binding_id': binding_id, 'sha256': binding['sha256'], 'assets': [a['id'] for a in binding['assets']]})

    def run_event(self, binding_id, phase, evidence):
        with self.tasks.connect() as db:
            db.execute('INSERT OR IGNORE INTO learning_runs(binding_id,phase,payload,at) VALUES(?,?,?,?)',
                       (binding_id, phase, canonical(evidence), time.time()))

    def check_acceptance(self, task_id):
        with self.tasks.connect() as db:
            row = db.execute('SELECT id FROM learning_bindings WHERE task_id=?', (task_id,)).fetchone()
            if not row:
                return
            phases = {r['phase']: json.loads(r['payload']) for r in db.execute('SELECT phase,payload FROM learning_runs WHERE binding_id=?', (row['id'],))}
        binding = self.binding(row['id'])
        for entry in binding['assets']:
            self._eligible(self.get(entry['id']), binding['initiative_id'])
        self.report(self.tasks.get(task_id), passing=True)
        if any(p not in phases or not phases[p].get('passed') for p in ('precheck', 'implement', 'eval')):
            raise ValueError('缺少实际流程执行与检查证据，不能认定复用通过')
        task = self.tasks.get(task_id)
        runner = (task.get('result') or {}).get('runner') or {}
        workspace = Path(phases['precheck']['workspace']).resolve()
        if (not workspace.is_relative_to(Path(self.path).resolve().parent / 'daily-delivery') or
                not runner.get('validated') or Path(runner.get('workspace', '')).resolve() != workspace):
            raise ValueError('复用验证必须来自此次隔离候选的实际 Eval')
        from .daily_delivery import manifest
        if manifest(workspace, Path(self.path).resolve().parent) != phases['eval'].get('candidate_manifest'):
            raise ValueError('流程执行后候选发生变化，请重新复验')

    def finish(self, task_id, *, note=''):
        with self.tasks.connect() as db:
            row = db.execute('SELECT id FROM learning_bindings WHERE task_id=?', (task_id,)).fetchone()
        if not row:
            return
        binding = self.binding(row['id'])
        with self.tasks.connect() as db:
            if db.execute("SELECT 1 FROM learning_runs WHERE binding_id=? AND phase='outcome'", (binding['id'],)).fetchone():
                return
        task = self.tasks.get(task_id)
        if task['status'] not in {'completed', 'rework', 'failed', 'dead_letter'}:
            return
        passed = task['status'] == 'completed'
        if passed:
            self.report(task, passing=True)
            with self.tasks.connect() as db:
                phases = {r['phase']: json.loads(r['payload']) for r in db.execute('SELECT phase,payload FROM learning_runs WHERE binding_id=?', (binding['id'],))}
            if any(p not in phases or not phases[p].get('passed') for p in ('precheck', 'implement', 'eval')):
                raise ValueError('缺少实际流程执行与检查证据，不能认定复用通过')
            if not task.get('reviewed_by') or task.get('review_decision') != 'approve':
                raise ValueError('复用验证缺少具名验收')
        try:
            report_evidence = self.report(task)
        except (ValueError, OSError) as error:
            if passed:
                raise
            report_evidence = {'error': str(error)}
        outcome = {'task_id': task_id, 'passed': passed, 'status': task['status'],
                   'reviewed_by': task.get('reviewed_by'), 'note': note or task.get('review_note') or task.get('error') or '任务未通过，保留失败轨迹',
                   'report': report_evidence, 'binding_sha256': binding['sha256']}
        self.run_event(binding['id'], 'review', {'passed': passed, 'reviewed_by': task.get('reviewed_by'), 'note': outcome['note']})
        self.run_event(binding['id'], 'outcome', outcome)
        if not passed:
            with self.tasks.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                for a in binding['assets']:
                    if a['snapshot']['kind'] == 'workflow':
                        db.execute("UPDATE learning_assets SET state='revoked' WHERE id=? AND state IN ('active','candidate')", (a['id'],))
                        self._event(db, a['id'], 'harness', 'reuse_failed', '复用失败，停用此流程版本；保留来源并提炼新版本', outcome)

    def view(self, initiative_id):
        project = self.project(initiative_id)
        with self.tasks.connect() as db:
            ids = [r['id'] for r in db.execute('SELECT id FROM learning_assets WHERE project=? ORDER BY rowid DESC', (project,))]
            bindings = [r['id'] for r in db.execute('SELECT id FROM learning_bindings WHERE initiative_id=? ORDER BY rowid', (initiative_id,))]
        assets = [self.get(i) for i in ids]
        history = []
        for b in bindings:
            binding = self.binding(b)
            with self.tasks.connect() as db:
                binding['runs'] = [dict(r) | {'payload': json.loads(r['payload'])} for r in db.execute('SELECT phase,payload,at FROM learning_runs WHERE binding_id=? ORDER BY id', (b,))]
            history.append(binding)
        outcomes = [r['payload'] for b in history for r in b['runs'] if r['phase'] == 'outcome']
        return {'assets': assets, 'bindings': history, 'metrics': {'scope': '本事项实际记录',
                'adopted_versions': sum(len(b['assets']) for b in history),
                'reuse_passed': sum(o['passed'] for o in outcomes), 'reuse_failed': sum(not o['passed'] for o in outcomes),
                'repeated_failure_reduction': '待测'}}
