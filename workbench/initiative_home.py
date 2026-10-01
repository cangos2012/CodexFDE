"""Cheap, read-only initiative summaries and keyset pagination for the home page.

The summary deliberately reads persisted state only. File checks, learning
history and task events belong to the detail screen, not a polling dashboard.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


RUNNING = frozenset({"researching", "queued", "executing", "checking", "cancelling", "integrating"})
OUTCOME = frozenset({"integrated", "released", "observed"})
ATTENTION = frozenset({"idle", "clarifying", "ready", "confirmed", "cancelled", "interrupted",
                       "failed", "rework", "review", "accepted", "completed", "dead_letter"})
GROUPS = frozenset({"all", "attention", "running", "outcome", "unknown"})


def status_group(stage: str) -> str:
    if stage in RUNNING:
        return "running"
    if stage in OUTCOME:
        return "outcome"
    if stage in ATTENTION:
        return "attention"
    return "unknown"


def _boolean(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"1", "true"}:
        return True
    if str(value).lower() in {"0", "false"}:
        return False
    raise ValueError("筛选开关必须是 true 或 false")


def _signature(filters: dict) -> str:
    return hashlib.sha256(json.dumps(filters, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _cursor(row, signature: str) -> str:
    raw = json.dumps([row["updated_at"], row["id"], signature], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str, signature: str) -> tuple[str, str]:
    try:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        parts = json.loads(raw.decode("utf-8"))
        if (not isinstance(parts, list) or len(parts) != 3 or
                not all(isinstance(part, str) for part in parts) or parts[2] != signature):
            raise ValueError
        return parts[0], parts[1]
    except (ValueError, UnicodeError, TypeError) as error:
        raise ValueError("分页游标无效或筛选条件已变化，请从第一页重试") from error


class InitiativeHome:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def page(self, *, home=True, project_id="", group="all", q="", include_mock=None,
             include_hidden=None, limit=None, cursor="") -> dict:
        project_id = str(project_id or "").strip()
        if project_id == "all":
            project_id = ""
        group = str(group or "all")
        if group not in GROUPS:
            raise ValueError("未知事项状态组")
        q = str(q or "").strip()
        if len(q) > 200:
            raise ValueError("检索词不能超过 200 字符")
        include_mock = _boolean(include_mock, not home)
        include_hidden = _boolean(include_hidden, not home)
        try:
            size = int(limit if limit is not None else (20 if home else 100))
        except (ValueError, TypeError) as error:
            raise ValueError("每页数量必须是整数") from error
        if not 1 <= size <= 100:
            raise ValueError("每页数量必须在 1 到 100 之间")
        signature = _signature(dict(project_id=project_id, group=group, q=q,
                                    include_mock=include_mock, include_hidden=include_hidden, home=home))
        anchor = _decode_cursor(cursor, signature) if cursor else None
        # No store constructor or connect() here: those initialize tables and
        # participate in the runtime write gate. A dashboard stays read-only.
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=15)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")  # counts, projects and page share a read snapshot
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            projects = ([dict(row) for row in db.execute("SELECT id,name FROM harness_projects ORDER BY name,id")]
                        if "harness_projects" in tables else [])
            workflow_join = ""
            task_join = ""
            stage, revision, goal, task_id, release = "'idle'", "0", "NULL", "NULL", "NULL"
            if "initiative_workflows" in tables:
                workflow_join = " LEFT JOIN initiative_workflows w ON w.id=i.id"
                valid = "json_valid(w.payload)"
                task_id = f"CASE WHEN {valid} THEN json_extract(w.payload,'$.active_task_id') END"
                raw_stage = f"CASE WHEN w.id IS NULL THEN 'idle' WHEN {valid} THEN json_extract(w.payload,'$.stage') ELSE 'unavailable' END"
                stage = raw_stage
                revision = f"CASE WHEN {valid} THEN json_extract(w.payload,'$.revision') ELSE 0 END"
                goal = f"CASE WHEN {valid} THEN json_extract(w.payload,'$.proposal.goal') END"
                release = f"CASE WHEN {valid} THEN json_extract(w.payload,'$.current_release') END"
                if "tasks" in tables:
                    task_join = f" LEFT JOIN tasks t ON t.id=({task_id})"
                    stage = (f"CASE WHEN {valid} AND json_extract(w.payload,'$.v0')=1 AND "
                             "t.status IN ('review','completed','rework','failed','dead_letter') "
                             f"THEN t.status ELSE ({raw_stage}) END")
            fields = ("i.id,i.title,i.project_id,i.goal,i.raw_signal,i.version,i.home_hidden,i.updated_at,i.created_at"
                      if home else "i.*")
            sql = ("SELECT " + fields + ", " + stage + " AS workflow_stage, " + revision + " AS workflow_revision, "
                   + goal + " AS proposal_goal, " + task_id + " AS workflow_task, " + release + " AS current_release "
                   + "FROM initiatives i" + workflow_join + task_join)
            conditions, parameters = [], []
            if project_id:
                conditions.append("i.project_id=?")
                parameters.append(project_id)
            if not include_mock:
                conditions.append("i.title NOT LIKE '[Mock课程演示]%'")
            if not include_hidden:
                busy = ",".join("'" + value + "'" for value in sorted(RUNNING))
                conditions.append(f"(i.home_hidden=0 OR ({stage}) IN ({busy}))")
            if q:
                literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                conditions.append("(" + " OR ".join(f"i.{field} LIKE ? ESCAPE '\\'" for field in
                    ("id", "title", "raw_signal", "goal", "problem_statement")) + ")")
                parameters.extend(["%" + literal + "%"] * 5)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            # The database aggregates all matches, but returns only one page.
            # JSON manifests, messages and histories never leave SQLite.
            category_cases = []
            for category, stages in (("running", RUNNING), ("outcome", OUTCOME), ("attention", ATTENTION)):
                values = ",".join("'" + value + "'" for value in sorted(stages))
                category_cases.append(f"WHEN workflow_stage IN ({values}) THEN '{category}'")
            base_sql = ("WITH projected AS (" + sql + "), grouped AS (SELECT *, CASE "
                        + " ".join(category_cases) + " ELSE 'unknown' END AS status_group FROM projected) ")
            stats = db.execute(base_sql + "SELECT status_group,COUNT(*) AS amount, "
                "SUM(title NOT LIKE '[Mock课程演示]%' AND current_release IS NOT NULL AND current_release!='') AS released, "
                "SUM(title NOT LIKE '[Mock课程演示]%' AND workflow_stage='observed') AS observed "
                "FROM grouped GROUP BY status_group", parameters).fetchall()
            counts = {key: 0 for key in ("attention", "running", "outcome", "unknown")}
            outcome_counts = {"released": 0, "observed": 0}
            for row in stats:
                counts[row["status_group"]] = row["amount"]
                outcome_counts["released"] += row["released"] or 0
                outcome_counts["observed"] += row["observed"] or 0
            matching_total = sum(counts.values())
            total = matching_total if group == "all" else counts[group]
            page_conditions, page_parameters = [], list(parameters)
            if group != "all":
                page_conditions.append("status_group=?")
                page_parameters.append(group)
            if anchor:
                page_conditions.append("(updated_at<? OR (updated_at=? AND id<?))")
                page_parameters.extend((anchor[0], anchor[0], anchor[1]))
            page_where = " WHERE " + " AND ".join(page_conditions) if page_conditions else ""
            page_parameters.append(size + 1)
            selected = db.execute(base_sql + "SELECT * FROM grouped" + page_where
                                  + " ORDER BY updated_at DESC,id DESC LIMIT ?", page_parameters).fetchall()
            page = selected[:size]
            next_cursor = _cursor(page[-1], signature) if len(selected) > size else None
            # This is informational and does not affect filtering/statistics.
            has_mock = bool(db.execute("SELECT 1 FROM initiatives WHERE title LIKE '[Mock课程演示]%' LIMIT 1").fetchone())
            project_names = {project["id"]: project["name"] for project in projects}
            items = []
            for row in page:
                if not home:
                    from .initiative import InitiativeStore
                    raw = {key: row[key] for key in row.keys() if key not in {
                        "workflow_stage", "workflow_revision", "proposal_goal", "workflow_task", "current_release", "status_group"}}
                    # Projection helpers only: never instantiate the mutating store.
                    store = object.__new__(InitiativeStore)
                    items.append(store._project(store._decode(raw)))
                    continue
                item = {key: row[key] for key in ("id", "title", "project_id", "goal", "raw_signal", "version",
                                                  "home_hidden", "updated_at", "created_at")}
                work = {"stage": row["workflow_stage"] or "unavailable", "revision": row["workflow_revision"],
                        "active_task_id": row["workflow_task"], "current_release": row["current_release"],
                        "proposal": {"goal": row["proposal_goal"] or ""},
                        "project": {"id": row["project_id"], "name": project_names.get(row["project_id"], "项目")}}
                items.append({"item": item, "work": work, "group": status_group(work["stage"])})
            return {"items": items, "counts": counts, "total": total, "matching_total": matching_total,
                    "next_cursor": next_cursor, "projects": projects, "outcomes": outcome_counts,
                    "has_mock": has_mock}
