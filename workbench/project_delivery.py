"""Project source snapshots and independent Eval in the candidate directory."""
import json
import hashlib
from pathlib import Path
import secrets
import subprocess
import time

from .execution import CodexExecutionRunner, _is_sensitive_path
from .file_io import read_bytes, read_text


def project_source_paths(root, runtime):
    from .execution_control import checkpoint
    from .file_io import atomic_write_text
    checkpoint()
    command = ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard']
    folder = Path(runtime) / 'git-processes' / secrets.token_hex(12)
    folder.mkdir(parents=True, exist_ok=False)
    runner = CodexExecutionRunner(root, folder)
    result = None
    error = None
    try:
        result = runner._run_codex_streaming(command, '', 120, lambda line: None,
                                             time.monotonic(), binary_stdout=True)
        (folder / 'stdout.bin').write_bytes(result.stdout)
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
        checkpoint()
    except BaseException as failure:
        error = failure
        raise
    finally:
        receipt = {'command': command, 'cwd': str(Path(root).resolve()),
                   'returncode': result.returncode if result else None,
                   'stdout_path': str(folder / 'stdout.bin'),
                   'stdout_sha256': hashlib.sha256(result.stdout).hexdigest() if result else None,
                   'stderr': result.stderr if result else '', 'success': result is not None and error is None,
                   'error': str(error) if error else ''}
        try:
            atomic_write_text(folder / 'process.json', json.dumps(receipt, ensure_ascii=False))
        except Exception as persistence_error:
            if error is None: raise
            error.add_note('源码清单回执保存失败：' + str(persistence_error))
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
        from .evidence_gate import eval_contract
        contract = eval_contract(self.runtime, self.task_id, self.command)
        folder = self.runtime / 'project-reports' / self.task_id / secrets.token_hex(12)
        folder.mkdir(parents=True)
        report_path = folder / 'report.json'
        command = [p.replace('{report_path}', str(report_path)).replace('{workspace}', str(self.workspace))
                   for p in self.command]
        from .execution import CodexExecutionRunner
        import time
        runner = CodexExecutionRunner(self.workspace, self.runtime)
        try:
            result = runner._run_codex_streaming(command, '', self.timeout, lambda line: None, time.monotonic())
        except BaseException as error:
            # The stream did not return a process result; a cleanup/startup fault
            # cannot become successful Eval evidence or a fabricated exit code.
            receipt = {'command': command, 'cwd': str(self.workspace),
                'status': 'failed', 'success': False, 'returncode': None,
                'process_result_available': False, 'exception_type': type(error).__name__,
                'error': str(error), 'notes': list(getattr(error, '__notes__', [])),
                'contract': contract, 'candidate_sha256': fingerprint(before)}
            try:
                from .file_io import atomic_write_text
                atomic_write_text(folder / 'process.json', json.dumps(receipt, ensure_ascii=False))
            except Exception as receipt_error:
                message = '失败项目 Eval 进程回执保存失败：' + str(receipt_error)
                if hasattr(error, 'add_note'):
                    error.add_note(message)
                else:
                    import logging
                    logging.getLogger(__name__).error('%s；原错误：%s', message, error)
            raise
        (folder / 'process.json').write_text(json.dumps({'command': command, 'cwd': str(self.workspace),
            'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
            'contract': contract, 'candidate_sha256': fingerprint(before)}, ensure_ascii=False), encoding='utf-8')
        checkpoint()
        if result.returncode in {124, 127, 130}:
            reason = {124: '项目 Eval 超时', 127: '项目 Eval 命令无法启动', 130: '项目 Eval 已取消'}[result.returncode]
            raise RuntimeError(reason + '，未完成验证；进程记录：' + str(folder / 'process.json'))
        report = json.loads(read_text(report_path) if report_path.exists() else result.stdout)
        # Preserve the exact received report even when validation rejects it.
        (folder / 'raw-report.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        validate_project_report(report, result.returncode)
        if before != manifest(self.workspace, self.runtime):
            raise RuntimeError('项目 Eval 执行期间候选源码变化，结果不可用于验收')
        report['runner'] = {'workspace': str(self.workspace), 'process_returncode': result.returncode,
                            'validated': True, 'label': self.label, 'report_path': str(report_path),
                            'candidate_sha256': fingerprint(before), 'command': command,
                            'process_path': str(folder / 'process.json'),
                            'process_sha256': hashlib.sha256((folder / 'process.json').read_bytes()).hexdigest(),
                            'configured_command': list(self.command), **contract}
        serialized = json.dumps(report, ensure_ascii=False)
        report_path.write_text(serialized, encoding='utf-8')
        persisted = read_bytes(report_path)
        if persisted != serialized.encode('utf-8'):
            raise RuntimeError('项目 Eval 报告写入后变化，结果不可用于验收')
        report['report_sha256'] = hashlib.sha256(persisted).hexdigest()
        return report
