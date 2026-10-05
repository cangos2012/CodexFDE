"""Read-only preparation and evidence boundaries for course verification."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

from eval.harness import PROJECT_CASES
from .course_mainline import lesson_contract
from . import external_project


CASE_LABELS = {
    'inventory_export_is_stable': '库存导出的字段、排序与可用数量一致',
    'receiving_is_idempotent': '相同入库幂等键只生效一次',
    'stock_never_negative': '可用库存不为负，缺货不产生部分写入',
    'order_total_matches_lines': '订单金额与明细一致',
    'sales_credit_and_atomic_reservation': '销售订单缺货时整单回滚',
    'ci_evidence_envelope_is_honest': 'CI 报告与提交、运行身份一致',
    'cancellation_releases_reservation': '取消订单释放预占库存',
    'illegal_transition_is_blocked': '订单不能跳过前置状态',
    'purchase_request_preserves_reason': '采购申请保留数量、原因和身份',
    'write_sets_reject_conflict': '有写入冲突的任务不能并行',
    'purchase_requires_approval': '采购未经审批不能入库',
    'delivery_evidence_and_review_controls': '任务、报告与具名人审可追溯',
    'web_api_and_persistence_projection_agree': '工作台 API 与持久化状态一致',
    'no_committed_secrets': '源码中没有常见凭据特征',
    'raw_feedback_cannot_become_blocking': '原始反馈经过人审后才能采用',
    'backup_is_restorable': '备份可恢复并通过完整性检查',
}


class CourseVerificationNotReady(ValueError):
    def __init__(self, verification):
        self.verification = verification
        super().__init__(verification['message'])


def target_verification_key(lesson, target):
    checks = [{'name': name, 'label': CASE_LABELS.get(name, name),
               'target': 'FlowERP' if name in PROJECT_CASES else '工作台'}
              for name in lesson_contract(int(lesson)).eval_cases]
    return hashlib.sha256(json.dumps({'lesson': int(lesson), 'checks': checks, 'target': target},
                                    sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def prepare_verification(repository, projects, lesson, project_id=None, *, target=None,
                         injected_runner=False):
    """Inspect prerequisites without executing checks or creating task records.

    Registry lookup is deliberately limited to the calling service. A previously
    frozen target is rechecked by path rather than resolved against a new default.
    """
    if not 4 <= int(lesson) <= 16:
        raise ValueError('课程任务请选择 L04～L16')
    if project_id is not None and (not isinstance(project_id, str) or len(project_id) > 100):
        raise ValueError('复验项目编号无效')
    contract = lesson_contract(int(lesson))
    repository = Path(repository).resolve()
    checks = [{'name': name, 'label': CASE_LABELS.get(name, name),
               'target': 'FlowERP' if name in PROJECT_CASES else '工作台'}
              for name in contract.eval_cases]
    product_cases = [row['name'] for row in checks if row['target'] == 'FlowERP']
    external = [p for p in projects.list() if Path(p['root_path']).resolve() != repository]
    choices = [p for p in external if (Path(p['root_path']) / 'flowerp').is_dir()
               or 'flowerp' in p['name'].lower()]
    payload = {'lesson': int(lesson), 'title': contract.title, 'ready': True,
               'checks': checks, 'projects': [{k: p[k] for k in ('id', 'name', 'root_path')}
                                             for p in choices],
               'target': {'workbench_root': str(repository), 'project_id': None,
                          'product_root': None, 'root_path': None},
               'issues': [],
               'limitations': ['只运行上面列出的固定检查；备注不会增加验收用例。',
                               '通过后仍需核对个人成果、失败与修订记录，并由具名人员验收。']}
    if int(lesson) == 12:
        payload['limitations'].append('L12 的 Graph 状态、等待、打回与恢复轨迹，须按实践手册另行核验。')
    if contract.dynamic_eval_required:
        payload['limitations'].append('本讲的新需求与新增检查，须从已确认事项或课程执行方案验收。')

    def issue(code, message, action):
        payload['issues'].append({'code': code, 'message': message, 'action': action})

    if target:
        if Path(target.get('workbench_root') or '').resolve() != repository:
            issue('workbench_changed', '复验任务所属工作台源码目录已变化。', '核对迁移后的原任务来源，重新选择明确的复验对象。')
        payload['target'] = dict(target)
    elif product_cases and not injected_runner:
        selected = next((p for p in external if p['id'] == project_id), None) if project_id else None
        if project_id and selected is None:
            issue('project_missing', '所选项目不在当前工作台的项目登记中。', '回到首页“管理项目”登记 FlowERP，再重新选择。')
        elif not project_id:
            if len(choices) == 1:
                selected = choices[0]
            elif len(choices) > 1:
                issue('project_required', '当前工作台有多个 FlowERP 项目，请选择本次检查对象。', '在“FlowERP 检查项目”中选择学生本次使用的源码项目。')
            elif os.environ.get('FLOWERP_PROJECT_ROOT'):
                payload['target'].update(product_root=str(Path(os.environ['FLOWERP_PROJECT_ROOT']).resolve()))
            else:
                issue('project_missing', '当前工作台尚未登记独立 FlowERP 项目。', '回到首页“管理项目”添加已有 FlowERP 源码目录；按手册创建该项目的 .venv 并安装后再检查。')
        if selected:
            payload['target'].update(project_id=selected['id'], product_root=str(Path(selected['root_path']).resolve()))

    root_value = payload['target'].get('product_root')
    if product_cases and not injected_runner and root_value:
        root = Path(root_value).resolve()
        payload['target'].update(product_root=str(root), root_path=str(root))
        if root == repository or not (root / 'flowerp/server.py').is_file() or not (root / 'flowerp/__init__.py').is_file():
            issue('product_source_missing', '所选目录缺少独立 FlowERP 源码。', '在“管理项目”核对源码目录，恢复 flowerp 包后再检查。')
        try:
            external_project.python_for(root)
        except ValueError as error:
            issue('product_environment_missing', str(error), '在所选 FlowERP 目录按实践手册创建 .venv，执行 pip install -e .，然后刷新检查。')
        path = root / 'eval/erp_cases.py'
        if not path.is_file():
            path = root / 'eval/cases.py'
        try:
            module = ast.parse(path.read_text(encoding='utf-8-sig'))
            names = {node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for node in module.body:
                if isinstance(node, ast.ImportFrom):
                    names.update(alias.asname or alias.name for alias in node.names)
            missing = sorted(set(product_cases) - names)
            if missing:
                issue('product_checks_missing', 'FlowERP 缺少本讲检查：' + '、'.join(missing), '核对 FlowERP 版本与本讲材料，补齐对应 Eval 文件后再检查。')
        except (OSError, SyntaxError, UnicodeError) as error:
            issue('product_checks_unavailable', '无法读取 FlowERP 检查文件：' + str(error), '恢复检查文件并修复语法或编码，再刷新检查。')
    elif product_cases and not injected_runner and not payload['issues']:
        issue('project_missing', '原复验任务没有可读取的 FlowERP 对象。', '重新选择明确的项目后创建复验任务；原失败记录保留。')

    payload['ready'] = not payload['issues']
    payload['message'] = ('检查条件已具备。提交后运行列出的固定检查，并保留结果等待人审。'
                          if payload['ready'] else '；'.join(row['message'] + ' ' + row['action'] for row in payload['issues']))
    payload['verification_key'] = target_verification_key(lesson, payload['target'])
    return payload


def eval_diagnostics(result):
    rows = []
    for item in result.get('results', []):
        if not isinstance(item, dict) or item.get('passed'):
            continue
        error = item.get('error') or {}
        message = str(error.get('message') or item.get('evidence') or item.get('message') or '未提供具体失败原因，请查看原报告。')
        environmental = error.get('type') in {'ValueError', 'FileNotFoundError', 'ModuleNotFoundError', 'TimeoutExpired', 'OSError', 'ExternalProjectEnvironmentError'}
        rows.append({'name': item.get('name'), 'label': CASE_LABELS.get(item.get('name'), item.get('name')),
                     'message': message, 'kind': 'environment' if environmental else 'check',
                     'action': ('先核对本次项目目录、虚拟环境和检查文件，再在原任务重新复验。'
                                if environmental else '对照原始失败证据修复本次代码，再在原任务重新复验；复验按钮只检查，不会修改代码。')})
    return rows
