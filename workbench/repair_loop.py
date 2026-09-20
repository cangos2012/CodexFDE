"""L10 bounded repair-loop projection for an initiative delivery history."""
from __future__ import annotations

import time


DEFAULTS = {"enabled": False, "max_rounds": 3, "token_budget": 30_000,
            "time_budget_seconds": 900}


def validate_config(raw: dict | None) -> dict:
    raw = raw or {}
    enabled = raw.get("enabled") is True
    try:
        rounds = int(raw.get("max_rounds", DEFAULTS["max_rounds"]))
        tokens = int(raw.get("token_budget", DEFAULTS["token_budget"]))
        seconds = int(raw.get("time_budget_seconds", DEFAULTS["time_budget_seconds"]))
    except (TypeError, ValueError) as error:
        raise ValueError("Loop 边界必须是整数") from error
    if not 1 <= rounds <= 3:
        raise ValueError("L10 Loop 最多三轮")
    if tokens <= 0 or seconds <= 0:
        raise ValueError("Token 与时间预算必须大于 0")
    return {"enabled": enabled, "max_rounds": rounds, "token_budget": tokens,
            "time_budget_seconds": seconds}


def _blocking(task: dict) -> list[str]:
    report = task.get("result") or {}
    return sorted(str(row.get("name")) for row in report.get("results", [])
                  if isinstance(row, dict) and row.get("level") == "blocking" and not row.get("passed"))


def _execution(task: dict) -> dict:
    return next((event.get("evidence") or {} for event in reversed(task.get("events", []))
                 if event.get("detail") == "受控执行阶段完成"), {})


def project(config: dict | None, iterations: list[dict], tasks, *, now: float | None = None) -> dict:
    """Return an evidence-bound Loop view without changing task state."""
    bounds = validate_config(config)
    history, tokens_used, usage_missing = [], 0, False
    for number, iteration in enumerate(iterations, 1):
        task = tasks.get(iteration["task_id"])
        execution = _execution(task)
        usage = execution.get("usage") if isinstance(execution.get("usage"), dict) else None
        measured = usage.get("total_tokens") if usage else None
        if execution and (not isinstance(measured, int) or measured <= 0):
            usage_missing = True
        if isinstance(measured, int) and measured > 0:
            tokens_used += measured
        failures = _blocking(task)
        history.append({"round": number, "task_id": task["id"], "task_status": task["status"],
                        "failures": failures, "changed_files": execution.get("changed_files", []),
                        "tokens": measured, "verified": isinstance(task.get("result"), dict)})

    started = min((float(row.get("at", now or time.time())) for row in iterations if row.get("at") is not None),
                  default=None)
    elapsed = max(0, int((now or time.time()) - started)) if started is not None else 0
    status, reason, can_continue = "ready", "尚未开始修复轮次", True
    if history:
        last = history[-1]
        if last["verified"] and not last["failures"] and last["task_status"] in {"review", "completed"}:
            status, reason, can_continue = "converged", "最近一次检查已通过；等待具名验收", False
        elif not last["verified"] and last["changed_files"]:
            status, reason, can_continue = "modified_pending_verification", "末轮已有修改但尚未复验", False
        elif usage_missing:
            status, reason, can_continue = "stopped_token_usage_unavailable", "执行器未返回可核验 Token 用量", False
        elif tokens_used >= bounds["token_budget"]:
            status, reason, can_continue = "stopped_token_budget", "累计 Token 用量达到或超过预算", False
        elif elapsed >= bounds["time_budget_seconds"]:
            status, reason, can_continue = "stopped_time_budget", "累计时间达到或超过预算", False
        elif len(history) >= 2 and history[-1]["failures"] and history[-1]["failures"] == history[-2]["failures"]:
            status, reason, can_continue = "stopped_no_progress", "连续两次检查的阻断失败名称没有减少", False
        elif len(history) >= bounds["max_rounds"]:
            status, reason, can_continue = "stopped_max_rounds", "已达到最大轮数", False
        else:
            status, reason = "continue", "仍有阻断失败，且预算允许继续一轮"

    remaining = history[-1]["failures"] if history else []
    latest = history[-1] if history else None
    handoff = None if can_continue or status == "converged" else {
        "stop_reason": reason,
        "last_task_id": latest["task_id"] if latest else None,
        "last_verified_round": max((row["round"] for row in history if row["verified"]), default=None),
        "remaining_failures": remaining,
        "changed_files": latest["changed_files"] if latest else [],
        "unverified": ["末轮修改尚未复验"] if status == "modified_pending_verification" else [],
        "next_action": "先核对最后候选、原始报告与 Diff，再由具名负责人决定复验、缩小范围或停止。",
    }
    return {"config": bounds, "status": status, "reason": reason,
            "can_continue": bool(bounds["enabled"] and can_continue), "rounds": len(history),
            "tokens_used": tokens_used, "tokens_remaining": max(0, bounds["token_budget"] - tokens_used),
            "elapsed_seconds": elapsed, "remaining_failures": remaining,
            "history": history, "handoff": handoff}
