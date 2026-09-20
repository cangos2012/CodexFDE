"""Project source snapshots and independent Eval in the candidate directory."""
import json
from pathlib import Path
import secrets
import subprocess

from .execution import _is_sensitive_path


def project_source_paths(root, runtime):
    result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            cwd=root, capture_output=True, check=True)
    paths = []
    names = set(result.stdout.decode('utf-8').split('\0')) - {''}
    if (root / 'AGENTS.md').is_file():
        names.add('AGENTS.md')
    for name in sorted(names):
        path = root / name
        if any(p in {'.venv', 'node_modules', '__pycache__', '.runtime', '.harness-runtime'} for p in Path(name).parts):
            continue
        if _is_sensitive_path(name) or (not root.is_relative_to(runtime) and path.resolve().is_relative_to(runtime)):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('项目源文件不可链接到其他位置：' + name)
        if path.is_file():
            paths.append(path)
    return paths


class CandidateProjectEval:
    def __init__(self, workspace, runtime, task_id, command, label, *, timeout=1800):
        self.workspace, self.runtime = Path(workspace), Path(runtime)
        self.task_id, self.command, self.label = task_id, command, label
        self.timeout = timeout

    def __call__(self, suite='blocking', write_report=True):
        from .execution_control import checkpoint
        from .daily_delivery import manifest
        from .eval_harness import fingerprint, validate_project_report
        import hashlib
        checkpoint()
        before = manifest(self.workspace, self.runtime)
        folder = self.runtime / 'project-reports' / self.task_id / secrets.token_hex(12)
        folder.mkdir(parents=True)
        report_path = folder / 'report.json'
        command = [p.replace('{report_path}', str(report_path)).replace('{workspace}', str(self.workspace))
                   for p in self.command]
        from .execution import CodexExecutionRunner
        import time
        runner = CodexExecutionRunner(self.workspace, self.runtime)
        result = runner._run_codex_streaming(command, '', self.timeout, lambda line: None, time.monotonic())
        (folder / 'process.json').write_text(json.dumps({'command': command, 'cwd': str(self.workspace),
            'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}, ensure_ascii=False), encoding='utf-8')
        checkpoint()
        if result.returncode in {124, 127, 130}:
            reason = {124: '项目 Eval 超时', 127: '项目 Eval 命令无法启动', 130: '项目 Eval 已取消'}[result.returncode]
            raise RuntimeError(reason + '，未完成验证；进程记录：' + str(folder / 'process.json'))
        report = json.loads(report_path.read_text(encoding='utf-8') if report_path.exists() else result.stdout)
        # Preserve the exact received report even when validation rejects it.
        (folder / 'raw-report.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        validate_project_report(report, result.returncode)
        if before != manifest(self.workspace, self.runtime):
            raise RuntimeError('项目 Eval 执行期间候选源码变化，结果不可用于验收')
        report['runner'] = {'workspace': str(self.workspace), 'process_returncode': result.returncode,
                            'validated': True, 'label': self.label, 'report_path': str(report_path),
                            'candidate_sha256': fingerprint(before), 'command': command,
                            'process_path': str(folder / 'process.json')}
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        report['report_sha256'] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        return report
