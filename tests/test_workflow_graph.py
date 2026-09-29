from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workbench.task_store import TaskStore
from workbench.workflow_graph import WorkflowConflict, WorkflowGraph


PASS_REPORT = {
    "summary": {"decision": "pass", "blocking_failed": 0, "blocking_passed": 1},
    "results": [{"name": "gate", "level": "blocking", "passed": True}],
}


class WorkflowGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks = TaskStore(Path(self.tmp.name) / "workbench.db")
        self.graphs = WorkflowGraph(self.tasks)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def review_task(self, *, l12: bool = False) -> tuple[str, dict]:
        task = self.tasks.create(
            "deliver", requirement_id="REQ-COURSE-L12" if l12 else "REQ-TEST",
            business_refs=["PURCHASE:TEST"] if l12 else [], actor="builder",
        )
        self.tasks.transition(task["id"], "spec_ready", actor="builder")
        self.tasks.transition(task["id"], "executing", actor="builder")
        self.tasks.transition(task["id"], "evaluating", actor="reviewer")
        self.tasks.transition(task["id"], "review", actor="reviewer", result=PASS_REPORT)
        graph = self.graphs.ensure(task["id"])
        graph = self.graphs.bind_candidate(task["id"], "abc123")
        return task["id"], graph

    def test_migrates_without_inventing_history_and_lists_nodes(self) -> None:
        task_id, graph = self.review_task()
        self.assertTrue(graph["migrated"])
        self.assertEqual("awaiting_software_review", graph["current"])
        self.assertEqual(["decide"], graph["allowed_actions"])
        self.assertIn("未补造历史边", graph["events"][0]["reason"])
        self.assertTrue(any(node["id"] == "completed" for node in graph["nodes"]))

    def test_software_approval_is_version_bound_and_idempotent(self) -> None:
        task_id, graph = self.review_task()
        kwargs = dict(
            decision_type="software_review", decision="approve", actor="boss-a",
            role="human:reviewer", reason="Spec、Diff 与 Eval 一致",
            expected_version=graph["version"], candidate_revision=graph["candidate"]["revision"],
            candidate_sha256="abc123", key="approve-1",
        )
        completed = self.graphs.decide(task_id, **kwargs)
        replay = self.graphs.decide(task_id, **kwargs)
        self.assertEqual("completed", completed["current"])
        self.assertEqual(completed["version"], replay["version"])
        self.assertEqual("completed", self.tasks.get(task_id)["status"])
        self.assertEqual("boss-a", self.tasks.get(task_id)["reviewed_by"])
        with self.assertRaises(WorkflowConflict):
            self.graphs.decide(task_id, **{**kwargs, "reason": "different"})

    def test_l12_separates_software_and_purchase_decisions(self) -> None:
        task_id, graph = self.review_task(l12=True)
        waiting = self.graphs.decide(
            task_id, decision_type="software_review", decision="approve", actor="qa-a",
            role="human:reviewer", reason="软件证据通过", expected_version=graph["version"],
            candidate_revision=graph["candidate"]["revision"], candidate_sha256="abc123", key="software-1",
        )
        self.assertEqual("awaiting_purchase_approval", waiting["current"])
        self.assertEqual("review", self.tasks.get(task_id)["status"])
        rejected = self.graphs.decide(
            task_id, decision_type="purchase_approval", decision="reject", actor="buyer-a",
            role="human:purchase_approver", reason="预算未批准", expected_version=waiting["version"],
            candidate_revision=waiting["candidate"]["revision"], candidate_sha256="abc123",
            target_ref="PURCHASE:TEST", key="purchase-1",
        )
        self.assertEqual("business_rejected", rejected["current"])
        self.assertEqual(["software_review", "purchase_approval"],
                         [item["decision_type"] for item in rejected["decisions"]])

    def test_l12_registered_effect_is_idempotent_and_reconciled_before_completion(self) -> None:
        task_id, graph = self.review_task(l12=True)
        waiting = self.graphs.decide(
            task_id, decision_type="software_review", decision="approve", actor="qa-a",
            role="human:reviewer", reason="软件证据通过", expected_version=graph["version"],
            candidate_revision=graph["candidate"]["revision"], candidate_sha256="abc123", key="software-effect",
        )
        receiving = self.graphs.decide(
            task_id, decision_type="purchase_approval", decision="approve", actor="buyer-a",
            role="human:purchase_approver", reason="批准收货", expected_version=waiting["version"],
            candidate_revision=waiting["candidate"]["revision"], candidate_sha256="abc123",
            target_ref="PURCHASE:TEST", key="purchase-effect",
        )
        request = {"purchase_ref": "PURCHASE:TEST", "idempotency_key": "receipt-1"}
        first = self.graphs.begin_effect(
            task_id, handler="flowerp.receive_purchase", business_ref="PURCHASE:TEST",
            request=request, idempotency_key="receipt-1", expected_version=receiving["version"])
        replay = self.graphs.begin_effect(
            task_id, handler="flowerp.receive_purchase", business_ref="PURCHASE:TEST",
            request=request, idempotency_key="receipt-1", expected_version=receiving["version"])
        self.assertEqual(first["request_sha256"], replay["request_sha256"])
        reconciling = self.graphs.finish_effect(task_id, idempotency_key="receipt-1",
                                                result={"on_hand": 17, "allocated": 2, "available": 15,
                                                        "receipt_count": 1})
        self.assertEqual("reconciling", reconciling["current"])
        completed = self.graphs.reconcile(
            task_id, actor="auditor-a", evidence={"matched": True, "on_hand": 17,
                                                   "available": 15, "receipt_count": 1},
            expected_version=reconciling["version"], key="reconcile-1")
        self.assertEqual("completed", completed["current"])

    def test_candidate_change_invalidates_old_decision_and_stale_version(self) -> None:
        task_id, graph = self.review_task(l12=True)
        waiting = self.graphs.decide(
            task_id, decision_type="software_review", decision="approve", actor="qa-a",
            role="human:reviewer", reason="通过", expected_version=graph["version"],
            candidate_revision=graph["candidate"]["revision"], candidate_sha256="abc123", key="software-2",
        )
        changed = self.graphs.bind_candidate(task_id, "def456")
        self.assertEqual(1, changed["decisions"][0]["stale"])
        with self.assertRaises(WorkflowConflict):
            self.graphs.decide(
                task_id, decision_type="purchase_approval", decision="approve", actor="buyer-a",
                role="human:purchase_approver", reason="批准", expected_version=waiting["version"],
                candidate_revision=waiting["candidate"]["revision"], candidate_sha256="abc123",
                target_ref="PURCHASE:TEST", key="purchase-stale",
            )

    def test_handler_registry_has_no_command_surface(self) -> None:
        handlers = self.graphs.handlers()
        self.assertEqual({"flowerp.purchase_approval", "flowerp.receive_purchase"},
                         {item["name"] for item in handlers})
        self.assertTrue(all("command" not in item and "shell" not in item for item in handlers))

    def test_safe_advance_stops_at_execution_authorization(self) -> None:
        task = self.tasks.create("deliver", actor="builder")
        graph = self.graphs.ensure(task["id"])
        spec = self.graphs.advance(task["id"], actor="builder", expected_version=graph["version"], key="advance-1")
        waiting = self.graphs.advance(task["id"], actor="builder", expected_version=spec["version"], key="advance-2")
        self.assertEqual("awaiting_execution_authorization", waiting["current"])
        self.assertEqual(["authorize"], waiting["allowed_actions"])


if __name__ == "__main__":
    unittest.main()
