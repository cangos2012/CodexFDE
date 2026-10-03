"""A report read retry must preserve disk identity and reject concurrent edits."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from workbench import file_io
from workbench.project_delivery import CandidateProjectEval


class ProjectReportReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'project'
        self.runtime = Path(self.temporary.name) / 'runtime'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        (self.root / 'value.txt').write_text('1', encoding='utf-8')
        self.report = {'summary': {'total': 1, 'passed': 1, 'blocking_failed': 0,
                                  'observing_failed': 0, 'decision': 'pass'},
                       'results': [{'name': 'value', 'level': 'blocking', 'passed': True}]}
        self.runner = CandidateProjectEval(self.root, self.runtime, 'TASK-read',
                                           ['fixture-eval'], 'read-test')

    def run_locked(self, *, permanent=False, tamper=False):
        original = Path.open
        failures = []

        def locked(target, mode='r', *args, **kwargs):
            if target.name == 'report.json' and mode == 'rb' and (permanent or not failures):
                failures.append(target)
                if tamper:
                    with original(target, 'w', encoding='utf-8') as output:
                        output.write('{}')
                raise PermissionError('temporary report sharing lock')
            return original(target, mode, *args, **kwargs)

        result = subprocess.CompletedProcess(['fixture-eval'], 0, json.dumps(self.report), '')
        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', locked), \
                patch.object(file_io.time, 'sleep'), \
                patch('workbench.execution.CodexExecutionRunner._run_codex_streaming', return_value=result):
            return self.runner(), failures

    def test_transient_lock_returns_hash_of_verified_persisted_report(self):
        report, failures = self.run_locked()
        self.assertEqual(1, len(failures))
        raw = file_io.read_bytes(report['runner']['report_path'])
        self.assertEqual(report['report_sha256'], hashlib.sha256(raw).hexdigest())
        persisted = json.loads(raw)
        self.assertEqual(self.report['results'], persisted['results'])
        self.assertTrue(persisted['runner']['validated'])

    def test_persistent_denial_cannot_return_successful_evidence(self):
        with self.assertRaises(PermissionError):
            self.run_locked(permanent=True)
        self.assertEqual(1, len(list(self.runtime.rglob('process.json'))))
        self.assertEqual(1, len(list(self.runtime.rglob('raw-report.json'))))

    def test_report_changed_during_read_retry_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '报告写入后变化'):
            self.run_locked(tamper=True)


if __name__ == '__main__':
    unittest.main()
