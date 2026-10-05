"""Human-owned project milestones projected from existing initiative evidence."""
import hashlib
import json
import re
from pathlib import Path


ACCEPTED = {'accepted', 'integrated', 'released', 'observed'}


class ProjectPlans:
    def __init__(self, projects, initiatives, workflow):
        self.projects, self.initiatives, self.workflow = projects, initiatives, workflow
        with projects.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS project_plans (project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')

    def get(self, project_id):
        self.projects.get(project_id)
        with self.projects.connect() as db:
            row = db.execute('SELECT revision,payload FROM project_plans WHERE project_id=?', (project_id,)).fetchone()
        result = json.loads(row['payload']) if row else {'objective': '', 'architecture_refs': [], 'milestones': []}
        result.update(project_id=project_id, revision=row['revision'] if row else 0)
        by_id = {m['id']: m for m in result['milestones']}
        for m in result['milestones']:
            m['blocked_by'] = [d for d in m['depends_on'] if by_id[d]['status'] != 'completed']
            m['initiative_states'] = []
            for item_id in m['initiative_ids']:
                with self.projects.connect() as db:
                    flow = db.execute('SELECT payload FROM initiative_workflows WHERE id=?', (item_id,)).fetchone()
                stage = json.loads(flow['payload']).get('stage', 'idle') if flow else 'idle'
                m['initiative_states'].append({'id': item_id, 'stage': stage})
                if m['status'] == 'completed' and stage not in ACCEPTED:
                    m['status'] = 'needs_revalidation'
                if m['status'] == 'completed' and flow:
                    state = json.loads(flow['payload'])
                    try:
                        from .evidence_gate import assert_current_evidence
                        assert_current_evidence(self.workflow.tasks.get(state['active_task_id']), self.workflow.runtime)
                    except (OSError, ValueError, KeyError, TypeError):
                        m['status'] = 'needs_revalidation'
        # Re-evaluate dependency state after a reopened predecessor was projected.
        for m in result['milestones']:
            m['blocked_by'] = [d for d in m['depends_on'] if by_id[d]['status'] != 'completed']
        result['blocked'] = any(m['blocked_by'] for m in result['milestones'])
        return result

    def save(self, project_id, fields, actor, expected_revision):
        actor = self.workflow.actor(actor)
        project = self.projects.get(project_id)
        objective = fields.get('objective', '')
        if not isinstance(objective, str) or len(objective) > 10000:
            raise ValueError('项目目标须为最多10000字符的文本')
        milestones = fields.get('milestones', [])
        refs = fields.get('architecture_refs', [])
        if not isinstance(milestones, list) or len(milestones) > 100 or not isinstance(refs, list) or len(refs) > 50:
            raise ValueError('里程碑和架构引用格式无效')
        clean, identifiers, linked = [], set(), set()
        for m in milestones:
            if not isinstance(m, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(m.get('id', ''))):
                raise ValueError('里程碑必须有唯一的字母数字编号')
            if m['id'] in identifiers:
                raise ValueError('里程碑编号重复')
            identifiers.add(m['id'])
            title, acceptance = m.get('title'), m.get('acceptance')
            if not isinstance(title, str) or not title.strip() or not isinstance(acceptance, str) or not acceptance.strip():
                raise ValueError('请填写里程碑标题与验收条件')
            deps, items = m.get('depends_on', []), m.get('initiative_ids', [])
            if not isinstance(deps, list) or not isinstance(items, list) or any(not isinstance(v, str) for v in deps + items):
                raise ValueError('依赖和关联事项必须为编号列表')
            if len(set(deps)) != len(deps) or len(set(items)) != len(items):
                raise ValueError('依赖和关联事项不可重复')
            for item_id in items:
                if self.initiatives.get(item_id)['project_id'] != project_id or item_id in linked:
                    raise ValueError('关联事项须属于该项目且只关联一个里程碑')
                linked.add(item_id)
            status = m.get('status', 'planned')
            if status not in {'planned', 'active', 'completed', 'needs_revalidation'}:
                raise ValueError('里程碑状态无效')
            evidence = m.get('evidence', '')
            if status == 'completed':
                if not items or not isinstance(evidence, str) or not evidence.strip():
                    raise ValueError('里程碑完成必须关联事项并保留具名验收依据')
                if any(self.workflow.get(i)['stage'] not in ACCEPTED for i in items):
                    raise ValueError('关联事项尚未接受，不能完成里程碑')
                from .evidence_gate import assert_current_evidence
                for item_id in items:
                    state = self.workflow.get(item_id)
                    assert_current_evidence(self.workflow.tasks.get(state['active_task_id']), self.workflow.runtime)
            clean.append(dict(id=m['id'], title=title.strip(), acceptance=acceptance.strip(),
                              depends_on=deps, initiative_ids=items, status=status, evidence=evidence,
                              reviewed_by=actor if status == 'completed' else None))
        edges = {m['id']: m['depends_on'] for m in clean}
        seen, active = set(), set()
        def visit(node):
            if node not in edges:
                raise ValueError('里程碑依赖不存在')
            if node in active:
                raise ValueError('里程碑依赖存在循环')
            if node in seen:
                return
            active.add(node)
            for dep in edges[node]:
                visit(dep)
            active.remove(node); seen.add(node)
        for node in edges:
            visit(node)
        by_id = {m['id']: m for m in clean}
        if any(m['status'] == 'completed' and any(by_id[d]['status'] != 'completed' for d in m['depends_on']) for m in clean):
            raise ValueError('前置里程碑未完成')
        root = Path(project['root_path']).resolve()
        clean_refs = []
        for ref in refs:
            name = ref.get('path') if isinstance(ref, dict) else ref
            if not isinstance(name, str) or not name:
                raise ValueError('架构基线须为项目内文件路径')
            path = root / name
            if Path(name).is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
                raise ValueError('架构基线文件不存在或越界')
            clean_refs.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        payload = dict(objective=objective, milestones=clean, architecture_refs=clean_refs, actor=actor)
        with self.projects.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM project_plans WHERE project_id=?', (project_id,)).fetchone()
            revision = row[0] if row else 0
            if expected_revision != revision:
                raise ValueError('项目计划版本已变化，请重新读取')
            db.execute('INSERT OR REPLACE INTO project_plans VALUES(?,?,?)',
                       (project_id, revision + 1, json.dumps(payload, ensure_ascii=False)))
        return self.get(project_id)

    def assert_ready(self, initiative_id):
        item = self.initiatives.get(initiative_id)
        plan = self.get(item['project_id'])
        for m in plan['milestones']:
            if initiative_id in m['initiative_ids'] and m['blocked_by']:
                raise ValueError('事项被前置里程碑阻断：' + ', '.join(m['blocked_by']))
        root = Path(self.projects.get(item['project_id'])['root_path'])
        for ref in plan['architecture_refs']:
            path = root / ref['path']
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
                raise ValueError('架构基线已变化，请重新核对项目计划')
