from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.schedule import Subtask, assert_parallel_safe


_STATES = {"planned", "running", "completed", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("SubAgent 清单必须是 JSON 对象")
    return value


class SubagentCoordinator:
    """Persist governed delegation facts; it does not impersonate a native agent runtime."""

    def __init__(self, runtime_dir: str | Path) -> None:
        self.root = Path(runtime_dir).resolve() / "subagents"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, plan_id: str) -> Path:
        if not plan_id.startswith("SUBAGENT-") or any(char in plan_id for char in "/\\"):
            raise ValueError("无效的 SubAgent 计划编号")
        return self.root / f"{plan_id}.json"

    def create(self, manifest_path: str | Path) -> dict:
        manifest = _read_json(Path(manifest_path))
        candidate = Path(str(manifest.get("candidate_path") or ""))
        if not candidate.is_absolute() or not candidate.is_dir():
            raise ValueError("candidate_path 必须是已存在的隔离候选绝对目录")
        input_version = str(manifest.get("input_version") or "").strip()
        if not input_version:
            raise ValueError("必须记录非空 input_version，冻结共同输入")
        task_id = str(manifest.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("必须关联工作台 task_id")
        raw_tasks = manifest.get("subtasks")
        if not isinstance(raw_tasks, list) or len(raw_tasks) < 2:
            raise ValueError("并行计划至少需要两个子任务")
        tasks: list[Subtask] = []
        contracts: list[dict] = []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise ValueError("每个子任务合同必须是对象")
            prompt = str(raw.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("每个子任务必须提供 prompt")
            item = Subtask(
                str(raw.get("name") or "").strip(),
                tuple(raw.get("write_set") or ()),
                tuple(raw.get("read_set") or ()),
                tuple(raw.get("resource_set") or ()),
                input_version,
            )
            tasks.append(item)
            contracts.append({
                "name": item.name,
                "prompt": prompt,
                "read_set": list(item.read_set),
                "write_set": list(item.write_set),
                "resource_set": list(item.resource_set),
                "input_version": input_version,
                "status": "planned",
                "started_at": None,
                "ended_at": None,
                "actor": None,
                "evidence": [],
            })
        decision = assert_parallel_safe(tasks)
        plan_id = f"SUBAGENT-{uuid.uuid4().hex[:12].upper()}"
        plan = {
            "schema_version": "1.0",
            "id": plan_id,
            "task_id": task_id,
            "candidate_path": str(candidate.resolve()),
            "input_version": input_version,
            "status": "planned",
            "native_execution": False,
            "boundary": "工作台保存授权与活动证据；原生 SubAgent 必须由可用客户端实际启动。",
            "parallel_decision": decision,
            "subtasks": contracts,
            "events": [{"at": _now(), "kind": "plan/created", "actor": "workbench"}],
        }
        self._path(plan_id).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan

    def get(self, plan_id: str) -> dict:
        path = self._path(plan_id)
        if not path.is_file():
            raise KeyError(plan_id)
        return _read_json(path)

    def record(self, plan_id: str, name: str, status: str, actor: str, evidence: tuple[str, ...] = ()) -> dict:
        if status not in _STATES - {"planned"}:
            raise ValueError("活动状态必须是 running、completed 或 failed")
        plan = self.get(plan_id)
        subtask = next((item for item in plan["subtasks"] if item["name"] == name), None)
        if subtask is None:
            raise ValueError("子任务不属于该计划")
        previous = subtask["status"]
        allowed = {
            "planned": {"running", "failed"},
            "running": {"completed", "failed"},
            "completed": set(),
            "failed": set(),
        }
        if status not in allowed[previous]:
            raise ValueError(f"非法子任务状态迁移：{previous} -> {status}")
        evidence_paths = []
        for value in evidence:
            path = Path(value).resolve()
            if not path.exists():
                raise ValueError(f"证据不存在：{path}")
            evidence_paths.append(str(path))
        now = _now()
        subtask["status"] = status
        subtask["actor"] = actor.strip() or "unknown"
        if status == "running":
            subtask["started_at"] = now
        else:
            subtask["ended_at"] = now
        subtask["evidence"].extend(value for value in evidence_paths if value not in subtask["evidence"])
        plan["status"] = "running" if any(item["status"] == "running" for item in plan["subtasks"]) else plan["status"]
        plan["events"].append({
            "at": now, "kind": "subtask/status", "actor": subtask["actor"],
            "subtask": name, "from": previous, "to": status, "evidence": evidence_paths,
        })
        self._path(plan_id).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan

    def finalize(self, plan_id: str, actor: str) -> dict:
        plan = self.get(plan_id)
        if any(item["status"] != "completed" for item in plan["subtasks"]):
            raise ValueError("所有子任务完成后才能进入主 Agent 串行整合")
        if any(not item["evidence"] for item in plan["subtasks"]):
            raise ValueError("每个子任务必须保存可打开的原始证据")
        intervals = [
            (datetime.fromisoformat(item["started_at"]), datetime.fromisoformat(item["ended_at"]))
            for item in plan["subtasks"]
        ]
        overlaps = any(
            max(left[0], right[0]) < min(left[1], right[1])
            for index, left in enumerate(intervals)
            for right in intervals[index + 1:]
        )
        if not overlaps:
            raise ValueError("活动时间没有重叠，不能声称发生真实并行")
        plan["status"] = "ready_for_serial_integration"
        plan["events"].append({"at": _now(), "kind": "plan/finalized", "actor": actor, "overlap_proved": True})
        self._path(plan_id).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan
