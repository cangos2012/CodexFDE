from __future__ import annotations

"""Durable workflow graph for workbench Tasks.

The graph owns fine-grained workflow state. ``tasks.status`` remains the coarse
list projection and is updated in the same SQLite transaction whenever a graph
transition crosses a Task boundary.
"""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .task_store import VALID_TRANSITIONS, TaskStore


CORE_NODES = (
    "queued", "spec_ready", "awaiting_execution_authorization", "executing",
    "evaluating", "awaiting_software_review", "post_review", "rework",
    "completed", "failed", "dead_letter", "stopped", "cancelled",
)
TERMINAL_NODES = {"completed", "failed", "dead_letter", "stopped", "cancelled", "business_rejected"}
CORE_EDGES = {
    "queued": {"spec_ready", "failed", "cancelled"},
    "spec_ready": {"awaiting_execution_authorization", "executing", "failed", "cancelled"},
    "awaiting_execution_authorization": {"executing", "cancelled"},
    "executing": {"evaluating", "rework", "failed", "dead_letter"},
    "evaluating": {"awaiting_software_review", "rework", "failed", "dead_letter"},
    "awaiting_software_review": {"post_review", "rework"},
    "post_review": {"completed", "awaiting_purchase_approval"},
    "rework": {"executing", "stopped", "failed", "dead_letter"},
    "awaiting_purchase_approval": {"receiving", "business_rejected"},
    "receiving": {"reconciling", "failed", "dead_letter"},
    "reconciling": {"completed", "failed"},
    "failed": {"rework", "dead_letter"},
    "dead_letter": {"rework"},
}
TASK_TO_NODE = {"review": "awaiting_software_review"}
NODE_TO_TASK = {
    "queued": "queued", "spec_ready": "spec_ready", "executing": "executing",
    "evaluating": "evaluating", "awaiting_software_review": "review",
    "post_review": "review", "awaiting_purchase_approval": "review",
    "receiving": "review", "reconciling": "review", "business_rejected": "rework",
    "rework": "rework", "completed": "completed", "failed": "failed",
    "dead_letter": "dead_letter", "stopped": "failed", "cancelled": "failed",
}
WAITING_NODES = {"awaiting_execution_authorization", "awaiting_software_review", "awaiting_purchase_approval"}


class WorkflowConflict(ValueError):
    pass


@dataclass(frozen=True)
class HandlerDefinition:
    name: str
    slot: str
    schema: dict
    read_only: bool
    side_effect: bool
    requires_human: bool
    roles: tuple[str, ...]
    timeout_seconds: int
    retry: str
    evidence_types: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "name": self.name, "slot": self.slot, "schema": self.schema,
            "read_only": self.read_only, "side_effect": self.side_effect,
            "requires_human": self.requires_human, "roles": list(self.roles),
            "timeout_seconds": self.timeout_seconds, "retry": self.retry,
            "evidence_types": list(self.evidence_types),
        }


HANDLERS = {
    "flowerp.purchase_approval": HandlerDefinition(
        "flowerp.purchase_approval", "after_software_review",
        {"required": ["purchase_ref"], "properties": {"purchase_ref": {"type": "string"},
         "on_approve": {"const": "flowerp.receive_purchase"}}},
        True, False, True, ("human:purchase_approver",), 300, "never",
        ("purchase_identity", "decision", "candidate_revision"),
    ),
    "flowerp.receive_purchase": HandlerDefinition(
        "flowerp.receive_purchase", "after_software_review",
        {"required": ["purchase_ref", "idempotency_key"]},
        False, True, False, ("system",), 300, "query-before-retry",
        ("inventory_before", "inventory_after", "receipt_id", "reconciliation"),
    ),
}


