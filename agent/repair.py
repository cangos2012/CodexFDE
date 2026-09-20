from __future__ import annotations

import argparse
import sys
import json
import hashlib
from pathlib import Path
from pathlib import PurePosixPath


def map_repair_report(raw_report: bytes, *, source_task: str, candidate: str,
                      allowed_files: list[str], required_cases: list[str],
                      actual_exit: int, cwd: str, python_executable: str,
                      source_report: str, source_version: str, objective: str,
                      expected_suite: str = "blocking") -> dict:
    """Pure strict mapper. Context is supplied by the trusted caller, never evidence.

    Hash the original bytes, not a reserialized dictionary. No files or ledger
    entries are written; invalid reports cannot yield an executable repair task.
    The legacy build_repair_task API below remains available for older callers.
    """
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def names(value):
        return (isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
                and len(value) == len(set(value)))

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    try:
        require(isinstance(raw_report, bytes), "report must be original bytes")
        require(all(isinstance(v, str) and v.strip() for v in (source_task, candidate, cwd, python_executable, source_report, source_version, objective)), "missing source context")
        require(Path(source_report).is_absolute(), "source report path must be absolute")
        require(candidate == str(Path(cwd).resolve()), "candidate must match resolved cwd")
        require(Path(cwd).is_absolute() and Path(cwd).is_dir(), "cwd must exist and be absolute")
        require(Path(python_executable).is_absolute() and Path(python_executable).is_file(), "Python executable must exist")
        require(names(allowed_files) and bool(allowed_files), "explicit allowed files required")
        for name in allowed_files:
            path = PurePosixPath(name)
            require(not path.is_absolute() and str(path) == name and not any(
                p in {"..", ".git", ".codex", ".runtime", ".tmp"} or p.startswith(".env") for p in path.parts)
                and not any(c in name for c in "\\:*?\x00") and bool(path.suffix), "unsafe allowed file")
        require(names(required_cases) and bool(required_cases), "required cases missing")
        require(type(actual_exit) is int and actual_exit in (0, 1), "invalid process exit")
        report = json.loads(raw_report.decode("utf-8-sig"), object_pairs_hook=unique_object)
        require(isinstance(report, dict) and report.get("schema_version") == "1.0", "unsupported report protocol")
        suite = report.get("suite")
        require(expected_suite in ("all", "blocking", "observing") and suite == expected_suite, "suite/request mismatch")
        require(isinstance(report.get("generated_at"), str) and bool(report["generated_at"].strip()), "missing timestamp")
        require(names(report.get("requested_cases")), "invalid requested cases")
        rows = report.get("results")
        require(isinstance(rows, list) and bool(rows), "empty results")
        for row in rows:
            require(isinstance(row, dict), "invalid result")
            require(isinstance(row.get("name"), str) and bool(row["name"].strip()), "missing case name")
            require(type(row.get("passed")) is bool, "passed must be boolean")
            require(row.get("level") in ("blocking", "observing"), "invalid level")
            require(suite == "all" or row["level"] == suite, "suite/level mismatch")
            require(isinstance(row.get("evidence"), str) and bool(row["evidence"].strip()), "missing evidence")
            require(type(row.get("duration_ms")) is int and row["duration_ms"] >= 0, "invalid duration")
        case_names = [r["name"] for r in rows]
        require(names(case_names), "duplicate cases")
        require(set(required_cases) <= set(case_names), "required cases absent")
        require(all(r["level"] == "blocking" for r in rows if r["name"] in required_cases), "required case downgraded")
        require(not report["requested_cases"] or set(report["requested_cases"]) == set(case_names), "requested cases mismatch")
        failed = [r for r in rows if r["level"] == "blocking" and not r["passed"]]
        observing = [dict(r) for r in rows if r["level"] == "observing"]
        expected = dict(total=len(rows), passed=sum(r["passed"] for r in rows),
                        blocking_failed=len(failed), observing_failed=sum(not r["passed"] for r in observing),
                        decision="block" if failed else "pass")
        summary = report.get("summary")
        require(isinstance(summary, dict), "missing summary")
        require(all(type(summary.get(k)) is type(v) and summary[k] == v for k, v in expected.items()), "summary mismatch")
        require(actual_exit == (1 if failed else 0), "process/report mismatch")
        if not failed:
            return {"status": "no_blocking_repair", "task": None, "observations": observing}
        command = {"argv": [python_executable, "-B", "-X", "utf8", "-m", "eval.harness", "--suite", "blocking", "--no-report"], "cwd": cwd}
        task = dict(source_task=source_task, candidate=candidate,
                    objective=objective, source_report=source_report, source_version=source_version,
                    report_sha256=hashlib.sha256(raw_report).hexdigest(), allowed_files=list(allowed_files),
                    scope=[r["name"] for r in failed], evidence=[dict(r) for r in failed],
                    reproduce={"argv": command["argv"] + [v for r in failed for v in ("--case", r["name"])], "cwd": cwd},
                    acceptance=command, actual_exit=actual_exit, required_cases=list(required_cases),
                    max_attempts=1, human_review="pending")
        return {"status": "repair_required" if failed else "no_blocking_repair", "task": task, "observations": observing}
    except (ValueError, TypeError, UnicodeError, OSError, RecursionError) as exc:
        return {"status": "invalid_report", "errors": [str(exc)], "task": None}


def build_repair_task(report: dict, output: str | Path = ".runtime/repair-task.json") -> dict:
    """Legacy teaching mapper used by Loop/Graph; use map_repair_report for strict tasks."""
    failed = [r for r in report.get("results", []) if not r.get("passed") and r.get("level") == "blocking"]
    task = {
        "objective": "仅修复阻断级 Eval，保持现有公共接口和业务不变量",
        "scope": [r["name"] for r in failed],
        "evidence": [{"eval": r["name"], "reason": r["evidence"]} for r in failed],
        "reproduce": "python -X utf8 -m eval.harness --suite blocking",
        "acceptance": "阻断级失败为 0，退出码为 0",
        "forbidden": ["删除或跳过 Eval", "把 blocking 降级为 observing", "直接修改运行数据库", "提交密钥"],
    }
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    return task


def main(argv: list[str] | None = None) -> int:
    """Map a recorded report without executing, accepting, or overwriting a task."""
    parser = argparse.ArgumentParser(description="将真实 Eval 报告映射为有来源和明确写集的修复草案")
    parser.add_argument("report", type=Path)
    parser.add_argument("--source-task", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--allowed-file", action="append", required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--observed-exit", type=int, required=True)
    parser.add_argument("--suite", choices=("all", "blocking", "observing"), default="blocking")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # Refuse stale outputs even when the current report would produce no task.
        if args.output.exists():
            raise ValueError("输出已存在；请换新路径，保留旧证据")
        result = map_repair_report(
            args.report.read_bytes(), source_task=args.source_task,
            candidate=str(args.candidate.resolve()), cwd=str(args.candidate.resolve()),
            source_report=str(args.report.resolve()), source_version=args.source_version,
            objective=args.objective, allowed_files=args.allowed_file, required_cases=args.case,
            actual_exit=args.observed_exit, python_executable=args.python, expected_suite=args.suite,
        )
        if result["status"] == "repair_required":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result["task"], stream, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result["status"] == "invalid_report" else 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid_report", "task": None, "errors": [str(exc)]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
