"""Local fixtures exercise real evidence and process boundaries, not human acceptance."""
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from eval.workbench_contracts import LocalDeliveryFixture
from workbench.evidence_gate import assert_current_evidence
from workbench.generic_preview import ProjectPreviews
from workbench.mutation_receipts import MutationReceipts, MutationPending
from workbench.project_configuration import ProjectConfiguration, configuration
from workbench.project_plan import ProjectPlans
from workbench.workbench_server import WorkbenchApp, make_handler


class PersonalPlatformTests(unittest.TestCase):
    def test_plan_dependencies_and_architecture_drift_block_execution(self):
        with LocalDeliveryFixture() as f:
            a, b = f.item('A'), f.item('B')
            plans = ProjectPlans(f.projects, f.items, f.service)
            plans.assert_ready(b['id'])  # No plan remains a supported path.
            fields = dict(objective='Local fixture', architecture_refs=['policy.txt'], milestones=[
                dict(id='A', title='First', acceptance='Accepted value', initiative_ids=[a['id']]),
                dict(id='B', title='Second', acceptance='Accepted reuse', initiative_ids=[b['id']], depends_on=['A'])])
            plans.save(f.project['id'], fields, 'fixture-owner', 0)
            with self.assertRaisesRegex(ValueError, '前置里程碑'):
                plans.assert_ready(b['id'])
            cycle = json.loads(json.dumps(fields)); cycle['milestones'][0]['depends_on'] = ['B']
            with self.assertRaisesRegex(ValueError, '循环'):
                plans.save(f.project['id'], cycle, 'fixture-owner', 1)
            fields['milestones'][0].update(status='completed', evidence='Cannot claim unfinished delivery')
            with self.assertRaisesRegex(ValueError, '尚未接受'):
                plans.save(f.project['id'], fields, 'fixture-owner', 1)
            fields['milestones'][0]['status'] = 'active'
            with self.assertRaisesRegex(ValueError, '版本'):
                plans.save(f.project['id'], fields, 'fixture-owner', 0)
            (f.source / 'policy.txt').write_text('changed', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '基线已变化'):
                plans.assert_ready(a['id'])

    def test_plan_completion_requires_accepted_item_and_reopen_blocks_dependency(self):
        with LocalDeliveryFixture() as f:
            a, _ = f.accepted_source(); f.integrate(a); b = f.item('Next')
            plans = ProjectPlans(f.projects, f.items, f.service)
            plans.save(f.project['id'], dict(objective='Local fixture', milestones=[
                dict(id='A', title='Accepted A', acceptance='Value accepted', status='completed',
                     evidence='Fixture accepted candidate', initiative_ids=[a['id']]),
                dict(id='B', title='B', acceptance='Reuse', initiative_ids=[b['id']], depends_on=['A'])]), 'fixture-owner', 0)
            plans.assert_ready(b['id'])
            f.call(a, 'reopen', 'New local fixture iteration')
            current = plans.get(f.project['id'])
            self.assertEqual('needs_revalidation', current['milestones'][0]['status'])
            with self.assertRaisesRegex(ValueError, '前置里程碑'):
                plans.assert_ready(b['id'])

    def test_config_versions_and_json_command_constraints(self):
        with LocalDeliveryFixture() as f:
            config = ProjectConfiguration(f.projects)
            value = dict(preview_config=dict(command=[sys.executable, '-c', 'print({"status":"ok"})'],
                health={'path': '/health', 'expected': {'status': 'ok'}}), expected_configuration_revision=0)
            self.assertEqual(1, config.save(f.project['id'], value, 'fixture-owner')['configuration_revision'])
            with self.assertRaisesRegex(ValueError, '版本'):
                config.save(f.project['id'], value, 'fixture-owner')
            for preview in ('arbitrary command', {'command': 'python server.py'}, {'command': [sys.executable, '{unknown}']}):
                with self.assertRaises(ValueError):
                    configuration(preview, [])
            with self.assertRaises(ValueError):
                configuration(None, ['invalid'])
            with self.assertRaisesRegex(ValueError, '密钥'):
                configuration({'command':[sys.executable, '--password', 'fixture'], 'health':{'path':'/health'}}, [])

    def test_mutation_retries_never_repeat_side_effects_or_uncertain_requests(self):
        with LocalDeliveryFixture() as f:
            receipts = MutationReceipts(f.tasks); calls = []
            def work():
                calls.append('called'); return {'id': 'result'}
            self.assertEqual({'id': 'result'}, receipts.run('op', 'key', {'actor': 'fixture'}, work))
            self.assertEqual({'id': 'result'}, receipts.run('op', 'key', {'actor': 'fixture'}, work))
            self.assertEqual(['called'], calls)
            with self.assertRaisesRegex(ValueError, '不同请求'):
                receipts.run('op', 'key', {'actor': 'other'}, work)
            def fail():
                calls.append('failed'); raise ValueError('failure receipt')
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'failure receipt'):
                    receipts.run('op', 'failed', {}, fail)
            self.assertEqual(['called', 'failed'], calls)
            def uncertain():
                with self.assertRaises(MutationPending):
                    receipts.run('op', 'pending', {}, work)
                return {'id': 'first'}
            receipts.run('op', 'pending', {}, uncertain)
            self.assertEqual(['called', 'failed'], calls)

    def test_all_acceptance_paths_reject_old_report_receipt_and_candidate_drift(self):
        with LocalDeliveryFixture() as f:
            item = f.item(); f.prepare(item); state = f.execute(item)
            task = f.tasks.get(state['active_task_id'])
            assert_current_evidence(task, f.runtime)
            old = json.loads(json.dumps(task)); old['result']['runner'].pop('candidate_sha256')
            with self.assertRaisesRegex(ValueError, '绑定'):
                assert_current_evidence(old, f.runtime)
            for field in ('process_path', 'process_sha256', 'configured_command'):
                missing = json.loads(json.dumps(task)); missing['result']['runner'].pop(field)
                with self.assertRaisesRegex(ValueError, '绑定'):
                    assert_current_evidence(missing, f.runtime)
            other = f.item('Same source, different task contract'); f.prepare(other)
            other_state = f.execute(other)
            borrowed = f.tasks.get(other_state['active_task_id']); borrowed['result'] = task['result']
            with self.assertRaisesRegex(ValueError, '所属任务'):
                assert_current_evidence(borrowed, f.runtime)
            receipt = Path(task['result']['runner']['process_path']); raw = receipt.read_bytes()
            receipt.write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, '回执'):
                f.tasks.review(task['id'], 'fixture-reviewer', 'approve', 'Fixture review')
            receipt.write_bytes(raw)
            (Path(state['workspace']) / 'value.txt').write_text('7', encoding='utf-8')
            for accept in (lambda: f.tasks.review(task['id'], 'fixture-reviewer', 'approve', 'Fixture review'),
                           lambda: f.tasks.transition(task['id'], 'completed', 'Fixture direct accept', actor='fixture-reviewer')):
                with self.assertRaisesRegex(ValueError, '变化'):
                    accept()

    def test_non_flowerp_preview_owns_process_and_rejects_consumed_plan(self):
        with LocalDeliveryFixture() as f:
            # A generic project has no flowerp package or web/index.html.
            (f.source / 'preview.py').write_text(
                "from http.server import BaseHTTPRequestHandler, HTTPServer\nimport json,sys\n"
                "from pathlib import Path\nPath(sys.argv[2]).mkdir(parents=True,exist_ok=True)\n"
                "class H(BaseHTTPRequestHandler):\n"
                " def do_GET(self):\n"
                "  body=json.dumps({'status':'ok'}).encode(); self.send_response(200); self.end_headers(); self.wfile.write(body)\n"
                " def log_message(self,*args): pass\n"
                "HTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()\n", encoding='utf-8')
            item = f.item(); f.prepare(item); state = f.execute(item)
            config = ProjectConfiguration(f.projects)
            config.save(f.project['id'], dict(expected_configuration_revision=0, preview_config={
                'command': [sys.executable, '-B', 'preview.py', '{port}', '{runtime_dir}'],
                'health': {'path': '/health', 'expected': {'status': 'ok'}}, 'timeout_seconds': 8}), 'fixture-owner')
            previews = ProjectPreviews(f.runtime, f.tasks, f.projects, config)
            try:
                plan = previews.plan(state['active_task_id'])
                fields = {**plan, 'confirmed': True}
                result = previews.start(state['active_task_id'], 'fixture-owner', fields)
                self.assertTrue(result['health_result']['passed'])
                self.assertFalse(result['human_accepted'])
                process = previews.running[state['active_task_id']][0]
                self.assertIsNone(process.poll())
                with self.assertRaisesRegex(ValueError, '消费'):
                    previews.start(state['active_task_id'], 'fixture-owner', fields)
                config.save(f.project['id'], {'expected_configuration_revision':1, 'preview_config':None}, 'fixture-owner')
                with self.assertRaisesRegex(ValueError, '配置已移除'):
                    previews.start(state['active_task_id'], 'fixture-owner', fields)
                self.assertEqual('1', (f.source / 'value.txt').read_text())
            finally:
                previews.close()
            self.assertIsNotNone(process.poll())


