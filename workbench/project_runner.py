from __future__ import annotations

import json
import shutil
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
                from .reference_paths import resolve_reference
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                if receipt['project_id'] != project['id']:
                    raise ValueError('候选项目绑定不一致')
                workspace = resolve_reference(receipt['workspace'], self.runtime_dir)
                if workspace.is_symlink() or workspace.resolve() != (receipt_path.parent / 'workspace').resolve():
                    raise ValueError('候选工作区路径不匹配，禁止修改登记项目源码')
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
            from .project_delivery import CandidateProjectEval
            from .reference_paths import resolve_reference
            candidate_receipt = self.runtime_dir / 'candidates' / task['id'] / 'project.json'
            if candidate_receipt.is_file():
                receipt = json.loads(candidate_receipt.read_text(encoding='utf-8'))
                if receipt['project_id'] != project['id']:
                    raise ValueError('候选项目绑定不一致')
                workspace = resolve_reference(receipt['workspace'], self.runtime_dir)
                if workspace.is_symlink() or workspace.resolve() != (candidate_receipt.parent / 'workspace').resolve():
                    raise ValueError('候选工作区路径不匹配，禁止以其他源码替代项目 Eval')
                report = CandidateProjectEval(workspace, self.runtime_dir, task['id'], project['eval_command'], 'project')()
                report['project_runner'] = {'project_id': project['id'], 'root_path': project['root_path'],
                                            'workspace': str(workspace), 'returncode': report['runner']['process_returncode']}
                return report
            if task.get('execution_mode') == 'codex':
                raise RuntimeError('编码任务缺少隔离候选，不能用原项目 Eval 替代')
            workspace = Path(project['root_path'])
            report = CandidateProjectEval(workspace, self.runtime_dir, task['id'], project['eval_command'], 'project-verify')()
            report["project_runner"] = {
                "project_id": project["id"], "root_path": project["root_path"],
                "returncode": report['runner']['process_returncode'],
            }
            return report

        return run
