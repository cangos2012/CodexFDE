"""Registered source reads and verify-only Eval use real owned processes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from workbench.execution import spawn_owned_process
from workbench.execution_control import local
from workbench.project_delivery import project_source_paths
from workbench.project_runner import ProjectEvalRunner, ProjectExecutionRunner


class ProjectOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'project'
        self.runtime = self.root / 'runtime'
        self.source.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=self.source, check=True, capture_output=True, timeout=10)
        (self.source / '中文 空格.bin').write_bytes(b'\x00\xff\r\n')
        self.task = {'id': 'TASK-verify-only', 'execution_mode': 'verify', 'business_refs': ['PROJECT:fixture']}

    def eval_runner(self, script):
        projects = Mock()
        projects.get.return_value = {'id': 'fixture', 'root_path': str(self.source),
                                     'eval_command': [sys.executable, '-u', '-c', script]}
        return ProjectEvalRunner(projects, self.runtime).for_task(self.task)

    def test_source_manifest_keeps_unicode_names_and_raw_nul_receipt(self):
        paths = project_source_paths(self.source, self.runtime)
        self.assertEqual(['中文 空格.bin'], [path.name for path in paths])
        receipt_path, = (self.runtime / 'git-processes').rglob('process.json')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        raw = Path(receipt['stdout_path']).read_bytes()
        self.assertEqual('中文 空格.bin'.encode('utf-8') + b'\x00', raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['stdout_sha256'])
        self.assertTrue(receipt['success'])
        self.assertEqual(0, receipt['returncode'])

    def test_verify_only_eval_rejects_an_empty_green_report(self):
        report = {'summary': {'total': 0, 'passed': 0, 'blocking_failed': 0, 'observing_failed': 0, 'decision': 'pass'}, 'results': []}
        with self.assertRaisesRegex(RuntimeError, '非空分项'):
            self.eval_runner(f'print({json.dumps(json.dumps(report))})')()
        self.assertEqual(1, len(list((self.runtime / 'project-reports').rglob('raw-report.json'))))

    def test_tampered_candidate_cannot_redirect_code_or_eval_to_registered_source(self):
        projects = Mock()
        projects.get.return_value = {'id': 'fixture', 'root_path': str(self.source), 'eval_command': ['must-not-run']}
        path = self.runtime / 'candidates' / self.task['id'] / 'project.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'project_id': 'fixture', 'workspace': str(self.source)}), encoding='utf-8')
        task = dict(self.task, execution_mode='codex')
        with patch('workbench.project_runner.CodexExecutionRunner') as coding:
            with self.assertRaisesRegex(ValueError, '候选工作区路径'):
                ProjectExecutionRunner(projects, self.runtime)(task)
            coding.assert_not_called()
        with self.assertRaisesRegex(ValueError, '候选工作区路径'):
            ProjectEvalRunner(projects, self.runtime).for_task(task)()
        self.assertEqual(b'\x00\xff\r\n', (self.source / '中文 空格.bin').read_bytes())
        self.assertFalse((self.runtime / 'project-reports').exists())

    def test_verify_only_eval_cancels_the_registered_real_process(self):
        marker = self.root / 'eval-ready'
        script = f'import pathlib,time;pathlib.Path({str(marker)!r}).write_text("ready");time.sleep(30)'
        run = self.eval_runner(script)
        results, errors, processes = [], [], []
        stop = threading.Event()

        def capture(*args, **kwargs):
            value = spawn_owned_process(*args, **kwargs)
            processes.append(value)
            return value

        def work():
            local.cancel_event = stop
            try: results.append(run())
            except Exception as error: errors.append(error)
            finally: local.cancel_event = None

        worker = threading.Thread(target=work, daemon=True)
        try:
            with patch('workbench.execution.spawn_owned_process', side_effect=capture):
                worker.start()
                deadline = time.monotonic() + 10
                while not marker.exists() and worker.is_alive() and time.monotonic() < deadline:
                    stop.wait(.02)
                self.assertTrue(marker.exists(), errors)
                stop.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual([], results)
            self.assertEqual(1, len(errors))
            receipts = [json.loads(path.read_text(encoding='utf-8'))
                        for path in (self.runtime / 'project-reports').rglob('process.json')]
            self.assertEqual([130], [receipt['returncode'] for receipt in receipts])
            self.assertTrue(processes)
            for process, owner, _ in processes:
                self.assertIsNotNone(process.poll())
                self.assertTrue(all(getattr(process, name).closed for name in ('stdin', 'stdout', 'stderr')))
                if owner: self.assertIsNone(owner.handle)
            self.assertEqual(b'\x00\xff\r\n', (self.source / '中文 空格.bin').read_bytes())
        finally:
            stop.set()
            worker.join(5)
            for process, owner, _ in processes:
                if owner: owner.close()
                if process.poll() is None: process.kill()
                process.wait(timeout=5)
                for name in ('stdin', 'stdout', 'stderr'): getattr(process, name).close()


if __name__ == '__main__':
    unittest.main()
