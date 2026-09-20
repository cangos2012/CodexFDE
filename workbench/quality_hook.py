"""Reviewable Stop adapters for a confirmed project candidate; never installs or trusts hooks."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare(runtime, workspace, project, task_id, item_id, actor):
    """Freeze the confirmed command, identity and runner in an append-only package."""
    root, runtime = Path(workspace).resolve(), Path(runtime).resolve()
    if not root.is_dir() or not (root / '.git').exists():
        raise ValueError('请先取得本事项的隔离候选')
    if not re.fullmatch(r'TASK-[A-Za-z0-9_-]+', task_id):
        raise ValueError('Hook 必须关联实际任务')
    if root == Path(project['root_path']).resolve():
        raise ValueError('请在隔离候选准备 Hook，不能使用项目正式源码目录')
    command = project.get('eval_command')
    if not isinstance(command, list) or not command or any(not isinstance(p, str) or not p for p in command):
        raise ValueError('本事项尚未确认项目质量检查命令')
    if not actor.strip():
        raise ValueError('请填写准备者姓名')
    folder = runtime / 'hook-packages' / secrets.token_hex(16)
    folder.mkdir(parents=True)
    binding = dict(schema='workbench.quality-hook/v1', workspace=str(root), runtime=str(runtime),
        project_id=project['id'], task_id=task_id, initiative_id=item_id, actor=actor,
        command=command, timeout=100, prepared_at=time.time())
    write_json(folder / 'binding.json', binding)
    # The customer repository does not need to install the Workbench package.
    # Use the explicitly reviewed controller interpreter and module, but execute
    # the customer's confirmed quality command in the candidate directory.
    source = str(Path(__file__).resolve().parents[1])
    handler = ('import sys\n'
        f'sys.path.insert(0, {source!r})\n'
        'from workbench.quality_hook import main\n'
        f'raise SystemExit(main({str(folder / "binding.json")!r}, {digest(folder / "binding.json")!r}))\n')
    (folder / 'quality_gate.py').write_text(handler, encoding='utf-8')
    installed = root / '.codex/hooks/quality_gate.py'
    python = str(Path(sys.executable).absolute())
    psquote = lambda value: "'" + value.replace("'", "''") + "'"
    # EncodedCommand avoids nested shell quoting of spaces and metacharacters.
    import base64
    script = f'& {psquote(python)} -X utf8 {psquote(str(installed))}; exit $LASTEXITCODE'
    windows = 'powershell -NoProfile -EncodedCommand ' + base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    entry = {'type': 'command', 'command': shlex.join([python, '-X', 'utf8', str(installed)]),
             'commandWindows': windows, 'timeout': 120, 'statusMessage': '运行本事项候选质量检查'}
    write_json(folder / 'hooks.json', {'description': '工作台准备的候选 Stop 检查；安装后须在 /hooks 审查与信任',
                                     'hooks': {'Stop': [{'hooks': [entry]}]}})
    return {'path': str(folder), 'workspace': str(root), 'task_id': task_id,
            'binding_sha256': digest(folder / 'binding.json'),
            'handler_sha256': digest(folder / 'quality_gate.py'),
            'config_sha256': digest(folder / 'hooks.json'), 'actor': actor, 'prepared_at': binding['prepared_at']}


def view(package, workspace, task_id):
    if not package:
        return {'status': 'not_prepared', 'trust': 'unknown', 'runs': []}
    result = dict(package, status='prepared', trust='unknown', runs=[])
    try:
        folder = Path(package['path'])
        for filename, key in [('binding.json', 'binding_sha256'), ('quality_gate.py', 'handler_sha256'), ('hooks.json', 'config_sha256')]:
            if digest(folder / filename) != package[key]:
                raise ValueError('待审文件发生变化，请重新准备')
        result['review_files'] = {name: (folder / name).read_text(encoding='utf-8')
                                 for name in ('binding.json', 'hooks.json', 'quality_gate.py')}
        if str(Path(workspace).resolve()) != package['workspace'] or task_id != package['task_id']:
            result['status'] = 'stale'
            return result
        root = Path(workspace)
        config = root / '.codex/hooks.json'
        handler = root / '.codex/hooks/quality_gate.py'
        if config.is_file() and handler.is_file():
            groups = json.loads(config.read_text(encoding='utf-8-sig')).get('hooks', {}).get('Stop', [])
            expected = json.loads((folder / 'hooks.json').read_text(encoding='utf-8'))['hooks']['Stop'][0]['hooks'][0]
            present = any(expected == hook for group in groups for hook in group.get('hooks', []))
            result['status'] = 'installed' if present and digest(handler) == package['handler_sha256'] else 'different'
        elif config.exists() or handler.exists():
            result['status'] = 'different'
        for path in sorted(folder.glob('run-*.json'), reverse=True)[:10]:
            run = json.loads(path.read_text(encoding='utf-8'))
            # Report freshness uses the same candidate/source check as manual Eval.
            if run.get('report'):
                from .eval_harness import report_view
                run['freshness'] = report_view(run['report'], workspace, json.loads((folder / 'binding.json').read_text(encoding='utf-8'))['runtime'])['freshness']
            result['runs'].append(run)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(status='unavailable', error=str(error))
    return result


def handle(binding, event, *, runner_factory=None):
    """Protocol result and evidence are distinct; reentry never grants a pass."""
    record = dict(at=time.time(), task_id=binding['task_id'], initiative_id=binding['initiative_id'],
                  workspace=binding['workspace'], evidence_kind='stop_input', host_event_verified=False)
    try:
        if not isinstance(event, dict) or event.get('hook_event_name') != 'Stop':
            raise ValueError('需要 Stop 事件对象')
        root = Path(binding['workspace']).resolve(strict=True)
        cwd = Path(event['cwd']).resolve(strict=True)
        if cwd != root and root not in cwd.parents:
            raise ValueError('事件目录不属于绑定候选')
        record['session_id'] = event.get('session_id')
        if type(event.get('stop_hook_active', False)) is not bool:
            raise ValueError('stop_hook_active 必须是布尔值')
        if event.get('stop_hook_active'):
            record['outcome'] = 'skipped'
            return {'continue': True, 'systemMessage': '重入跳过，本次未验证。结束前请显式复验同一候选。'}, record
        if runner_factory is None:
            from .project_delivery import CandidateProjectEval
            runner_factory = CandidateProjectEval
        report = runner_factory(root, binding['runtime'], binding['task_id'], binding['command'],
                                'stop-hook', timeout=binding['timeout'])()
        record.update(outcome=report['summary']['decision'], report=report)
        if record['outcome'] == 'pass':
            return {'continue': True, 'systemMessage': '绑定候选的所选质量检查通过，仍须人工验收。'}, record
        return {'decision': 'block', 'reason': '候选质量检查未通过，请修复后显式复验。'}, record
    except Exception as error:
        record.update(outcome='unverified', error=f'{type(error).__name__}: {error}')
        return {'decision': 'block', 'reason': '未完成验证：' + record['error']}, record


def main(binding_path, expected_hash):
    import contextlib
    try:
        if digest(binding_path) != expected_hash:
            raise ValueError('Hook 绑定已变化，请重新准备并审查')
        binding = json.loads(Path(binding_path).read_text(encoding='utf-8'))
        try:
            event = json.load(sys.stdin)
        except ValueError:
            event = None
        with contextlib.redirect_stdout(sys.stderr):
            response, record = handle(binding, event)
        folder = Path(binding_path).parent
        path = folder / f'run-{time.time_ns()}-{secrets.token_hex(4)}.json'
        record['response'] = response
        write_json(path, record)
    except Exception as error:
        response = {'decision': 'block', 'reason': f'Hook 未完成验证或记录失败：{type(error).__name__}: {error}'}
    print(json.dumps(response, ensure_ascii=False))
    return 0
