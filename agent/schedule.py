from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Subtask:
    name: str
    write_set: tuple[str, ...]
    read_set: tuple[str, ...] = ()
    resource_set: tuple[str, ...] = ()
    input_version: str = ""


def _scope(value: str) -> str:
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if not value.strip() or path.is_absolute() or any(part == ".." for part in path.parts) or any(char in value for char in ":*?[]"):
        raise ValueError("读写集必须是明确的仓库相对文件或目录")
    # Case-insensitive comparison is conservative and portable across classroom
    # Windows and macOS machines; differently cased paths are not independent.
    return path.as_posix().rstrip("/").casefold()


def _overlap(left: str, right: str) -> bool:
    return left == right or left == "." or right == "." or left.startswith(right + "/") or right.startswith(left + "/")


def _resource(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or any(char.isspace() for char in normalized):
        raise ValueError("共享资源名称必须是非空且不含空白的标识")
    return normalized


def conflict_pairs(tasks: list[Subtask] | tuple[Subtask, ...]) -> list[tuple[str, str, list[str]]]:
    conflicts: list[tuple[str, str, list[str]]] = []
    items = list(tasks)
    names = [item.name.strip() for item in items]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("子任务名称必须非空且唯一")
    scopes = {item.name: (tuple(_scope(p) for p in item.write_set), tuple(_scope(p) for p in item.read_set)) for item in items}
    resources = {
        item.name: tuple(_resource(value) for value in item.resource_set)
        for item in items
    }
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            left_writes, left_reads = scopes[left.name]
            right_writes, right_reads = scopes[right.name]
            shared = set()
            for writes, other in ((left_writes, right_writes + right_reads), (right_writes, left_reads)):
                for a in writes:
                    for b in other:
                        if _overlap(a, b):
                            shared.add(max((a, b), key=lambda path: len(PurePosixPath(path).parts)))
            if shared:
                conflicts.append((left.name, right.name, sorted(shared)))
            shared_resources = sorted(set(resources[left.name]) & set(resources[right.name]))
            if shared_resources:
                conflicts.append((
                    left.name,
                    right.name,
                    [f"resource:{value}" for value in shared_resources],
                ))
    return conflicts


def assert_parallel_safe(tasks: list[Subtask] | tuple[Subtask, ...]) -> dict:
    items = list(tasks)
    versions = {item.input_version.strip() for item in items if item.input_version.strip()}
    if len(versions) > 1:
        raise ValueError("并行子任务必须使用同一个固定输入版本")
    conflicts = conflict_pairs(items)
    if conflicts:
        raise ValueError(
            "共享写集或读写依赖不得并行：" + "; ".join(f"{a}×{b}→{','.join(files)}" for a, b, files in conflicts)
        )
    return {
        "parallel": True,
        "tasks": [item.name for item in items],
        "conflicts": [],
        "input_version": next(iter(versions), ""),
    }
