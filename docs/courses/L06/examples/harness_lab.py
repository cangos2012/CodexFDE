"""L06 controlled experiments: exercise the real Harness, never edit its registry on disk."""
from __future__ import annotations

import argparse
import csv
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from workbench.course_experiments import ensure_product_process
ensure_product_process(__file__)
from eval import harness
from flowerp import ERPService, ERPStore
from flowerp.models import InsufficientStock, OrderLine


def stock_agrees() -> str:
    with tempfile.TemporaryDirectory(prefix="l06-stock-") as directory:
        service = ERPService(ERPStore(Path(directory) / "stock.db"))
        service.add_product("L06-A", "口径实验商品", 1000, 2)
        service.receive_stock("L06-A", 8, "l06-open")
        order = service.create_order("课堂夹具", [OrderLine("L06-A", 3, 1000)], "L06-ORDER")
        service.reserve_order(order["id"])
        stock = service.product("L06-A")
        assert (stock["on_hand"], stock["reserved"], stock["available"]) == (8, 3, 5), stock
        rows = list(csv.DictReader(io.StringIO(service.export_inventory().lstrip("\ufeff"))))
        exported = [row for row in rows if row["sku"] == "L06-A"]
        assert len(exported) == 1, exported
        assert tuple(int(exported[0][key]) for key in ("on_hand", "reserved", "available")) == (8, 3, 5), exported
        before = {key: stock[key] for key in ("on_hand", "reserved", "available")}
        excessive = service.create_order("课堂夹具", [OrderLine("L06-A", 6, 1000)], "L06-EXCESS")
        try:
            service.reserve_order(excessive["id"])
        except InsufficientStock:
            pass
        else:
            raise AssertionError("AC-REJECT: 可用 5，预占 6 应拒绝")
        after = service.product("L06-A")
        assert {key: after[key] for key in before} == before, after
        return "真实临时库：查询与 CSV 均为 8/3/5；预占 6 被拒绝，三项数量不变"


def deliberately_fail() -> str:
    raise AssertionError("教学夹具：期望 available=5，故意提供 actual=8；不是产品事故")


def crash() -> str:
    raise RuntimeError("教学夹具：检查依赖不可用，业务结果未知")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("pass", "blocking", "observing", "error", "unknown", "empty", "wrong-suite", "write-error"))
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args()
    entries = [("stock_agrees", "blocking", stock_agrees)]
    if args.scenario in {"blocking", "observing"}:
        entries.append(("controlled_failure", args.scenario, deliberately_fail))
    elif args.scenario == "error":
        entries.insert(0, ("controlled_error", "blocking", crash))
    elif args.scenario == "empty":
        entries = []
    elif args.scenario == "wrong-suite":
        entries.append(("observation", "observing", deliberately_fail))
    argv = ["harness", "--suite", "all", "--report-path", args.report_path]
    if args.scenario == "unknown":
        argv.extend(["--case", "not_registered"])
    elif args.scenario == "wrong-suite":
        argv[2] = "blocking"
        argv.extend(["--case", "observation"])
    # Patching is process-local and demonstrates Harness behavior, not student implementation.
    with patch.object(harness, "EVALS", entries), patch.object(sys, "argv", argv):
        if args.scenario == "write-error":
            with tempfile.TemporaryDirectory(prefix="l06-report-") as directory:
                blocker = Path(directory) / "ordinary-file"
                blocker.write_text("This is a file, not a directory.", encoding="utf-8")
                argv[-1] = str(blocker / "report.json")
                return harness.main()
        return harness.main()


if __name__ == "__main__":
    raise SystemExit(main())
