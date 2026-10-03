#!/usr/bin/env python3
"""Sync course task cards and detailed lesson headers to the outline contract."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Inline the same extractor used by tests to avoid importing unittest modules slowly.
CONTRACT_LABELS = {
    "核心内容",
    "演示结果",
    "课内增量",
    "通过标准",
    "挑战任务",
    "验收命令",
    "最终验收命令",
}
MANUAL_CONTRACT_LABELS = ("核心内容", "演示结果", "课内增量", "通过标准")


def outline_contracts() -> dict[int, tuple[str, list[str]]]:
    text = (ROOT / "docs" / "课程大纲-Codex-FDE行动营-个人研发自动化工作台.md").read_text(encoding="utf-8")
    matches = list(re.finditer(r"^#### 第 (\d+) 讲｜(.+)$", text, re.MULTILINE))
    contracts: dict[int, tuple[str, list[str]]] = {}
    for index, match in enumerate(matches):
        lesson = int(match.group(1))
        if not 1 <= lesson <= 16:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.end() : end]
        lines = []
        for line in section.splitlines():
            field = re.match(r"^- \*\*(.+?)\*\*：", line)
            if field and field.group(1) in CONTRACT_LABELS:
                lines.append(line)
        contracts[lesson] = (match.group(2), lines)
    return contracts


def replace_header(body: str, title_line: str, contract_lines: list[str]) -> str:
    lines = body.splitlines()
    if not lines:
        return title_line + "\n\n" + "\n".join(contract_lines) + "\n"
    lines[0] = title_line
    # Drop leading contract bullets immediately after title (and blank lines among them).
    i = 1
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith("- **")):
        # Stop if we hit a non-contract bullet that isn't a known label
        if lines[i].startswith("- **"):
            field = re.match(r"^- \*\*(.+?)\*\*：", lines[i])
            if not field or field.group(1) not in CONTRACT_LABELS:
                break
        i += 1
    # Skip one blank after contracts if present
    rest = lines[i:]
    while rest and not rest[0].strip():
        rest = rest[1:]
    return "\n".join([title_line, ""] + contract_lines + [""] + rest) + ("\n" if body.endswith("\n") else "")


def replace_manual_contract(body: str, contract_lines: list[str]) -> str:
    """Update the four adopted contract bullets without moving learner prose."""
    field_pattern = re.compile(r"^- \*\*(核心内容|演示结果|课内增量|通过标准)\*\*：")
    replacements: dict[str, str] = {}
    for line in contract_lines:
        field = field_pattern.match(line)
        if not field:
            continue
        label = field.group(1)
        if label in replacements:
            raise ValueError(f"课程大纲合同重复：{label}")
        replacements[label] = line
    missing_source = [label for label in MANUAL_CONTRACT_LABELS if label not in replacements]
    if missing_source:
        raise ValueError(f"课程大纲合同缺项：{', '.join(missing_source)}")

    lines = body.splitlines(keepends=True)
    positions: dict[str, list[int]] = {label: [] for label in MANUAL_CONTRACT_LABELS}
    fence_character = ""
    fence_length = 0
    for index, line in enumerate(lines):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence_character:
            if (fence and fence.group(1)[0] == fence_character
                    and len(fence.group(1)) >= fence_length and not fence.group(2).strip()):
                fence_character = ""
            continue
        if fence:
            fence_character, fence_length = fence.group(1)[0], len(fence.group(1))
            continue
        field = field_pattern.match(line)
        if field:
            positions[field.group(1)].append(index)

    missing = [label for label, indexes in positions.items() if not indexes]
    duplicates = [f"{label}（行 {', '.join(str(index + 1) for index in indexes)}）"
                  for label, indexes in positions.items() if len(indexes) > 1]
    if missing or duplicates:
        details = []
        if missing:
            details.append(f"缺项：{', '.join(missing)}")
        if duplicates:
            details.append(f"重复：{'; '.join(duplicates)}")
        raise ValueError(f"实践手册正式合同{'；'.join(details)}；先确认正式合同位置，不自动补写")

    for label, indexes in positions.items():
        index = indexes[0]
        ending = lines[index][len(lines[index].rstrip("\r\n")):]
        lines[index] = replacements[label] + ending
    return "".join(lines)


def ensure_task_mainline(body: str) -> str:
    if "FlowERP 现场问题" in body:
        return body
    needle = "## 项目主线与评价证据"
    if needle not in body:
        # Insert after contract block
        parts = body.split("\n\n", 1)
        block = (
            f"{needle}\n\n"
            "- **FlowERP 现场问题**：本讲由 FlowERP 真实交付暴露可重复工程问题。\n"
            "- **工作台增量**：见本讲课内增量。\n"
            "- **学生学习证据**：首次判断、失败证据、修订与同伴复验。\n"
            "- **形成性评价**：保留修订前后版本与反馈。\n"
        )
        return parts[0] + "\n\n" + block + ("\n" + parts[1] if len(parts) > 1 else "")
    # Insert marker into existing section
    return body.replace(
        needle,
        needle
        + "\n\n"
        + "- **FlowERP 现场问题**：本讲由 FlowERP 真实交付暴露可重复工程问题，用于触发工作台能力验证。",
        1,
    )


def main() -> None:
    contracts = outline_contracts()
    for relative in (Path("docs/courses"), Path("docs/courses/tasks")):
        directory = ROOT / relative
        paths = [path for path in sorted(directory.glob("L??-*.md")) if not path.name.endswith("-教师备课说明.md")]
        for number in range(1, 17):
            path = ROOT / f"docs/courses/L{number:02d}" / ("行动卡.md" if directory.name == "tasks" else "辅导资料.md")
            if directory.name == "tasks" and not path.is_file():
                path = path.with_name("实践操作手册.md")
            if path.is_file():
                paths.append(path)
        for path in paths:
            match = re.fullmatch(r'L(\d{2})', path.parent.name) or re.match(r'L(\d{2})-', path.name)
            if not match:
                continue
            lesson = int(match.group(1))
            if lesson not in contracts:
                continue
            title, contract_lines = contracts[lesson]
            title_line = f"# L{lesson:02d}｜{title}"
            body = path.read_text(encoding="utf-8")
            if path.name == "实践操作手册.md":
                try:
                    updated = replace_manual_contract(body, contract_lines)
                except ValueError as error:
                    raise ValueError(f"{path.relative_to(ROOT)}：{error}") from error
            else:
                updated = replace_header(body, title_line, contract_lines)
            if relative.as_posix() == "docs/courses/tasks" and path.name != "实践操作手册.md":
                updated = ensure_task_mainline(updated)
            if updated != body:
                path.write_text(updated, encoding="utf-8")
                print(f"updated {path.relative_to(ROOT)}")
            else:
                print(f"ok {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
