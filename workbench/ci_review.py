"""Verify and retain CI evidence for a workbench delivery candidate."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse


def _text(value, name: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{name}不能为空或过长")
    return value.strip()


def verify(report_text: str, envelope: dict, *, run_url: str, job_conclusion: str,
           candidate_sha: str) -> dict:
    if not isinstance(report_text, str) or not report_text.strip() or len(report_text.encode("utf-8")) > 5_000_000:
        raise ValueError("Harness 原始报告为空或超过 5 MB")
    try:
        report = json.loads(report_text)
    except json.JSONDecodeError as error:
        raise ValueError("Harness 原始报告不是有效 JSON") from error
    if not isinstance(report, dict) or not isinstance(envelope, dict):
        raise ValueError("报告和 Evidence Envelope 必须是 JSON 对象")
    commit = _text(envelope.get("commit_sha"), "Envelope commit_sha")
    run_id = _text(envelope.get("run_id"), "Envelope run_id")
    if commit.upper().startswith("SIMULATED") or run_id.upper().startswith("SIMULATED"):
        raise ValueError("SIMULATED 身份只能用于教学观察，不能登记为真实 CI 证据")
    candidate = _text(candidate_sha, "实际 checkout SHA")
    if commit != candidate:
        raise ValueError("Evidence Envelope 的提交与实际 checkout SHA 不一致")
    parsed = urlparse(_text(run_url, "Run 链接", 2000))
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Run 链接必须是可回查的 HTTPS 平台地址")
    actual_hash = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
    if envelope.get("report_sha256") != actual_hash:
        raise ValueError("原始报告 SHA-256 与 Evidence Envelope 不一致")
    summary = report.get("summary")
    decision = summary.get("decision") if isinstance(summary, dict) else None
    if decision not in {"pass", "block"} or envelope.get("report_decision") != decision:
        raise ValueError("报告或 Evidence Envelope 缺少一致的 pass/block 决策")
    conclusion = _text(job_conclusion, "Job 结论", 20).lower()
    if conclusion not in {"success", "failure"}:
        raise ValueError("Job 结论只能是 success 或 failure")
    expected = "success" if decision == "pass" else "failure"
    if conclusion != expected:
        raise ValueError("Harness 决策没有如实传播到 CI Job，当前证据不可信")
    return {
        "status": "verified", "candidate_sha": candidate, "run_id": run_id,
        "run_url": run_url.strip(), "workflow": str(envelope.get("workflow") or ""),
        "runner_os": str(envelope.get("runner_os") or ""), "python": str(envelope.get("python") or ""),
        "suite": report.get("suite"), "report_decision": decision,
        "job_conclusion": conclusion, "report_sha256": actual_hash,
        "requested_cases": report.get("requested_cases") or [],
    }


def retain(runtime: str | Path, task_id: str, report_text: str, envelope: dict,
           *, run_url: str, job_conclusion: str, candidate_sha: str, actor: str) -> dict:
    result = verify(report_text, envelope, run_url=run_url, job_conclusion=job_conclusion,
                    candidate_sha=candidate_sha)
    token = hashlib.sha256(f"{task_id}:{result['run_id']}:{time.time_ns()}".encode()).hexdigest()[:20]
    folder = Path(runtime).resolve() / "ci-evidence" / task_id / token
    folder.mkdir(parents=True, exist_ok=False)
    report_path, envelope_path = folder / "report.json", folder / "envelope.json"
    report_path.write_text(report_text, encoding="utf-8")
    envelope_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    result.update(actor=actor, recorded_at=time.time(), artifacts={
        "report": str(report_path), "envelope": str(envelope_path)})
    return result


def view(records) -> dict:
    clean = list(records or [])[-20:]
    latest = clean[-1] if clean else None
    return {"status": latest.get("status") if latest else "missing", "latest": latest, "history": clean}
