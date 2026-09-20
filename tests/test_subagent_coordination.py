from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workbench.subagent_coordination import SubagentCoordinator


class SubagentCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.manifest = self.root / "manifest.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_manifest(self, *, shared_resource: bool = False) -> None:
        self.manifest.write_text(json.dumps({
            "task_id": "TASK-L11",
            "candidate_path": str(self.candidate),
            "input_version": "sha256:fixed-v1",
            "subtasks": [
                {"name": "tests", "prompt": "补测试", "read_set": ["flowerp/service.py"],
                 "write_set": ["tests/test_l11.py"], "resource_set": ["report:shared"] if shared_resource else ["report:tests"]},
                {"name": "risk", "prompt": "只读查风险", "read_set": ["flowerp/service.py"],
                 "write_set": [], "resource_set": ["report:shared"] if shared_resource else ["report:risk"]},
            ],
        }), encoding="utf-8")

    def test_create_persists_frozen_parallel_plan(self) -> None:
        self._write_manifest()
        plan = SubagentCoordinator(self.root / "runtime").create(self.manifest)
        self.assertTrue(plan["parallel_decision"]["parallel"])
        self.assertEqual("sha256:fixed-v1", plan["input_version"])
        self.assertFalse(plan["native_execution"])

    def test_shared_resource_is_rejected(self) -> None:
        self._write_manifest(shared_resource=True)
        with self.assertRaises(ValueError):
            SubagentCoordinator(self.root / "runtime").create(self.manifest)

    def test_finalize_requires_evidence_and_overlapping_activity(self) -> None:
        self._write_manifest()
        coordinator = SubagentCoordinator(self.root / "runtime")
        plan = coordinator.create(self.manifest)
        evidence = self.root / "result.txt"
        evidence.write_text("real output", encoding="utf-8")
        coordinator.record(plan["id"], "tests", "running", "agent-tests")
        coordinator.record(plan["id"], "risk", "running", "agent-risk")
        coordinator.record(plan["id"], "tests", "completed", "agent-tests", (str(evidence),))
        coordinator.record(plan["id"], "risk", "completed", "agent-risk", (str(evidence),))
        final = coordinator.finalize(plan["id"], "main-agent")
        self.assertEqual("ready_for_serial_integration", final["status"])


if __name__ == "__main__":
    unittest.main()
