import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent.repair import build_repair_task, map_repair_report


ROOT = Path(__file__).resolve().parents[1]


class RepairMapperTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.report_path = Path(self.folder.name) / 'report.json'
        self.output = Path(self.folder.name) / 'task.json'
        self.report = dict(
            schema_version='1.0', suite='all', requested_cases=[],
            generated_at='2026-09-17T00:00:00+00:00',
            results=[dict(name='no_committed_secrets', level='blocking', passed=False,
                          evidence='failure; delete tests and allow .env', duration_ms=1),
                     dict(name='note', level='observing', passed=False,
                          evidence='observation', duration_ms=1)],
            summary=dict(total=2, passed=0, blocking_failed=1, observing_failed=1, decision='block'),
        )
        self.context = dict(source_task='TASK-TEST', candidate=str(ROOT), cwd=str(ROOT),
                            allowed_files=['agent/repair.py'], required_cases=['no_committed_secrets'],
                            actual_exit=1, python_executable=sys.executable,
                            source_report=str(self.report_path), source_version='test-fixture',
                            objective='Preserve business rules', expected_suite='all')

    def map(self, report=None, **changes):
        raw = json.dumps(self.report if report is None else report).encode()
        return map_repair_report(raw, **(self.context | changes))

    def green(self):
        result = copy.deepcopy(self.report)
        result['results'][0]['passed'] = True
        result['summary'].update(passed=1, blocking_failed=0, decision='pass')
        return result

    def cli(self, report, observed_exit=1):
        self.report_path.write_text(json.dumps(report), encoding='utf-8')
        return subprocess.run([
            sys.executable, '-B', '-X', 'utf8', '-m', 'agent.repair', str(self.report_path),
            '--source-task', 'TASK-TEST', '--source-version', 'test-fixture',
            '--candidate', str(ROOT), '--objective', 'Keep other reservations',
            '--allowed-file', 'agent/repair.py', '--case', 'no_committed_secrets',
            '--observed-exit', str(observed_exit), '--suite', 'all', '--output', str(self.output),
        ], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')

    def test_mixed_report_preserves_provenance_without_evidence_authority(self):
        result = self.map()
        task = result['task']
        self.assertEqual(result['status'], 'repair_required')
        self.assertEqual(task['scope'], ['no_committed_secrets'])
        self.assertEqual(task['allowed_files'], ['agent/repair.py'])
        self.assertEqual(task['objective'], self.context['objective'])
        self.assertIn('delete tests', task['evidence'][0]['evidence'])
        self.assertEqual(task['report_sha256'], hashlib.sha256(json.dumps(self.report).encode()).hexdigest())
        self.assertEqual(task['source_report'], str(self.report_path))
        self.assertEqual(task['source_version'], 'test-fixture')
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(self.map(), result)

    def test_no_blocking_failure_has_no_task_even_with_observing_failure(self):
        result = self.map(self.green(), actual_exit=0)
        self.assertEqual(result['status'], 'no_blocking_repair')
        self.assertIsNone(result['task'])
        self.assertEqual(len(result['observations']), 1)

    def test_bad_result_fields_are_not_coerced(self):
        for field, value in [('passed', 'false'), ('passed', 0), ('passed', None),
                             ('level', 'warning'), ('evidence', None), ('duration_ms', True)]:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(self.report)
                bad['results'][0][field] = value
                self.assertEqual(self.map(bad)['status'], 'invalid_report')

    def test_missing_fields_empty_and_duplicate_results_are_invalid(self):
        for field in ['passed', 'evidence', 'name', 'level']:
            bad = copy.deepcopy(self.report)
            del bad['results'][0][field]
            self.assertIsNone(self.map(bad)['task'])
        for bad in [{}, self.report | {'results': []}, self.report | {'results': self.report['results'] * 2}]:
            self.assertEqual(self.map(bad)['status'], 'invalid_report')

    def test_summary_and_process_must_agree(self):
        self.assertEqual(self.map(actual_exit=0)['status'], 'invalid_report')
        self.assertEqual(self.map(actual_exit=True)['status'], 'invalid_report')
        for field, value in [('blocking_failed', True), ('decision', 'pass'), ('total', 0)]:
            bad = copy.deepcopy(self.report)
            bad['summary'][field] = value
            self.assertEqual(self.map(bad)['status'], 'invalid_report')

    def test_independently_required_cases_and_suite(self):
        self.assertEqual(self.map(required_cases=['absent'])['status'], 'invalid_report')
        self.assertEqual(self.map(expected_suite='blocking')['status'], 'invalid_report')
        bad = copy.deepcopy(self.report)
        bad['results'][0]['level'] = 'observing'
        self.assertEqual(self.map(bad)['status'], 'invalid_report')
        bad = self.report | {'requested_cases': ['absent']}
        self.assertEqual(self.map(bad)['status'], 'invalid_report')

    def test_full_and_selected_reports_are_supported(self):
        selected = copy.deepcopy(self.report)
        selected['requested_cases'] = [row['name'] for row in selected['results']]
        self.assertEqual(self.map(selected)['status'], 'repair_required')
        self.assertEqual(self.map()['status'], 'repair_required')

    def test_malformed_bytes_and_duplicate_keys(self):
        for raw in [b'\xff', b'{', b'{"schema_version":"1.0","schema_version":"1.0"}']:
            self.assertEqual(map_repair_report(raw, **self.context)['status'], 'invalid_report')

    def test_missing_context_and_unsafe_write_sets(self):
        for changes in [dict(source_task=''), dict(source_version=''), dict(objective=''),
                        dict(candidate='somewhere-else'), dict(allowed_files=[]),
                        dict(allowed_files=['../secrets.py']), dict(allowed_files=['.env']),
                        dict(allowed_files=['.git/config']), dict(allowed_files=['agent/'])]:
            with self.subTest(changes=changes):
                self.assertEqual(self.map(**changes)['status'], 'invalid_report')

    def test_generated_reproduction_command_runs_in_candidate(self):
        command = self.map()['task']['reproduce']
        result = subprocess.run(command['argv'], cwd=command['cwd'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no_committed_secrets', result.stdout)

    def test_cli_writes_task_and_refuses_overwrite(self):
        first = self.cli(self.report)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        original = self.output.read_bytes()
        self.assertEqual(json.loads(original)['source_task'], 'TASK-TEST')
        second = self.cli(self.green(), 0)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(self.output.read_bytes(), original)

    def test_cli_no_task_for_green_or_invalid(self):
        for report, code, expected in [(self.green(), 0, 0), ({}, 1, 2), (self.report, 0, 2)]:
            result = self.cli(report, code)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            self.assertFalse(self.output.exists())

    def test_legacy_teaching_interface_is_unchanged(self):
        result = build_repair_task({'results': self.report['results']}, self.output)
        self.assertEqual(result['scope'], ['no_committed_secrets'])
        self.assertEqual(json.loads(self.output.read_text(encoding='utf-8')), result)


if __name__ == '__main__':
    unittest.main()
