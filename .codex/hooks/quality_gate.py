from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def main() -> int:
    # Installed location: <project>/.codex/hooks/quality_gate.py
    root = Path(__file__).resolve().parents[2]
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("hook_event_name") != "Stop":
            raise ValueError("expected a Stop event object")
        cwd = Path(event["cwd"]).resolve(strict=True)
        if cwd != root and root not in cwd.parents:
            raise ValueError("event cwd is outside this project")
        if event.get("stop_hook_active"):
            print(json.dumps({"continue": True, "systemMessage": "重入跳过；本次未复验。结束前仍须显式运行阻断级 Eval。"}, ensure_ascii=False))
            return 0
        python = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        result = subprocess.run(
            [str(python), "-X", "utf8", "-m", "eval.harness", "--suite", "blocking"],
            cwd=root, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False, timeout=100,
        )
        if result.returncode == 0:
            response = {"continue": True, "systemMessage": "当前工作台阻断级 Eval 已通过；不代表 FlowERP 业务验收。"}
        else:
            tail = "\n".join((result.stdout + result.stderr).splitlines()[-10:])
            response = {"decision": "block", "reason": "阻断级 Eval 未通过。修复后显式复验：\n" + tail}
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        print(detail, file=sys.stderr)
        response = {"decision": "block", "reason": "Hook 未完成验证，请修复环境或配置后显式复验：" + detail}
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