class WorkflowGraph:
    def __init__(self, tasks: TaskStore) -> None:
        self.tasks = tasks
        self.path = tasks.path
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_definitions(
              id TEXT NOT NULL, version INTEGER NOT NULL, core_version TEXT NOT NULL,
              config_json TEXT NOT NULL, config_sha256 TEXT NOT NULL, enabled INTEGER NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS workflow_instances(
              task_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, definition_version INTEGER NOT NULL,
              current_node TEXT NOT NULL, candidate_revision INTEGER NOT NULL DEFAULT 1,
              candidate_sha256 TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
              state TEXT NOT NULL DEFAULT 'active', lease_owner TEXT, lease_until REAL,
              migrated INTEGER NOT NULL DEFAULT 0, config_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS workflow_node_runs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, node TEXT NOT NULL,
              attempt INTEGER NOT NULL, input_sha256 TEXT NOT NULL, handler TEXT,
              handler_version TEXT NOT NULL DEFAULT '1', status TEXT NOT NULL,
              result_json TEXT, error TEXT, started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              ended_at TEXT, UNIQUE(task_id,node,attempt));
            CREATE TABLE IF NOT EXISTS workflow_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, from_node TEXT,
              to_node TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
              evidence_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS workflow_decisions(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, decision_type TEXT NOT NULL,
              actor TEXT NOT NULL, role TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
              candidate_revision INTEGER NOT NULL, candidate_sha256 TEXT NOT NULL,
              target_ref TEXT NOT NULL DEFAULT '', stale INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS workflow_effects(
              idempotency_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, handler TEXT NOT NULL,
              business_ref TEXT NOT NULL, request_sha256 TEXT NOT NULL, status TEXT NOT NULL,
              result_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS workflow_requests(
              idempotency_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
              fingerprint TEXT NOT NULL, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
            config = {"slots": ["after_spec", "before_execution", "after_execution", "after_eval", "after_software_review"],
                      "handlers": []}
            raw = json.dumps(config, ensure_ascii=False, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO workflow_definitions VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP)",
                       ("workbench.delivery", 1, "v1", raw, hashlib.sha256(raw.encode()).hexdigest()))
            columns = {item[1] for item in db.execute("PRAGMA table_info(workflow_instances)")}
            if "config_json" not in columns:
                db.execute("ALTER TABLE workflow_instances ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def handlers() -> list[dict]:
        return [item.as_dict() for item in HANDLERS.values()]

    def ensure(self, task_id: str) -> dict:
        task = self.tasks.get(task_id)
        node = TASK_TO_NODE.get(task["status"], task["status"])
        l12 = str(task.get("requirement_id") or "").endswith("L12")
        config = {"slots": ["after_spec", "before_execution", "after_execution", "after_eval", "after_software_review"],
                  "handlers": ([{"handler": "flowerp.purchase_approval", "slot": "after_software_review",
                                  "config": {"purchase_ref": (task.get("business_refs") or ["PURCHASE:UNBOUND"])[0],
                                             "on_approve": "flowerp.receive_purchase"}}] if l12 else [])}
        with self._connect() as db:
            row = db.execute("SELECT * FROM workflow_instances WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                db.execute("INSERT INTO workflow_instances(task_id,definition_id,definition_version,current_node,migrated,config_json) VALUES(?,?,?,?,1,?)",
                           (task_id, "workbench.delivery", 1, node, json.dumps(config, ensure_ascii=False)))
                db.execute("INSERT INTO workflow_events(task_id,from_node,to_node,actor,reason,evidence_json) VALUES(?,?,?,?,?,?)",
                           (task_id, None, node, "migration", "按现有任务状态建立只读迁移投影；未补造历史边",
                            json.dumps({"task_status": task["status"]}, ensure_ascii=False)))
            elif row["migrated"] and row["current_node"] != node and row["current_node"] in set(TASK_TO_NODE.values()) | set(NODE_TO_TASK):
                db.execute("UPDATE workflow_instances SET current_node=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                           (node, task_id))
                db.execute("INSERT INTO workflow_events(task_id,from_node,to_node,actor,reason,evidence_json) VALUES(?,?,?,?,?,?)",
                           (task_id, row["current_node"], node, "legacy-adapter",
                            "兼容接口完成任务迁移，Graph 同步权威任务事实",
                            json.dumps({"task_status": task["status"]}, ensure_ascii=False)))
            # Store task-specific immutable definition once.
            definition_id = "workbench.l12" if l12 else "workbench.delivery"
            template_config = {"slots": config["slots"], "handlers": [item["handler"] for item in config["handlers"]]}
            raw = json.dumps(template_config, ensure_ascii=False, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO workflow_definitions VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP)",
                       (definition_id, 1, "v1", raw, hashlib.sha256(raw.encode()).hexdigest()))
            db.execute("UPDATE workflow_instances SET definition_id=?,config_json=? WHERE task_id=?",
                       (definition_id, json.dumps(config, ensure_ascii=False), task_id))
        return self.view(task_id)

    def _row(self, db: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM workflow_instances WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        return row

    @staticmethod
    def _fingerprint(action: str, payload: dict) -> str:
        return hashlib.sha256(json.dumps({"action": action, "payload": payload}, ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _idempotent(self, db, task_id: str, action: str, key: str, payload: dict):
        if not key or len(key) > 200:
            raise ValueError("Idempotency-Key 不能为空且不能超过200字符")
        fingerprint = self._fingerprint(action, payload)
        row = db.execute("SELECT * FROM workflow_requests WHERE idempotency_key=?", (key,)).fetchone()
        if row:
            if row["task_id"] != task_id or row["action"] != action or row["fingerprint"] != fingerprint:
                raise WorkflowConflict("Idempotency-Key 已用于不同请求")
            return json.loads(row["response_json"]) if row["response_json"] else None, fingerprint
        db.execute("INSERT INTO workflow_requests(idempotency_key,task_id,action,fingerprint) VALUES(?,?,?,?)",
                   (key, task_id, action, fingerprint))
        return None, fingerprint

    def _transition(self, db, row, target: str, actor: str, reason: str, evidence: dict | None = None) -> None:
        current = row["current_node"]
        if target not in CORE_EDGES.get(current, set()):
            raise ValueError(f"非法 Graph 状态迁移：{current} -> {target}")
        task_status = NODE_TO_TASK.get(target)
        task = db.execute("SELECT status FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
        if not task:
            raise KeyError(row["task_id"])
        if task_status and task_status != task["status"]:
            if task_status not in VALID_TRANSITIONS.get(task["status"], set()):
                # Fine-grained waiting nodes intentionally keep the coarse Task status.
                if not (task["status"] == "review" and task_status == "review"):
                    raise ValueError(f"Graph 与任务状态不一致：{task['status']} -> {task_status}")
            else:
                review_values = (None, None, None)
                if task_status == "completed":
                    raw_result = db.execute("SELECT result_json FROM tasks WHERE id=?", (row["task_id"],)).fetchone()[0]
                    result = json.loads(raw_result) if raw_result else {}
                    summary = result.get("summary", {}) if isinstance(result, dict) else {}
                    if summary.get("decision") != "pass" or int(summary.get("blocking_failed", 0)) != 0:
                        raise ValueError("阻断级 Eval 未通过，Graph 不能完成任务")
                    accepted = db.execute(
                        "SELECT actor,decision,reason FROM workflow_decisions WHERE task_id=? "
                        "AND decision_type='software_review' AND decision='approve' AND stale=0 ORDER BY id DESC LIMIT 1",
                        (row["task_id"],),
                    ).fetchone()
                    if not accepted:
                        raise ValueError("缺少绑定当前候选的软件审核批准，Graph 不能完成任务")
                    config = json.loads(row["config_json"] or "{}")
                    if config.get("handlers"):
                        business = db.execute(
                            "SELECT 1 FROM workflow_decisions WHERE task_id=? AND decision_type='purchase_approval' "
                            "AND decision='approve' AND stale=0 ORDER BY id DESC LIMIT 1", (row["task_id"],),
                        ).fetchone()
                        effect = db.execute(
                            "SELECT 1 FROM workflow_effects WHERE task_id=? AND handler='flowerp.receive_purchase' "
                            "AND status='completed' ORDER BY updated_at DESC LIMIT 1", (row["task_id"],),
                        ).fetchone()
                        if not business or not effect:
                            raise ValueError("采购批准或幂等收货证据不完整，Graph 不能完成任务")
                    review_values = (accepted["actor"], accepted["decision"], accepted["reason"])
                cursor = db.execute(
                    "UPDATE tasks SET status=?,reviewed_by=COALESCE(?,reviewed_by),"
                    "review_decision=COALESCE(?,review_decision),review_note=COALESCE(?,review_note),"
                    "reviewed_at=CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE reviewed_at END,"
                    "version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=?",
                    (task_status, *review_values, review_values[0], row["task_id"], task["status"]),
                )
                if cursor.rowcount != 1:
                    raise WorkflowConflict("任务状态已变化，Graph 拒绝覆盖")
                db.execute("INSERT INTO task_events(task_id,from_status,to_status,detail,actor,evidence_json) VALUES(?,?,?,?,?,?)",
                           (row["task_id"], task["status"], task_status, reason, actor,
                            json.dumps(evidence, ensure_ascii=False) if evidence else None))
        cursor = db.execute("UPDATE workflow_instances SET current_node=?,version=version+1,migrated=0,updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND version=?",
                            (target, row["task_id"], row["version"]))
        if cursor.rowcount != 1:
            raise WorkflowConflict("Graph 版本已变化")
        db.execute("INSERT INTO workflow_events(task_id,from_node,to_node,actor,reason,evidence_json) VALUES(?,?,?,?,?,?)",
                   (row["task_id"], current, target, actor, reason,
                    json.dumps(evidence, ensure_ascii=False) if evidence else None))
        attempt = db.execute("SELECT COUNT(*) FROM workflow_node_runs WHERE task_id=? AND node=?",
                             (row["task_id"], target)).fetchone()[0] + 1
        input_sha = hashlib.sha256(json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        db.execute("INSERT INTO workflow_node_runs(task_id,node,attempt,input_sha256,status,result_json,ended_at) "
                   "VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                   (row["task_id"], target, attempt, input_sha, "completed",
                    json.dumps({"reason": reason}, ensure_ascii=False)))

    def _acquire_lease(self, db, row, owner: str, seconds: int = 30) -> None:
        now = time.time()
        if row["lease_owner"] and float(row["lease_until"] or 0) > now and row["lease_owner"] != owner:
            raise WorkflowConflict(f"Graph 正由 {row['lease_owner']} 推进")
        cursor = db.execute(
            "UPDATE workflow_instances SET lease_owner=?,lease_until=? WHERE task_id=? AND version=?",
            (owner, now + seconds, row["task_id"], row["version"]),
        )
        if cursor.rowcount != 1:
            raise WorkflowConflict("Graph 版本已变化，未取得执行租约")

    def advance(self, task_id: str, *, actor: str, expected_version: int, key: str) -> dict:
        actor = actor.strip()
        if not actor:
            raise ValueError("必须填写具名操作者")
        self.ensure(task_id)
        payload = {"actor": actor, "expected_version": int(expected_version)}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous, _ = self._idempotent(db, task_id, "advance", key, payload)
            if previous is not None:
                return previous
            row = self._row(db, task_id)
            if row["version"] != int(expected_version):
                raise WorkflowConflict(f"Graph 版本已变化：期望 {expected_version}，实际 {row['version']}")
            self._acquire_lease(db, row, actor)
            automatic = {"queued": "spec_ready", "spec_ready": "awaiting_execution_authorization",
                         "executing": "evaluating", "post_review": "completed", "rework": "executing"}
            target = automatic.get(row["current_node"])
            if row["current_node"] == "evaluating":
                raw = db.execute("SELECT result_json FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
                report = json.loads(raw) if raw else {}
                summary = report.get("summary", {}) if isinstance(report, dict) else {}
                target = "awaiting_software_review" if (
                    summary.get("decision") == "pass" and int(summary.get("blocking_failed", 0)) == 0
                ) else "rework"
            if row["current_node"] == "rework":
                attempts = db.execute("SELECT COUNT(*) FROM workflow_events WHERE task_id=? AND to_node='rework'",
                                      (task_id,)).fetchone()[0]
                if attempts >= 3:
                    target = "stopped"
            if not target:
                raise ValueError(f"节点 {row['current_node']} 不能自动推进")
            self._transition(db, row, target, actor, "Graph 自动推进一个安全节点")
            db.execute("UPDATE workflow_instances SET lease_owner=NULL,lease_until=NULL WHERE task_id=?", (task_id,))
            response = self._view_db(db, task_id)
            db.execute("UPDATE workflow_requests SET response_json=? WHERE idempotency_key=?",
                       (json.dumps(response, ensure_ascii=False), key))
            return response

    def decide(self, task_id: str, *, decision_type: str, decision: str, actor: str, role: str,
               reason: str, expected_version: int, candidate_revision: int, candidate_sha256: str,
               key: str, target_ref: str = "") -> dict:
        if decision_type not in {"software_review", "purchase_approval"} or decision not in {"approve", "reject"}:
            raise ValueError("决定类型或决定值无效")
        if not actor.strip() or not reason.strip() or not role.strip():
            raise ValueError("决定必须包含具名人员、角色和理由")
        self.ensure(task_id)
        payload = {"type": decision_type, "decision": decision, "actor": actor.strip(), "role": role.strip(),
                   "reason": reason.strip(), "expected_version": int(expected_version),
                   "candidate_revision": int(candidate_revision), "candidate_sha256": candidate_sha256,
                   "target_ref": target_ref}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous, _ = self._idempotent(db, task_id, "decision", key, payload)
            if previous is not None:
                return previous
            row = self._row(db, task_id)
            if row["version"] != int(expected_version):
                raise WorkflowConflict(f"Graph 版本已变化：期望 {expected_version}，实际 {row['version']}")
            if row["candidate_revision"] != int(candidate_revision) or row["candidate_sha256"] != candidate_sha256:
                raise WorkflowConflict("决定所绑定的候选版本已经变化")
            expected_node = "awaiting_software_review" if decision_type == "software_review" else "awaiting_purchase_approval"
            if row["current_node"] != expected_node:
                raise ValueError(f"当前节点不能提交 {decision_type} 决定")
            if decision_type == "software_review" and role != "human:reviewer":
                raise ValueError("软件审核必须由 human:reviewer 作出")
            if decision_type == "purchase_approval" and role != "human:purchase_approver":
                raise ValueError("采购批准必须由 human:purchase_approver 作出")
            db.execute("INSERT INTO workflow_decisions(task_id,decision_type,actor,role,decision,reason,candidate_revision,candidate_sha256,target_ref) VALUES(?,?,?,?,?,?,?,?,?)",
                       (task_id, decision_type, actor.strip(), role, decision, reason.strip(), int(candidate_revision), candidate_sha256, target_ref))
            if decision_type == "software_review":
                target = "post_review" if decision == "approve" else "rework"
                if decision == "approve":
                    config = json.loads(row["config_json"] or "{}")
                    target = "awaiting_purchase_approval" if config.get("handlers") else "completed"
                    # post_review remains explicit in the audit trail.
                    self._transition(db, row, "post_review", actor, reason, payload)
                    row = self._row(db, task_id)
                self._transition(db, row, target, actor, reason, payload)
            else:
                self._transition(db, row, "receiving" if decision == "approve" else "business_rejected",
                                 actor, reason, payload)
            response = self._view_db(db, task_id)
            db.execute("UPDATE workflow_requests SET response_json=? WHERE idempotency_key=?",
                       (json.dumps(response, ensure_ascii=False), key))
            return response

    def authorize(self, task_id: str, *, actor: str, expected_version: int, candidate_sha256: str, key: str) -> dict:
        self.ensure(task_id)
        payload = {"actor": actor.strip(), "expected_version": int(expected_version), "candidate_sha256": candidate_sha256}
        if not payload["actor"] or not candidate_sha256:
            raise ValueError("执行授权必须绑定具名授权人和候选哈希")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous, _ = self._idempotent(db, task_id, "authorize", key, payload)
            if previous is not None:
                return previous
            row = self._row(db, task_id)
            if row["version"] != int(expected_version) or row["current_node"] != "awaiting_execution_authorization":
                raise WorkflowConflict("授权节点或 Graph 版本已经变化")
            db.execute("UPDATE workflow_instances SET candidate_sha256=? WHERE task_id=?", (candidate_sha256, task_id))
            row = self._row(db, task_id)
            self._transition(db, row, "executing", actor.strip(), "具名授权执行", payload)
            response = self._view_db(db, task_id)
            db.execute("UPDATE workflow_requests SET response_json=? WHERE idempotency_key=?",
                       (json.dumps(response, ensure_ascii=False), key))
            return response

    def recover(self, task_id: str, *, actor: str, reason: str, expected_version: int, key: str) -> dict:
        self.ensure(task_id)
        payload = {"actor": actor.strip(), "reason": reason.strip(), "expected_version": int(expected_version)}
        if not payload["actor"] or not payload["reason"]:
            raise ValueError("恢复必须记录具名人员和核对理由")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous, _ = self._idempotent(db, task_id, "recover", key, payload)
            if previous is not None:
                return previous
            row = self._row(db, task_id)
            if row["version"] != int(expected_version) or row["current_node"] not in {"failed", "dead_letter"}:
                raise WorkflowConflict("只有当前 failed/dead_letter 节点可以恢复")
            self._transition(db, row, "rework", actor.strip(), reason.strip(), {"human_checked": True})
            response = self._view_db(db, task_id)
            db.execute("UPDATE workflow_requests SET response_json=? WHERE idempotency_key=?",
                       (json.dumps(response, ensure_ascii=False), key))
            return response

    def bind_candidate(self, task_id: str, sha256: str) -> dict:
        """Invalidate decisions when a new candidate is observed."""
        self.ensure(task_id)
        if not sha256:
            raise ValueError("候选哈希不能为空")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, task_id)
            if row["candidate_sha256"] == sha256:
                return self._view_db(db, task_id)
            db.execute("UPDATE workflow_instances SET candidate_revision=candidate_revision+1,candidate_sha256=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                       (sha256, task_id))
            db.execute("UPDATE workflow_decisions SET stale=1 WHERE task_id=? AND stale=0", (task_id,))
            db.execute("INSERT INTO workflow_events(task_id,from_node,to_node,actor,reason,evidence_json) VALUES(?,?,?,?,?,?)",
                       (task_id, row["current_node"], row["current_node"], "system", "候选内容变化，旧决定失效",
                        json.dumps({"candidate_sha256": sha256}, ensure_ascii=False)))
            return self._view_db(db, task_id)

    def begin_effect(self, task_id: str, *, handler: str, business_ref: str, request: dict,
                     idempotency_key: str, expected_version: int) -> dict:
        """Reserve a registered side effect before a trusted connector executes it."""
        self.ensure(task_id)
        definition = HANDLERS.get(handler)
        if not definition or not definition.side_effect:
            raise ValueError("只能执行已注册的副作用处理器")
        if not business_ref.strip() or not idempotency_key.strip():
            raise ValueError("副作用必须绑定业务对象和幂等键")
        missing = [name for name in definition.schema.get("required", []) if name not in request]
        if missing:
            raise ValueError("处理器参数缺失：" + "、".join(missing))
        raw = json.dumps(request, ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, task_id)
            if row["version"] != int(expected_version) or row["current_node"] != "receiving":
                raise WorkflowConflict("收货节点或 Graph 版本已经变化")
            existing = db.execute("SELECT * FROM workflow_effects WHERE idempotency_key=?",
                                  (idempotency_key,)).fetchone()
            if existing:
                if existing["task_id"] != task_id or existing["handler"] != handler or existing["request_sha256"] != fingerprint:
                    raise WorkflowConflict("副作用幂等键已用于不同请求")
                return dict(existing)
            db.execute("INSERT INTO workflow_effects(idempotency_key,task_id,handler,business_ref,request_sha256,status) VALUES(?,?,?,?,?,'pending')",
                       (idempotency_key, task_id, handler, business_ref.strip(), fingerprint))
            return dict(db.execute("SELECT * FROM workflow_effects WHERE idempotency_key=?", (idempotency_key,)).fetchone())

    def finish_effect(self, task_id: str, *, idempotency_key: str, result: dict, error: str = "") -> dict:
        """Persist connector output and advance only after a conclusive result."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            effect = db.execute("SELECT * FROM workflow_effects WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if not effect or effect["task_id"] != task_id:
                raise KeyError(idempotency_key)
            if effect["status"] == "completed":
                return self._view_db(db, task_id)
            row = self._row(db, task_id)
            if row["current_node"] != "receiving":
                raise WorkflowConflict("当前已不在收货节点")
            status = "failed" if error else "completed"
            db.execute("UPDATE workflow_effects SET status=?,result_json=?,updated_at=CURRENT_TIMESTAMP WHERE idempotency_key=? AND status='pending'",
                       (status, json.dumps({"result": result, "error": error}, ensure_ascii=False), idempotency_key))
            target = "failed" if error else "reconciling"
            self._transition(db, row, target, f"handler:{effect['handler']}",
                             error or "已保存幂等副作用结果", {"idempotency_key": idempotency_key})
            return self._view_db(db, task_id)

    def reconcile(self, task_id: str, *, actor: str, evidence: dict, expected_version: int, key: str) -> dict:
        self.ensure(task_id)
        payload = {"actor": actor.strip(), "evidence": evidence, "expected_version": int(expected_version)}
        if not actor.strip() or evidence.get("matched") is not True:
            raise ValueError("完成前必须提供具名且匹配的业务对账证据")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous, _ = self._idempotent(db, task_id, "reconcile", key, payload)
            if previous is not None:
                return previous
            row = self._row(db, task_id)
            if row["version"] != int(expected_version) or row["current_node"] != "reconciling":
                raise WorkflowConflict("对账节点或 Graph 版本已经变化")
            self._transition(db, row, "completed", actor.strip(), "业务状态与 Graph 对账通过", evidence)
            response = self._view_db(db, task_id)
            db.execute("UPDATE workflow_requests SET response_json=? WHERE idempotency_key=?",
                       (json.dumps(response, ensure_ascii=False), key))
            return response

    def view(self, task_id: str) -> dict:
        with self._connect() as db:
            return self._view_db(db, task_id)

    def _view_db(self, db, task_id: str) -> dict:
        row = self._row(db, task_id)
        definition = db.execute("SELECT * FROM workflow_definitions WHERE id=? AND version=?",
                                (row["definition_id"], row["definition_version"])).fetchone()
        config = json.loads(row["config_json"] or "{}")
        extra = ["awaiting_purchase_approval", "receiving", "reconciling", "business_rejected"] if config.get("handlers") else []
        nodes = list(CORE_NODES[:-4]) + extra + list(CORE_NODES[-4:])
        events = [dict(item) for item in db.execute("SELECT * FROM workflow_events WHERE task_id=? ORDER BY id", (task_id,))]
        decisions = []
        for item in db.execute("SELECT * FROM workflow_decisions WHERE task_id=? ORDER BY id", (task_id,)):
            decisions.append(dict(item))
        visited = {e["to_node"] for e in events}
        current = row["current_node"]
        allowed = []
        if current in {"queued", "executing", "post_review"}: allowed.append("advance")
        if current == "awaiting_execution_authorization": allowed.append("authorize")
        if current in {"awaiting_software_review", "awaiting_purchase_approval"}: allowed.append("decide")
        if current in {"failed", "dead_letter"}: allowed.append("recover")
        if current == "receiving": allowed.append("run_registered_handler")
        if current == "reconciling": allowed.append("reconcile")
        owner = {"awaiting_execution_authorization": "human:authorizer", "awaiting_software_review": "human:reviewer",
                 "awaiting_purchase_approval": "human:purchase_approver"}.get(current, "workbench")
        return {
            "schema": "workbench.workflow-graph/v1", "task_id": task_id,
            "definition": {"id": row["definition_id"], "version": row["definition_version"],
                           "core_version": definition["core_version"] if definition else "v1",
                           "config_sha256": definition["config_sha256"] if definition else ""},
            "current": current, "version": row["version"], "state": row["state"],
            "candidate": {"revision": row["candidate_revision"], "sha256": row["candidate_sha256"]},
            "migrated": bool(row["migrated"]), "owner": owner,
            "waiting": current in WAITING_NODES,
            "nodes": [{"id": node, "state": "current" if node == current else "visited" if node in visited else "pending"}
                      for node in nodes],
            "edges": [{"from": source, "to": target} for source, targets in CORE_EDGES.items()
                      for target in sorted(targets) if source in nodes and target in nodes],
            "events": [{**{k: value for k, value in e.items() if k != "evidence_json"},
                        "evidence": json.loads(e["evidence_json"]) if e.get("evidence_json") else None}
                       for e in events],
            "decisions": decisions, "allowed_actions": allowed,
            "handlers": config.get("handlers", []),
            "runs": [dict(item) for item in db.execute(
                "SELECT id,node,attempt,input_sha256,handler,handler_version,status,error,started_at,ended_at "
                "FROM workflow_node_runs WHERE task_id=? ORDER BY id", (task_id,))],
        }
