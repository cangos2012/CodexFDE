"""L15 可解释 Memory/RAG 教学实验，只使用 Python 标准库。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


DEFAULT_FIXTURE = Path(__file__).with_name("memory_rag_fixture.json")


def terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    ascii_terms = set(re.findall(r"[a-z0-9_]+", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    grams = {chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))}
    return ascii_terms | grams


def score(query: str, memory: dict) -> float:
    query_terms = terms(query)
    searchable = " ".join(
        [
            memory["title"],
            memory["content"],
            memory["applies_when"],
            " ".join(memory["tags"]),
        ]
    )
    memory_terms = terms(searchable)
    if not query_terms or not memory_terms:
        return 0.0
    overlap = len(query_terms & memory_terms)
    return round(overlap / len(query_terms), 4)


def retrieve(
    memories: list[dict],
    query: str,
    project: str,
    top_k: int,
    *,
    include_revoked: bool = False,
    minimum_score: float = 0.08,
) -> list[dict]:
    candidates = []
    for memory in memories:
        if memory["project"] != project:
            continue
        if not include_revoked and memory["status"] != "active":
            continue
        value = score(query, memory)
        if value < minimum_score:
            continue
        candidates.append({"score": value, **memory})
    candidates.sort(key=lambda item: (-item["score"], item["memory_id"], -item["version"]))
    return candidates[:top_k]


def context_pack(query: str, project: str, results: list[dict]) -> dict:
    citations = [f'{item["memory_id"]}@v{item["version"]}' for item in results]
    payload = {
        "schema": "codexfde.l15.rag-context/v1",
        "query": query,
        "filters": {"project": project, "status": "active"},
        "retrieved": [
            {
                "memory_ref": citations[index],
                "score": item["score"],
                "content": item["content"],
                "applies_when": item["applies_when"],
                "not_when": item["not_when"],
                "source": item["source"],
            }
            for index, item in enumerate(results)
        ],
        "generation_contract": {
            "required_citations": citations,
            "rule": "关键建议引用 memory_ref；没有支持时明确写未找到可用记忆；采用由人决定。",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload["snapshot_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def evaluate(fixture: dict, top_k: int) -> tuple[dict, bool]:
    cases = []
    passed = True
    for query_case in fixture["queries"]:
        results = retrieve(
            fixture["memories"],
            query_case["query"],
            query_case["project"],
            top_k,
        )
        returned = [item["memory_id"] for item in results]
        relevant = set(query_case["relevant"])
        matched = relevant & set(returned)
        precision = round(len(matched) / top_k, 4) if top_k else 0.0
        recall = round(len(matched) / len(relevant), 4) if relevant else None
        no_answer_ok = bool(relevant) or not returned
        invalid = [
            item["memory_id"]
            for item in results
            if item["project"] != query_case["project"] or item["status"] != "active"
        ]
        case_ok = (recall == 1.0 if relevant else no_answer_ok) and not invalid
        passed = passed and case_ok
        cases.append(
            {
                "query_id": query_case["query_id"],
                "returned": returned,
                "relevant": sorted(relevant),
                "precision_at_k": precision,
                "recall_at_k": recall,
                "no_answer_ok": no_answer_ok,
                "invalid_leakage": invalid,
                "passed": case_ok,
            }
        )
    report = {
        "schema": "codexfde.l15.rag-eval/v1",
        "top_k": top_k,
        "cases": cases,
        "decision": "pass" if passed else "fail",
        "boundary": "只证明固定教学语料与查询集下的检索合同，不证明生产 RAG 或答案事实正确。",
    }
    return report, passed


def load_fixture(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "codexfde.l15.memory-fixture/v1":
        raise ValueError("不支持的教学记忆集 schema")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="L15 Memory/RAG 教学实验")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--query")
    parser.add_argument("--project", default="FlowERP")
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--include-revoked", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k 必须大于 0")
    fixture = load_fixture(args.fixture)
    if args.evaluate:
        output, passed = evaluate(fixture, args.top_k)
    else:
        if not args.query:
            parser.error("查询模式必须提供 --query，或改用 --evaluate")
        results = retrieve(
            fixture["memories"],
            args.query,
            args.project,
            args.top_k,
            include_revoked=args.include_revoked,
        )
        output = context_pack(args.query, args.project, results)
        output["diagnostic"] = {
            "include_revoked": args.include_revoked,
            "warning": "反例开关允许撤回条目进入候选，只用于观察治理缺失。"
            if args.include_revoked
            else None,
        }
        passed = not any(item["status"] != "active" for item in results)
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.out:
        if args.out.exists():
            raise FileExistsError(f"拒绝覆盖已有输出：{args.out}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(args.out)
    else:
        print(rendered)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
