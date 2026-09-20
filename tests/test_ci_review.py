from __future__ import annotations

import hashlib
import json
import tempfile
import unittest

from workbench.ci_review import retain, verify


class CIReviewTests(unittest.TestCase):
    def evidence(self, decision='pass'):
        report = json.dumps({'suite': 'blocking', 'requested_cases': ['atomic'],
                             'summary': {'decision': decision}}, separators=(',', ':'))
        envelope = {'commit_sha': 'abc123', 'run_id': '42', 'workflow': 'gate',
                    'report_decision': decision,
                    'report_sha256': hashlib.sha256(report.encode()).hexdigest()}
        return report, envelope

    def test_verified_green_is_retained_with_original_files(self):
        report, envelope = self.evidence()
        with tempfile.TemporaryDirectory() as directory:
            result = retain(directory, 'TASK-1', report, envelope,
                run_url='https://github.com/acme/repo/actions/runs/42', job_conclusion='success',
                candidate_sha='abc123', actor='复验者')
            self.assertEqual('verified', result['status'])
            self.assertTrue(result['artifacts']['report'].endswith('report.json'))

    def test_false_green_is_rejected(self):
        report, envelope = self.evidence('block')
        with self.assertRaisesRegex(ValueError, '没有如实传播'):
            verify(report, envelope, run_url='https://ci.example/runs/42',
                   job_conclusion='success', candidate_sha='abc123')

    def test_simulated_and_tampered_evidence_are_rejected(self):
        report, envelope = self.evidence()
        envelope['run_id'] = 'SIMULATED-42'
        with self.assertRaisesRegex(ValueError, 'SIMULATED'):
            verify(report, envelope, run_url='https://ci.example/runs/42',
                   job_conclusion='success', candidate_sha='abc123')
        envelope['run_id'] = '42'; envelope['report_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            verify(report, envelope, run_url='https://ci.example/runs/42',
                   job_conclusion='success', candidate_sha='abc123')


if __name__ == '__main__':
    unittest.main()
