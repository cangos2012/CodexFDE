import concurrent.futures
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from workbench.initiative import InitiativeStore, InitiativeSubmissionConflict
from workbench.initiative_home import InitiativeHome
from workbench.task_store import TaskStore


class InitiativeHomeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "workbench.db"
        self.tasks = TaskStore(self.path)
        self.store = InitiativeStore(self.path)
        self.home = InitiativeHome(self.path)
        with self.store.connect() as db:
            db.execute("CREATE TABLE initiative_workflows(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            db.execute("CREATE TABLE harness_projects(id TEXT PRIMARY KEY,name TEXT NOT NULL)")
            db.executemany("INSERT INTO harness_projects VALUES(?,?)", [("P1", "甲项目"), ("P2", "乙项目")])

    def add(self, title="事项", project="P1", stage="idle", hidden=False, **work):
        item = self.store.create({"title": title, "raw_signal": "客服原始需求", "source": "test",
                                  "project_id": project}, "tester")
        with self.store.connect() as db:
            db.execute("UPDATE initiatives SET home_hidden=?,updated_at='2026-10-01 10:00:00' WHERE id=?",
                       (int(hidden), item["id"]))
            db.execute("INSERT INTO initiative_workflows VALUES(?,?)", (item["id"], json.dumps({
                "stage": stage, "revision": 2, "proposal": {"goal": "已保存的目标"}, **work})))
        return item

    def test_more_than_100_items_are_reachable_and_counts_cover_all_matches(self):
        ids = {self.add(f"项目需求 {index}")["id"] for index in range(121)}
        self.add("其他项目的发布", project="P2", stage="released", current_release="release-1")
        first = self.home.page(project_id="P1", group="attention")
        self.assertEqual(20, len(first["items"]))
        self.assertEqual(121, first["counts"]["attention"])
        self.assertEqual(121, first["total"])
        found, cursor = [], ""
        while True:
            page = self.home.page(project_id="P1", group="attention", cursor=cursor)
            found.extend(row["item"]["id"] for row in page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(121, len(found))
        self.assertEqual(ids, set(found))
        self.assertEqual(121, len(set(found)))

    def test_project_search_and_visibility_are_server_filters_with_full_statistics(self):
        self.add("待讨论 100%_改善")
        self.add("执行进度", stage="executing", hidden=True)
        self.add("已回收结果", stage="observed", current_release="release-1")
        self.add("已清除", hidden=True)
        self.add("[Mock课程演示] 交付", stage="observed", current_release="mock-release")
        self.add("其他项目", project="P2")
        page = self.home.page(project_id="P1", group="attention")
        self.assertEqual({"attention": 1, "running": 1, "outcome": 1, "unknown": 0}, page["counts"])
        self.assertEqual(1, page["total"])
        self.assertEqual(3, page["matching_total"])
        self.assertEqual({"released": 1, "observed": 1}, page["outcomes"])
        self.assertTrue(page["has_mock"])
        self.assertEqual("甲项目", page["items"][0]["work"]["project"]["name"])
        self.assertEqual(5, self.home.page(project_id="P1", include_mock=True, include_hidden=True)["total"])
        self.assertEqual(1, self.home.page(q="100%_")["total"])
        self.assertEqual(0, self.home.page(q="100%_", project_id="P2")["total"])
        self.assertEqual(1, len(self.home.page(project_id="P1", group="running")["items"]))

    def test_summary_uses_stored_task_status_and_does_not_load_detail_or_history(self):
        task = self.tasks.create("fixture")
        with self.tasks.connect() as db:
            db.execute("UPDATE tasks SET status='rework' WHERE id=?", (task["id"],))
        item = self.add("V0事项", stage="executing", v0=True, active_task_id=task["id"],
                        research_manifest={"large": "x" * 200000}, messages=["x" * 200000])
        with patch.object(InitiativeStore, "get", side_effect=AssertionError("must not load detail")), \
             patch("workbench.daily_delivery.manifest", side_effect=AssertionError("must not hash files")), \
             patch("workbench.learning.LearningStore.view", side_effect=AssertionError("must not load history")):
            page = self.home.page()
        self.assertEqual(item["id"], page["items"][0]["item"]["id"])
        self.assertEqual("rework", page["items"][0]["work"]["stage"])
        self.assertEqual(1, page["counts"]["attention"])
        self.assertLess(len(json.dumps(page)), 2500)

    def test_invalid_saved_workflow_is_unknown_and_never_an_outcome(self):
        item = self.add()
        with self.store.connect() as db:
            db.execute("UPDATE initiative_workflows SET payload='bad json' WHERE id=?", (item["id"],))
        page = self.home.page()
        self.assertEqual(1, page["counts"]["unknown"])
        self.assertEqual("unavailable", page["items"][0]["work"]["stage"])
        self.assertEqual(0, self.home.page(group="outcome")["total"])

    def test_cursor_is_bound_to_filters_and_values_are_validated(self):
        self.add("一")
        self.add("二")
        cursor = self.home.page(limit=1)["next_cursor"]
        self.assertTrue(cursor)
        with self.assertRaisesRegex(ValueError, "游标"):
            self.home.page(q="一", cursor=cursor)
        for filters in ({"cursor": "%%%"}, {"limit": 101}, {"limit": 0}, {"limit": "a"},
                        {"group": "guess"}, {"include_hidden": "sometimes"}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.home.page(**filters)

    def test_legacy_query_preserves_items_projection_and_visibility_defaults(self):
        item = self.add("[Mock课程演示] 已清除", hidden=True)
        self.assertEqual(0, self.home.page()["total"])
        page = self.store.query()
        self.assertEqual(1, len(page["items"]))
        self.assertEqual(item["id"], page["items"][0]["id"])
        self.assertIn("readiness", page["items"][0])
        self.assertIn("work_packages", page["items"][0])
        self.assertNotIn("workflow_stage", page["items"][0])

    def test_idempotent_creation_survives_retry_and_parallel_requests(self):
        data = {"title": "同一需求", "raw_signal": "原始需求", "source": "test", "project_id": "P1"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.create(data, "tester", "submission-1"), range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        restarted = InitiativeStore(self.path)
        self.assertEqual(results[0]["id"], restarted.create(data, "tester", "submission-1")["id"])
        with self.store.connect() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM initiatives").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM initiative_events").fetchone()[0])
        with self.assertRaises(InitiativeSubmissionConflict):
            self.store.create({**data, "title": "另一个需求"}, "tester", "submission-1")
        self.assertNotEqual(results[0]["id"], self.store.create(data, "tester")["id"])
        with self.assertRaises(ValueError):
            self.store.create(data, "tester", "")


class InitiativeHomeHTTPTests(unittest.TestCase):
    def test_summary_list_and_idempotent_create_are_connected_to_http(self):
        from workbench.workbench_server import WorkbenchApp, make_handler
        with tempfile.TemporaryDirectory() as temporary:
            app = WorkbenchApp(Path(temporary))
            for number in range(24):
                app.initiatives.create({"title": f"已有需求 {number}", "raw_signal": "原始需求",
                                        "source": "test", "project_id": app.default_project}, "tester")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = HTTPConnection("127.0.0.1", server.server_port)
            try:
                def request(method, route, payload=None):
                    client.request(method, route, None if payload is None else json.dumps(payload).encode("utf-8"),
                                   {"Content-Type": "application/json"})
                    response = client.getresponse()
                    return response.status, json.loads(response.read())
                with patch.object(app.initiative_workflow, "get", side_effect=AssertionError("detail called")):
                    status, first = request("GET", "/api/v1/initiatives/home?group=attention")
                    self.assertEqual(200, status)
                    self.assertEqual(24, first["counts"]["attention"])
                    self.assertEqual(20, len(first["items"]))
                    self.assertEqual(app.default_project, first["items"][0]["work"]["project"]["id"])
                    status, second = request("GET", "/api/v1/initiatives/home?group=attention&cursor=" + first["next_cursor"])
                    self.assertEqual(200, status)
                    self.assertEqual(4, len(second["items"]))
                    self.assertIsNone(second["next_cursor"])
                status, legacy = request("GET", "/api/v1/initiatives")
                self.assertEqual(200, status)
                self.assertEqual(24, len(legacy["items"]))
                self.assertIn("readiness", legacy["items"][0])
                body = {"actor": "tester", "submission_key": "http-retry-1", "data": {
                    "title": "响应丢失的需求", "raw_signal": "原始输入", "source": "test"}}
                status, created = request("POST", "/api/v1/initiatives", body)
                self.assertEqual(201, status)
                status, retried = request("POST", "/api/v1/initiatives", body)
                self.assertEqual(201, status)
                self.assertEqual(created["id"], retried["id"])
                body["data"]["title"] = "不同需求"
                self.assertEqual(409, request("POST", "/api/v1/initiatives", body)[0])
                self.assertEqual(400, request("GET", "/api/v1/initiatives/home?limit=101")[0])
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                thread.join(5)


if __name__ == "__main__":
    unittest.main()
