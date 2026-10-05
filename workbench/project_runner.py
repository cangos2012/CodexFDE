from __future__ import annotations

import json
import os
import shutil
import subprocess
import secrets
import hashlib
from pathlib import Path

from .execution import CodexExecutionRunner, CodexLineCallback
from .codex_command import resolve_codex_command


def task_project_id(task: dict) -> str:
    reference = next(
        (item for item in task.get("business_refs", []) if str(item).startswith("PROJECT:")), "",
    )
    project_id = reference.partition(":")[2]
    if not project_id:
        raise ValueError("Harness 任务缺少 PROJECT 项目引用")
    return project_id


class ProjectExecutionRunner:
    def __init__(self, projects, runtime_dir: str | Path) -> None:
        self.projects = projects
        self.runtime_dir = Path(runtime_dir).resolve()

    def __call__(self, task: dict, *, on_codex_line: CodexLineCallback | None = None) -> dict:
        project = self.projects.get(task_project_id(task))
        workspace = Path(project['root_path'])
        if task.get('execution_mode') == 'codex':
            receipt_path = self.runtime_dir / 'candidates' / task['id'] / 'project.json'
            if receipt_path.is_file():
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                if receipt['project_id'] != project['id']:
                    raise ValueError('候选项目绑定不一致')
                workspace = Path(receipt['workspace'])
            else:
                from .daily_delivery import manifest
                from .delivery_runtime import DeliveryRuntime
                baseline = manifest(workspace, self.runtime_dir)
                candidate = receipt_path.parent / 'workspace'
                DeliveryRuntime._snapshot(workspace, candidate, baseline)
                receipt_path.write_text(json.dumps({'project_id': project['id'], 'source_root': str(workspace),
                    'workspace': str(candidate), 'source_manifest': baseline}, ensure_ascii=False), encoding='utf-8')
                workspace = candidate
        return CodexExecutionRunner(workspace, self.runtime_dir)(task, on_codex_line=on_codex_line)

    def capabilities(self) -> dict:
        command = resolve_codex_command()
        resolved = shutil.which(command)
        return {
            "codex_available": bool(resolved),
            "codex_command": resolved or command,
            "sandbox": "project-write-scope",
            "reason": "ready" if resolved else "找不到 Codex CLI",
        }


class ProjectEvalRunner:
    """Resolve and run the registered project's JSON-producing Eval command."""

    def __init__(self, projects, runtime_dir: str | Path) -> None:
        self.projects = projects
        self.runtime_dir = Path(runtime_dir).resolve()

    def for_task(self, task: dict):
        project = self.projects.get(task_project_id(task))

        def run(_suite: str = "blocking", write_report: bool = True) -> dict:
            from .daily_delivery import manifest
            from .eval_harness import fingerprint
            from .project_delivery import CandidateProjectEval
            candidate_receipt = self.runtime_dir / 'candidates' / task['id'] / 'project.json'
            if candidate_receipt.is_file():
                receipt = json.loads(candidate_receipt.read_text(encoding='utf-8'))
                report = CandidateProjectEval(receipt['workspace'], self.runtime_dir, task['id'], project['eval_command'], 'project')()
                report['project_runner'] = {'project_id': project['id'], 'root_path': project['root_path'],
                                            'workspace': receipt['workspace'], 'returncode': report['runner']['process_returncode']}
                return report
            if task.get('execution_mode') == 'codex':
                raise RuntimeError('编码任务缺少隔离候选，不能用原项目 Eval 替代')
            workspace = Path(project['root_path'])
            before = manifest(workspace, self.runtime_dir)
            report_path = self.runtime_dir / "project-reports" / task['id'] / secrets.token_hex(12) / 'report.json'
            report_path.parent.mkdir(parents=True, exist_ok=True)
            command = [part.replace("{report_path}", str(report_path)).replace('{workspace}', str(workspace)) for part in project["eval_command"]]
            completed = subprocess.run(
                command, cwd=project["root_path"], text=True,
                capture_output=True, check=False, timeout=1800,
            )
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding="utf-8"))
            else:
                output = (completed.stdout or "").strip()
                try:
                    report = json.loads(output)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("项目 Eval 命令必须写入 {report_path} 或在 stdout 输出完整 JSON") from exc
            summary = report.get("summary", {})
            if summary.get("decision") not in {"pass", "block"}:
                raise RuntimeError("项目 Eval 报告缺少 pass/block 决策")
            if (completed.returncode == 0) != (summary['decision'] == 'pass'):
                raise RuntimeError('项目 Eval 退出码与报告结论不一致')
            if before != manifest(workspace, self.runtime_dir):
                raise RuntimeError('项目 Eval 期间源码变化，不能接受结果')
            process_path = report_path.parent / 'process.json'
            process_path.write_text(json.dumps({'command': command, 'cwd': str(workspace), 'returncode': completed.returncode,
                                               'stdout': completed.stdout, 'stderr': completed.stderr}, ensure_ascii=False), encoding='utf-8')
            report['runner'] = {'workspace': str(workspace), 'process_returncode': completed.returncode,
                'validated': True, 'candidate_sha256': fingerprint(before), 'command': command,
                'process_path': str(process_path), 'report_path': str(report_path),
                'configured_command': project['eval_command'],
                'process_sha256': hashlib.sha256(process_path.read_bytes()).hexdigest()}
            report["project_runner"] = {
                "project_id": project["id"], "root_path": project["root_path"],
                "returncode": completed.returncode,
            }
            payload = json.dumps(report, ensure_ascii=False).encode('utf-8')
            report_path.write_bytes(payload)
            report['report_sha256'] = hashlib.sha256(payload).hexdigest()
            return report

        return run
