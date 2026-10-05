from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol


class ShellProvider(Protocol):
    def exec(self, root: Path, command: list[str], *, timeout: int = 120) -> dict: ...


_ALLOWED_SHELL_PREFIXES = (
    [sys.executable, "-m", "unittest"],
    [sys.executable, "-m", "eval.harness"],
    [sys.executable, "-X", "utf8", "-m", "unittest"],
    [sys.executable, "-X", "utf8", "-m", "eval.harness"],
    ["git", "status"],
    ["git", "diff"],
    ["git", "log"],
)

_UNSAFE_GIT_OPTIONS = ("--output", "--ext-diff", "--textconv", "--no-index")


def normalize_command(command: list[str]) -> list[str]:
    return [str(part) for part in command]


def command_allowed(command: list[str]) -> bool:
    normalized = normalize_command(command)
    if len(normalized) >= 2 and normalized[:2] in (["git", "status"], ["git", "diff"], ["git", "log"]):
        for argument in normalized[2:]:
            option = argument.partition("=")[0]
            # Git accepts unique long-option abbreviations. Do not admit a
            # shortened spelling that can restore a file write or subprocess.
            if len(option) > 2 and option.startswith("--") and any(
                forbidden.startswith(option) for forbidden in _UNSAFE_GIT_OPTIONS
            ):
                return False
    for allowed in _ALLOWED_SHELL_PREFIXES:
        if len(normalized) >= len(allowed) and normalized[: len(allowed)] == allowed:
            return True
    return False


def execution_command(command: list[str]) -> list[str]:
    """Keep the approved request intact; pin diagnostic execution semantics."""
    normalized = normalize_command(command)
    if not normalized or not command_allowed(normalized):
        raise ValueError("命令不在 Harness 允许列表内")
    if normalized[:2] in (["git", "diff"], ["git", "log"]):
        return normalized[:2] + ["--no-ext-diff", "--no-textconv"] + normalized[2:]
    return normalized


class LocalShellProvider:
    """Local controlled shell provider for the shell capability seam."""

    def exec(self, root: Path, command: list[str], *, timeout: int = 120) -> dict:
        normalized = normalize_command(command)
        if not normalized:
            raise ValueError("command 不能为空")
        if not command_allowed(normalized):
            raise ValueError("命令不在 Harness 允许列表内")
        admitted = execution_command(normalized)
        timeout = min(int(timeout), 600)
        completed = subprocess.run(
            admitted,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": normalized,
            "executed_command": admitted,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "")[-20_000:],
            "stderr": (completed.stderr or "")[-10_000:],
            "provider": "local",
        }


class DenyShellProvider:
    """Swap-in shell provider that refuses every command (proves seam replaceability)."""

    def exec(self, root: Path, command: list[str], *, timeout: int = 120) -> dict:
        raise PermissionError("shell provider=deny：拒绝执行任何命令")