class PlatformHTTPTests(unittest.TestCase):
    def test_signed_versioned_idempotent_project_plan_and_runtime_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = WorkbenchApp(tmp, enable_advanced_runtime=True)
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            def request(method, path, body=None, origin=None, expected_service=None):
                conn = HTTPConnection(*server.server_address)
                headers = {'Content-Type': 'application/json'}
                if origin: headers['Origin'] = origin
                if expected_service: headers['X-Workbench-Expected-Service-Instance'] = expected_service
                conn.request(method, path, json.dumps(body) if body is not None else None, headers)
                reply = conn.getresponse(); payload = json.loads(reply.read()); status = reply.status; conn.close()
                return status, payload
            try:
                item = app.initiatives.create({'title':'[Mock课程演示] platform test', 'raw_signal':'fixture',
                    'source':'automated test', 'project_id':app.default_project}, 'fixture-owner')
                path = '/api/v1/projects/' + app.default_project + '/plan'
                body = {'objective':'Fixture objective', 'milestones':[], 'actor':'fixture-owner',
                    'expected_revision':0, 'submission_key':'fixture-plan'}
                self.assertEqual(200, request('POST', path, body)[0])
                self.assertEqual(1, request('POST', path, body)[1]['revision'])
                self.assertEqual(400, request('POST', path, {**body, 'submission_key':'new'})[0])
                self.assertEqual(403, request('POST', path, body, 'http://untrusted.invalid')[0])
                self.assertEqual(400, request('POST', path, {**body, 'actor':''})[0])
                self.assertEqual(409, request('POST', path, {**body, 'expected_revision':1, 'submission_key':'stale-instance'}, expected_service='other-service')[0])
                self.assertEqual(1, app.project_plans.get(app.default_project)['revision'])
                code, runtime = request('GET', '/api/v1/initiatives/' + item['id'] + '/runtime')
                self.assertEqual(200, code); self.assertEqual(item['id'], runtime['initiative_id'])
                self.assertTrue(runtime['advanced_enabled'])
                self.assertEqual(0, request('GET', '/api/v1/learning/metrics')[1]['eligible_initiatives'])
            finally:
                server.shutdown(); worker.join(5); server.server_close(); app.delivery_runtime.close(); app.previews.close()
                app.harness_api.shutdown()
