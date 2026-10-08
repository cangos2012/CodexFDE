"""One acceptance gate for bound candidate evidence, including CLI acceptance."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .file_io import read_bytes


def eval_contract(runtime, task_id, configured_command):
    """Bind an Eval attempt to its existing task contract without creating state."""
    database = Path(runtime) / 'workbench.db'
    if not database.is_file():
        return {}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
            return {}
        row = db.execute('SELECT spec_path FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not row:
        return {}
    from .reference_paths import reference_mapping_scope, load_reference_mappings
    with reference_mapping_scope(runtime, load_reference_mappings(runtime)):
        return dict(task_id=task_id, spec_sha256=hashlib.sha256(read_bytes(row[0])).hexdigest(),
                    configuration_sha256=hashlib.sha256(json.dumps(configured_command, ensure_ascii=False, sort_keys=True).encode()).hexdigest())


def assert_current_evidence(task, runtime):
    from .reference_paths import reference_mapping_scope, load_reference_mappings
    with reference_mapping_scope(runtime, load_reference_mappings(runtime)):
        return _assert_current_evidence(task, runtime)


def _assert_current_evidence(task, runtime):
    report = task.get('result') or {}
    runner = report.get('runner') or {}
    projects = [ref.removeprefix('PROJECT:') for ref in task.get('business_refs', []) if ref.startswith('PROJECT:')]
    bound = bool(runner.get('candidate_sha256'))
    required = task.get('execution_mode') == 'codex' and (projects or str(task.get('requirement_id', '')).startswith('REQ-DAILY-'))
    if not bound and not required:
        return  # Historical verify-only/course evidence has its separate contracts.
    if not bound or runner.get('validated') is not True:
        raise ValueError('缺少本次候选的独立项目Eval绑定，不能接受')
    if report.get('summary', {}).get('decision') != 'pass' or runner.get('process_returncode') != 0:
        raise ValueError('项目Eval未通过，不能接受')
    if required and (not runner.get('process_path') or not runner.get('process_sha256')):
        raise ValueError('缺少本次Eval进程回执绑定')
    if required and projects and not runner.get('configured_command'):
        raise ValueError('缺少本次登记质量命令绑定')
    if required:
        expected = eval_contract(runtime, task['id'], runner.get('configured_command'))
        if not expected or any(runner.get(k) != v for k, v in expected.items()):
            raise ValueError('Eval所属任务、合同或配置绑定已变化')
    from .eval_harness import report_view
    workspace = runner.get('workspace')
    if not workspace or report_view(report, workspace, runtime)['freshness'] != 'current':
        raise ValueError('候选或Eval报告已变化，必须重新复验')
    if runner.get('process_path'):
        raw = read_bytes(runner['process_path'])
        if not runner.get('process_sha256') or hashlib.sha256(raw).hexdigest() != runner['process_sha256']:
            raise ValueError('Eval进程回执缺失或变化')
        receipt = json.loads(raw)
        if receipt.get('returncode') != 0:
            raise ValueError('Eval进程未通过')
        if required and (receipt.get('contract') != expected or receipt.get('candidate_sha256') != runner['candidate_sha256']):
            raise ValueError('Eval回执与本次合同或候选绑定不一致')
    for event in task.get('events', []):
        if event.get('detail') == '本次需求 Spec 已冻结':
            if hashlib.sha256(read_bytes(task['spec_path'])).hexdigest() != (event.get('evidence') or {}).get('sha256'):
                raise ValueError('冻结Spec已变化')
    configured = runner.get('configured_command')
    if configured and projects:
        database = Path(runtime) / 'workbench.db'
        if database.is_file():
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_projects'").fetchone():
                    row = db.execute('SELECT eval_command_json FROM harness_projects WHERE id=?', (projects[0],)).fetchone()
                    from .reference_paths import resolve_reference
                    relocate = lambda command: [str(resolve_reference(p, runtime)) if Path(p).is_absolute() else p for p in command]
                    if not row or relocate(json.loads(row[0])) != relocate(configured):
                        raise ValueError('项目质量配置已变化，请重新确认并复验')
