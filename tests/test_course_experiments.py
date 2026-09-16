"""Real local process regression; fixtures are maintenance data, not student work."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from workbench.course_experiments import copy_experiment_sources
from workbench.external_project import flowerp_root, python_for

ROOT = Path(__file__).resolve().parents[1]


class CourseExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.product = flowerp_root()
        python_for(cls.product)

    def setUp(self):
        self.run = ROOT / '.runtime/experiment-regression' / uuid.uuid4().hex
        self.run.mkdir(parents=True)
        self.counter = 0

    def command(self, *args, expected=0, cwd=ROOT):
        command = [sys.executable, '-B', '-X', 'utf8', *map(str, args)]
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, encoding='utf-8',
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), timeout=120)
        self.counter += 1
        (self.run/f'{self.counter:02}.json').write_text(json.dumps(dict(command=command, cwd=str(cwd),
             stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode), ensure_ascii=False, indent=2), encoding='utf-8')
        self.assertEqual(result.returncode, expected, result.stdout + '\n' + result.stderr)
        return result

    def test_observation_uses_customer_interpreter_preserves_cwd_and_exit(self):
        script = self.run / 'probe.py'
        script.write_text(
            f'import sys;sys.path.insert(0,{str(ROOT)!r})\n'
            'from workbench.course_experiments import ensure_product_process\n'
            'ensure_product_process(__file__)\n'
            'import flowerp,json;from pathlib import Path\n'
            'print(json.dumps(dict(python=sys.executable,prefix=sys.prefix,source=flowerp.__file__,cwd=str(Path.cwd()))))\n'
            'raise SystemExit(7)\n', encoding='utf-8')
        result = self.command(script, expected=7, cwd=self.run)
        data = json.loads(result.stdout)
        self.assertEqual(Path(data['python']).resolve(), Path(python_for(self.product)).resolve())
        self.assertEqual(Path(data['prefix']).resolve(), (self.product/'.venv').resolve())
        self.assertTrue(Path(data['source']).resolve().is_relative_to(self.product))
        self.assertEqual(Path(data['cwd']), self.run)

    def test_copy_manifest_and_candidate_eval_never_fall_back_to_product(self):
        candidate = self.run/'candidate'
        manifest = copy_experiment_sources(candidate)
        for relative, origin in manifest['files'].items():
            self.assertEqual(hashlib.sha256((candidate/relative).read_bytes()).hexdigest(), origin['sha256'])
        with self.assertRaises(FileExistsError):
            copy_experiment_sources(candidate)
        # Candidate's explicit business check must observe this candidate marker.
        (candidate/'eval/erp_cases.py').write_text('def receiving_is_idempotent():\n    return "ONLY-THIS-CANDIDATE"\n', encoding='utf-8')
        result = self.command('-m', 'eval.harness', '--suite', 'blocking', '--case', 'receiving_is_idempotent', '--no-report', cwd=candidate)
        self.assertIn('ONLY-THIS-CANDIDATE', result.stdout)

    def test_l05_old_green_two_real_reds_repair_and_refuse_overwrite(self):
        candidate = self.run/'l05'
        prepare = ROOT/'docs/courses/L05/examples/prepare_receiving_fixture.py'
        check = ROOT/'docs/courses/L05/examples/receiving_contract_eval.py'
        self.command(prepare, '--output', candidate)
        self.command(check, '--candidate', candidate, '--return-only')
        for _ in range(2):
            result = self.command(check, '--candidate', candidate, expected=1)
            self.assertEqual({x['requirement'] for x in json.loads(result.stdout)['failures']}, {'AC-REPLAY', 'AC-NEW'})
        shutil.copyfile(self.product/'flowerp/service.py', candidate/'flowerp/service.py')
        self.command(check, '--candidate', candidate)
        before = (candidate/'flowerp/service.py').read_bytes()
        self.command(prepare, '--output', candidate, expected=2)
        self.assertEqual(before, (candidate/'flowerp/service.py').read_bytes())

    def test_l06_prepare_false_green_repair_transfer_resume_and_reject_stale(self):
        old = self.run/'maintenance-l05-fixture'
        candidate = old/'candidate'
        copy_experiment_sources(candidate)
        (candidate/'tests').mkdir()
        (candidate/'tests/__init__.py').write_text('', encoding='utf-8')
        copies = {'test_receiving_starter.py': 'tests/test_l05_receiving.py',
                  'test_scope_starter.py': 'tests/test_l05_scope.py', 'write_scope_eval.py': 'eval/l05_scope.py'}
        for source, target in copies.items():
            shutil.copyfile(ROOT/'docs/courses/L05/examples'/source, candidate/target)
        digest = lambda p: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        (old/'session.json').write_text(json.dumps({'run': str(old), 'kind': 'maintenance-fixture-not-student'}), encoding='utf-8')
        (old/'submission.json').write_text(json.dumps({'isolation': {'path': str(candidate)}, 'task': {'id': 'TASK-MAINTENANCE-FIXTURE'}}), encoding='utf-8')
        (old/'frozen-checks.json').write_text(json.dumps({'files': {p: digest(candidate/p) for p in copies.values()}}), encoding='utf-8')
        tool = ROOT/'docs/courses/L06/examples/import_practice.py'
        target = self.run/'l06'
        self.command(tool, 'prepare', '--run', target, '--l05-session', old/'session.json')
        session = target/'session.json'
        def execute(action, name, expected, *extra):
            return self.command(tool, action, '--session', session, '--report', target/'reports'/f'{name}.json', *extra, expected=expected)
        execute('contract', '01-contract', 1)
        execute('run', '02-false-green', 0)
        execute('review', '02-false-green', 1)
        runner = target/'candidate/eval/l06_runner.py'
        text = runner.read_text(encoding='utf-8')
        runner.write_text(text.replace('blocking_failed = 0', "blocking_failed = sum(not r['passed'] and r['level']=='blocking' for r in results)"), encoding='utf-8')
        execute('contract', '03-contract', 0)
        execute('run', '04-block', 1)
        execute('review', '04-block', 0)
        adapter = target/'candidate/flowerp/import_batch.py'
        adapter.write_text("from .identity import SYSTEM_PRINCIPAL\ndef submit(service, content):\n    job = service.validate_csv(SYSTEM_PRINCIPAL, 'products', content)\n    return service.commit(SYSTEM_PRINCIPAL, job['id'])\n", encoding='utf-8')
        execute('run', '05-green', 0)
        execute('review', '05-green', 0)
        execute('contract', '06-final', 0)
        execute('run', '07-seven', 0, '--rows', '7')
        execute('review', '07-seven', 0)
        execute('review', '04-block', 1)
        execute('run', '05-green', 1)  # refuses to overwrite original output
        result = self.command(tool, 'verify', '--session', session)
        self.assertEqual(set(json.loads(result.stdout)['changed']), {'eval/l06_runner.py', 'flowerp/import_batch.py'})
        self.command(tool, 'prepare', '--run', target, '--l05-session', old/'session.json', expected=1)
        # The historical check adapter still supports old candidate snapshots.
        legacy = self.run/'legacy-candidate'
        copy_experiment_sources(legacy)
        (legacy/'tests').mkdir()
        (legacy/'tests/__init__.py').write_text('', encoding='utf-8')
        service = legacy/'flowerp/service.py'
        text = service.read_text(encoding='utf-8')
        start = text.index('    def export_inventory(')
        end = text.index('\n    def ', start+5)
        service.write_text(text[:start]+text[end:], encoding='utf-8')
        self.command(ROOT/'docs/courses/L06/examples/prepare_checks.py', '--candidate', legacy,
                     '--l05-session', old/'session.json', '--output', self.run/'legacy-source.json')
        restored = json.loads((self.run/'legacy-source.json').read_text(encoding='utf-8'))['prerequisite_restoration']
        self.assertEqual(Path(restored['source']), self.product/'flowerp/service.py')
        self.command('-m', 'unittest', 'tests.test_l06_runner', expected=1, cwd=legacy)

    def test_l04_real_file_delivery_and_duplicate_output(self):
        candidate = self.run/'candidate'
        copy_experiment_sources(candidate)
        tool = ROOT/'docs/courses/L04/scripts/check_inventory_delivery.py'
        output = self.run/'delivery'
        args = (tool, '--workspace', candidate, '--output', output, '--case', 'all',
                '--file-entry', 'flowerp.inventory_export:export_inventory_file')
        self.command(*args)
        self.command(*args, expected=2)

    def test_l09_map_real_failure_and_reject_wrong_exit_or_overwrite(self):
        lab = ROOT/'docs/courses/L09/examples/cancellation_lab.py'
        mapper = ROOT/'docs/courses/L09/examples/map_report.py'
        report = self.run/'leak.json'
        self.command(lab, 'leak', '--report-path', report, expected=1)
        args = (mapper, report, '--case', 'l09_teaching_cancellation')
        self.command(*args, '--observed-exit', 0, '--output', self.run/'bad.json', expected=2)
        self.assertFalse((self.run/'bad.json').exists())
        self.command(*args, '--observed-exit', 1, '--output', self.run/'draft.json')
        self.command(*args, '--observed-exit', 1, '--output', self.run/'draft.json', expected=2)

    def test_l14_http_sqlite_same_initiative_before_and_after_restart(self):
        from workbench.workbench_server import WorkbenchApp, make_handler
        runtime = self.run/'runtime'
        initiative_id = None
        for _ in range(2):
            app = WorkbenchApp(runtime)
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                if initiative_id is None:
                    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    data = {'title': '维护回归夹具', 'raw_signal': '检查同一事项持久化',
                            'source': 'maintenance fixture, not student evidence',
                            'goal': '验证读取工具', 'project_id': 'FlowERP', 'acceptance': ['字段一致']}
                    connection.request('POST', '/api/v1/initiatives', json.dumps({'actor': 'maintenance-fixture', 'data': data}),
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    body = json.loads(response.read())
                    connection.close()
                    self.assertEqual(response.status, 201, body)
                    initiative_id = body['id']
                tool = ROOT/'docs/courses/L14/examples/read_initiative.py'
                args = (tool, '--base-url', f'http://127.0.0.1:{server.server_port}', '--initiative-id', initiative_id)
                result = self.command(*args, '--runtime-dir', runtime)
                self.assertTrue(all(v['equal'] for v in json.loads(result.stdout)['fields'].values()))
                self.command(*args, '--runtime-dir', self.run/'missing', expected=2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(5)

    def test_l15_digest_real_unaccepted_task_duplicate_and_changed_evidence(self):
        from workbench.task_store import TaskStore
        from workbench.release_index import create_release_index
        runtime = self.run/'runtime'
        task = TaskStore(runtime/'workbench.db').create('维护回归夹具，不是学生交付', 'REQ-MAINTENANCE',
                                                       spec_path=str(runtime/'missing-spec.md'))
        risks = runtime/'risks.md'
        risks.write_text('尚未执行，尚未验收。', encoding='utf-8')
        index = create_release_index(runtime, task['id'], risks=risks)
        tool = ROOT/'docs/courses/L15/examples/export_digest.py'
        args = (tool, '--runtime-dir', runtime, '--index', index['path'])
        result = self.command(*args, '--out', self.run/'digest.md')
        self.assertEqual(json.loads(result.stdout)['task_status'], task['status'])
        self.assertIn('human_acceptance', json.loads(Path(index['path']).read_text(encoding='utf-8'))['evidence_gaps'])
        self.command(*args, '--out', self.run/'digest.md', expected=1)
        # Tamper a separate index, preserving the original evidence and digest.
        data = json.loads(Path(index['path']).read_text(encoding='utf-8'))
        data['references']['remaining_risks']['sha256'] = '0'*64
        changed = Path(index['path']).with_name('tampered-index.json')
        changed.write_text(json.dumps(data), encoding='utf-8')
        self.command(tool, '--runtime-dir', runtime, '--index', changed, '--out', self.run/'rejected.md', expected=1)
        self.assertFalse((self.run/'rejected.md').exists())
