"""Course verification must bind its checks to the current service's customer.

The tiny product fixtures run their checks in real Python subprocesses. Successful
fixtures reuse the test interpreter through ``python_for``; no business result is
mocked and no installed FlowERP checkout is required.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from workbench.task_store import TaskSubmissionConflict
from workbench.workbench_server import WorkbenchApp, make_handler


L12_CHECKS = {"purchase_requires_approval", "receiving_is_idempotent"}


class CourseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="course-verification-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = patch.dict(os.environ, {"FLOWERP_PROJECT_ROOT": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = WorkbenchApp(self.root / "current-service")

    def product(self, label="current-product", *, checks=L12_CHECKS, failure=None):
        root = self.root / label
        (root / ".git").mkdir(parents=True)
        (root / "flowerp").mkdir()
        (root / "flowerp/__init__.py").write_text("", encoding="utf-8")
        (root / "flowerp/server.py").write_text("", encoding="utf-8")
        (root / "eval").mkdir()
        source = []
        for name in sorted(checks):
            body = ("raise AssertionError('fixture-business-rule-failed')"
                    if name == failure else "return " + repr(label + ":" + name))
            source.append("def " + name + "():\n    " + body + "\n")
        (root / "eval/cases.py").write_text("\n".join(source), encoding="utf-8")
        return root

    def register(self, root, app=None):
        return (app or self.app).projects.create(root.name, root, [sys.executable, "-m", "eval.harness"])

    def fixture_python(self):
        return patch("workbench.external_project.python_for", return_value=sys.executable)

    def check_names(self, result):
        return {item if isinstance(item, str) else item["name"] for item in result["checks"]}

    def target_root(self, result):
        return Path(result["target"]["root_path"]).resolve()

    def test_missing_customer_is_explained_before_any_task_or_spec_is_created(self):
        readiness = self.app.course_verification(12)
        self.assertFalse(readiness["ready"])
        self.assertEqual(L12_CHECKS, self.check_names(readiness))
        self.assertTrue(readiness["message"])
        self.assertIn("projects", readiness)
        self.assertIn("limitations", readiness)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "FlowERP|客户|项目"):
                self.app.create_course_task(12, "复验现有成果", "student")
        self.assertEqual([], self.app.tasks.list())
        self.assertEqual([], list(self.app.runtime.glob("course/**/FDE_SPEC.md")))

    def test_http_prerequisites_explain_failure_and_reject_submission_without_a_task(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, body=None):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request(method, path, json.dumps(body) if body is not None else None,
                                   {"Content-Type": "application/json", "Idempotency-Key": "unready-request"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            code, readiness = request("GET", "/api/course/verification?lesson=12")
            self.assertEqual(200, code)
            self.assertFalse(readiness["ready"])
            self.assertEqual(L12_CHECKS, self.check_names(readiness))
            self.assertRegex(readiness["message"], "管理项目|登记|添加")
            for _ in range(2):
                code, response = request("POST", "/api/v1/delivery/requests",
                                         {"lesson": 12, "request": "核对采购规则", "actor": "student"})
                self.assertEqual(409, code)
                self.assertEqual("course_verification_not_ready", response["error"])
                self.assertRegex(response["message"], "FlowERP")
            self.assertEqual([], self.app.tasks.list())
            self.assertEqual([], list(self.app.runtime.glob("course/**/FDE_SPEC.md")))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_missing_product_environment_is_configuration_failure(self):
        project = self.register(self.product())
        readiness = self.app.course_verification(12, project_id=project["id"])
        self.assertFalse(readiness["ready"])
        self.assertRegex(readiness["message"], r"\.venv|虚拟环境|环境")
        with self.assertRaisesRegex(ValueError, r"\.venv|虚拟环境|环境"):
            self.app.create_course_task(12, "复验现有成果", "student", project_id=project["id"])
        self.assertEqual([], self.app.tasks.list())

    def test_missing_lesson_case_is_explained_before_submission(self):
        project = self.register(self.product(checks={"purchase_requires_approval"}))
        with self.fixture_python():
            readiness = self.app.course_verification(12, project_id=project["id"])
            self.assertFalse(readiness["ready"])
            self.assertIn("receiving_is_idempotent", readiness["message"])
            with self.assertRaisesRegex(ValueError, "receiving_is_idempotent"):
                self.app.create_course_task(12, "复验现有成果", "student", project_id=project["id"])
        self.assertEqual([], self.app.tasks.list())

    def test_multiple_customer_projects_require_an_explicit_target(self):
        first = self.register(self.product("first-product"))
        second = self.register(self.product("second-product"))
        with self.fixture_python():
            readiness = self.app.course_verification(12)
            self.assertFalse(readiness["ready"])
            self.assertEqual({first["id"], second["id"]}, {item["id"] for item in readiness["projects"]})
            selected = self.app.course_verification(12, project_id=second["id"])
            self.assertTrue(selected["ready"], selected["message"])
            self.assertEqual(Path(second["root_path"]), self.target_root(selected))
            invalid = self.app.course_verification(12, project_id="PROJECT-MISSING")
            self.assertFalse(invalid["ready"])
        self.assertEqual([], self.app.tasks.list())

    def test_verification_uses_current_service_registration_instead_of_another_runtime(self):
        current = self.register(self.product("current-product"))
        unrelated = WorkbenchApp(self.root / "unrelated-service")
        self.register(self.product("unrelated-product"), unrelated)
        with self.fixture_python(), \
                patch("workbench.runtime_paths.service_runtime", return_value=unrelated.runtime):
            ready = self.app.course_verification(12, project_id=current["id"])
            self.assertTrue(ready["ready"], ready["message"])
            created = self.app.create_course_task(12, "核对审批和幂等", "student", project_id=current["id"])
            result = self.app.verify_task(created["task_id"], "verifier")
        task = self.app.tasks.get(result["task_id"])
        self.assertEqual("review", task["status"], task.get("error"))
        self.assertEqual(0, task["result"]["summary"]["blocking_failed"])
        evidence = json.dumps(task["result"], ensure_ascii=False)
        self.assertIn("current-product:", evidence)
        self.assertNotIn("unrelated-product:", evidence)
        self.assertIsNone(task["reviewed_by"])

    def test_target_is_frozen_when_new_projects_or_environment_defaults_change(self):
        original = self.register(self.product("original-product"))
        with self.fixture_python():
            created = self.app.create_course_task(12, "复验原有成果", "student", project_id=original["id"])
            replacement = self.register(self.product("replacement-product"))
            self.app.projects.set_default(replacement["id"])
            with patch.dict(os.environ, {"FLOWERP_PROJECT_ROOT": replacement["root_path"]}):
                self.app.verify_task(created["task_id"], "verifier")
        task = self.app.tasks.get(created["task_id"])
        self.assertEqual("review", task["status"], task.get("error"))
        evidence = json.dumps(task["result"], ensure_ascii=False)
        self.assertIn("original-product:", evidence)
        self.assertNotIn("replacement-product:", evidence)
        recorded = json.dumps(task["events"], ensure_ascii=False)
        self.assertIn(original["id"], recorded)
        self.assertIn("original-product", recorded)

    def test_real_business_failure_is_preserved_as_a_blocking_result(self):
        project = self.register(self.product(failure="purchase_requires_approval"))
        with self.fixture_python():
            readiness = self.app.course_verification(12, project_id=project["id"])
            self.assertTrue(readiness["ready"], readiness["message"])
            created = self.app.create_course_task(12, "检查采购规则", "student", project_id=project["id"])
            self.app.verify_task(created["task_id"], "verifier")
        task = self.app.tasks.get(created["task_id"])
        self.assertEqual("rework", task["status"])
        self.assertEqual(1, task["result"]["summary"]["blocking_failed"])
        failed = [item for item in task["result"]["results"] if not item["passed"]]
        self.assertEqual(["purchase_requires_approval"], [item["name"] for item in failed])
        self.assertIn("fixture-business-rule-failed", failed[0]["evidence"])
        self.assertIsNone(task["reviewed_by"])

    def test_missing_dependency_is_reported_as_environment_failure_with_original_evidence(self):
        root = self.product()
        (root / "eval/cases.py").write_text(
            "def purchase_requires_approval():\n"
            "    import nonexistent_course_dependency\n\n"
            "def receiving_is_idempotent():\n"
            "    return 'fixture-idempotency-passed'\n",
            encoding="utf-8")
        project = self.register(root)
        with self.fixture_python():
            readiness = self.app.course_verification(12, project_id=project["id"])
            self.assertTrue(readiness["ready"], readiness["message"])
            created = self.app.create_course_task(12, "核对采购规则", "student", project_id=project["id"])
            view = self.app.verify_task(created["task_id"], "verifier")
        task = self.app.tasks.get(created["task_id"])
        self.assertEqual("rework", task["status"])
        self.assertEqual("block", task["result"]["summary"]["decision"])
        self.assertEqual(1, task["result"]["summary"]["blocking_failed"])
        failed = next(row for row in task["result"]["results"] if not row["passed"])
        self.assertEqual("ExternalProjectEnvironmentError", failed["error"]["type"])
        self.assertIn("ModuleNotFoundError: No module named 'nonexistent_course_dependency'", failed["evidence"])
        diagnostic = next(row for row in view["eval"]["diagnostics"]
                          if row["name"] == "purchase_requires_approval")
        self.assertEqual("environment", diagnostic["kind"])
        self.assertIn("nonexistent_course_dependency", diagnostic["message"])
        self.assertRegex(diagnostic["action"], "先核对.*环境")
        self.assertNotIn("修复本次代码", diagnostic["action"])
        self.assertIsNone(task["reviewed_by"])

    def test_same_submission_key_cannot_reuse_a_different_product_target(self):
        first = self.register(self.product("first-product"))
        second = self.register(self.product("second-product"))
        with self.fixture_python():
            original = self.app.create_course_task(12, "核对采购规则", "student",
                                                   submission_key="same-request", project_id=first["id"])
            replay = self.app.create_course_task(12, "核对采购规则", "student",
                                                 submission_key="same-request", project_id=first["id"])
            self.assertEqual(original["task_id"], replay["task_id"])
            with self.assertRaises(TaskSubmissionConflict):
                self.app.create_course_task(12, "核对采购规则", "student",
                                            submission_key="same-request", project_id=second["id"])
        self.assertEqual(1, len(self.app.tasks.list()))

    def test_http_rejects_stale_or_wrong_verification_key_without_creating_a_task(self):
        original = self.product("original-product")
        replacement = self.product("replacement-product")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, body=None):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request(method, path, json.dumps(body) if body is not None else None,
                                   {"Content-Type": "application/json", "Idempotency-Key": "checked-target"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            with self.fixture_python(), patch.dict(os.environ, {"FLOWERP_PROJECT_ROOT": str(original)}):
                code, readiness = request("GET", "/api/course/verification?lesson=12")
                self.assertEqual(200, code)
                self.assertTrue(readiness["ready"], readiness["message"])
                self.assertIsNone(readiness["target"]["project_id"])
                self.assertEqual(original.resolve(), self.target_root(readiness))
                for root, key in ((original, "wrong-key"), (replacement, readiness["verification_key"])):
                    with self.subTest(root=root.name), patch.dict(os.environ, {"FLOWERP_PROJECT_ROOT": str(root)}):
                        code, response = request("POST", "/api/v1/delivery/requests",
                                                 {"lesson": 12, "request": "核对采购规则", "actor": "student",
                                                  "verification_key": key})
                        self.assertEqual(409, code)
                        self.assertEqual("course_verification_not_ready", response["error"])
                        self.assertIn("变化", response["message"])
                self.assertEqual([], self.app.tasks.list())
                self.assertEqual([], list(self.app.runtime.glob("course/**/FDE_SPEC.md")))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_known_submission_receipt_replays_before_rechecking_a_broken_environment(self):
        project = self.register(self.product())
        with self.fixture_python():
            readiness = self.app.course_verification(12, project_id=project["id"])
            created = self.app.create_course_task(12, "核对采购规则", "student",
                                                  submission_key="known-receipt", project_id=project["id"],
                                                  verification_key=readiness["verification_key"])
        paths_before = set(self.app.runtime.glob("course/**/FDE_SPEC.md"))
        original_events = self.app.tasks.get(created["task_id"])["events"]
        with patch("workbench.external_project.python_for", side_effect=ValueError("fixture environment unavailable")) as python, \
                patch.object(self.app, "course_verification", side_effect=AssertionError("receipt replay must not precheck")):
            replay = self.app.create_course_task(12, "核对采购规则", "student",
                                                 submission_key="known-receipt", project_id=project["id"],
                                                 verification_key=readiness["verification_key"])
            python.assert_not_called()
        self.assertEqual(created["task_id"], replay["task_id"])
        self.assertEqual(1, len(self.app.tasks.list()))
        self.assertEqual(paths_before, set(self.app.runtime.glob("course/**/FDE_SPEC.md")))
        self.assertEqual(original_events, self.app.tasks.get(created["task_id"])["events"])

    def test_parallel_verifications_keep_each_tasks_product_scope(self):
        projects = [self.register(self.product(label)) for label in ("first-product", "second-product")]
        with self.fixture_python():
            tasks = [self.app.create_course_task(12, "检查采购规则", "student", project_id=project["id"])
                     for project in projects]
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda item: self.app.verify_task(item["task_id"], "verifier"), tasks))
        for index, item in enumerate(tasks):
            task = self.app.tasks.get(item["task_id"])
            self.assertEqual("review", task["status"], task.get("error"))
            evidence = json.dumps(task["result"], ensure_ascii=False)
            self.assertIn(Path(projects[index]["root_path"]).name + ":", evidence)
            self.assertNotIn(Path(projects[1 - index]["root_path"]).name + ":", evidence)


if __name__ == "__main__":
    unittest.main()
