"""Keep manual contracts in place when action cards have been merged into them."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_outline_contracts as sync


class ManualContractSyncTests(unittest.TestCase):
    labels = ("核心内容", "演示结果", "课内增量", "通过标准")
    old_contract = "\n".join(f"- **{label}**：旧{label}" for label in labels)
    new_lines = [f"- **{label}**：新{label}" for label in labels]
    opening = "# L09｜保留现有标题\n\n**实践操作手册**\n\n## 本讲目标\n\n先完成自己的建设。\n\n"
    tail = "\n\n## 1 个人任务\n\n按原操作链继续。\n"

    def test_main_updates_contract_after_goal_in_place_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manual = root / "docs/courses/L09/实践操作手册.md"
            manual.parent.mkdir(parents=True)
            original = self.opening + self.old_contract + self.tail
            manual.write_text(original, encoding="utf-8")
            contracts = {9: ("大纲标题不能覆盖手册开头", self.new_lines + ["- **挑战任务**：额外字段"])}
            with patch.object(sync, "ROOT", root), patch.object(sync, "outline_contracts", return_value=contracts), \
                    contextlib.redirect_stdout(io.StringIO()):
                sync.main()
                first = manual.read_text(encoding="utf-8")
                self.assertEqual(self.opening + "\n".join(self.new_lines) + self.tail, first)
                sync.main()
                self.assertEqual(first, manual.read_text(encoding="utf-8"))

    def test_fenced_examples_are_ignored_and_preserved(self):
        for fence in ("````markdown", "~~~markdown"):
            with self.subTest(fence=fence):
                closing = "````" if fence.startswith("`") else "~~~"
                example = fence + "\n" + self.old_contract + "\n" + closing + "\n\n"
                original = self.opening + example + self.old_contract + self.tail
                updated = sync.replace_manual_contract(original, self.new_lines)
                self.assertEqual(self.opening + example + "\n".join(self.new_lines) + self.tail, updated)
                self.assertEqual(updated, sync.replace_manual_contract(updated, self.new_lines))
                # A fenced example alone must not substitute for the adopted contract.
                with self.assertRaisesRegex(ValueError, "缺项"):
                    sync.replace_manual_contract(self.opening + example + self.tail, self.new_lines)

    def test_missing_or_duplicate_formal_contract_is_reported_without_writing(self):
        invalid = {
            "缺项": "\n".join(self.old_contract.splitlines()[:-1]),
            "重复": self.old_contract + "\n- **核心内容**：第二份来源未确认",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manual = root / "docs/courses/L09/实践操作手册.md"
            manual.parent.mkdir(parents=True)
            for message, contract in invalid.items():
                with self.subTest(message=message):
                    original = self.opening + contract + self.tail
                    manual.write_text(original, encoding="utf-8")
                    with patch.object(sync, "ROOT", root), \
                            patch.object(sync, "outline_contracts", return_value={9: ("标题", self.new_lines)}), \
                            self.assertRaisesRegex(ValueError, rf"L09.*{message}"):
                        sync.main()
                    self.assertEqual(original, manual.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
