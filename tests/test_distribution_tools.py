"""Exercise real source packages and external-process audit boundaries."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from workbench.package_desktop import build
from scripts import prepare_erp_page_audit as page_audit
from scripts import sync_outline_contracts
from scripts.prepare_l15_export_audit import validate_initial_failure


class DistributionTests(unittest.TestCase):
    def test_l15_baseline_requires_the_actual_missing_behavior(self):
        report = {'summary': {'blocking_failed': 1, 'decision': 'block'}, 'results': [{
            'name': 'inventory_empty_export_retains_schema', 'passed': False, 'level': 'blocking',
            'error': {'type': 'AssertionError', 'message': '空库存导出必须保留列名'}}]}
        validate_initial_failure(report, 1)
        with self.assertRaises(ValueError):
            validate_initial_failure(report, 0)
        report['results'][0]['error']['type'] = 'ModuleNotFoundError'
        with self.assertRaises(ValueError):
            validate_initial_failure(report, 1)
        report['results'][0]['error'] = {'type': 'AssertionError',
            'message': 'assert check(), "空库存导出必须保留列名"\nNameError: check is not defined'}
        with self.assertRaises(ValueError):
            validate_initial_failure(report, 1)
        report['results'][0]['passed'] = True
        with self.assertRaisesRegex(ValueError, '已经通过'):
            validate_initial_failure(report, 0)

    def test_contract_sync_reads_lesson_number_from_all_canonical_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chapter = root / 'docs/courses/L16/辅导资料.md'
            chapter.parent.mkdir(parents=True)
            chapter.write_text('# Old title\n\nKeep the real example.\n', encoding='utf-8')
            with patch.object(sync_outline_contracts, 'ROOT', root), \
                 patch.object(sync_outline_contracts, 'outline_contracts', return_value={16: ('Current title', [])}):
                sync_outline_contracts.main()
            body = chapter.read_text(encoding='utf-8')
            self.assertTrue(body.startswith('# L16｜Current title'))
            self.assertIn('Keep the real example.', body)

    def test_source_package_builds_without_embedded_customer_and_preserves_existing_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            for name in ('首次使用.cmd', '打开工作台.cmd', 'workbench/setup_desktop.py',
                         'workbench/__init__.py', 'workbench/cli.py', 'eval/__init__.py',
                         'eval/harness.py', 'workbench_web/index.html', 'docs/courses/session-versions.json'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}' if name.endswith('.json') else '# fixture\n', encoding='utf-8')
            def git(*args, **kwargs):
                return subprocess.run(['git', *args], cwd=root, capture_output=True, check=True, **kwargs)
            git('init', '--quiet')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost', '-c', 'commit.gpgsign=false',
                'commit', '--quiet', '-m', 'Fixture')
            sha = git('rev-parse', 'HEAD').stdout.decode().strip()
            git('update-ref', '--stdin', input=''.join(f'create refs/tags/course/l{n:02d}-start {sha}\n'
                                                     for n in range(1, 17)).encode())
            output = Path(directory) / 'course.zip'
            with patch('workbench.package_desktop.default_session_version',
                       side_effect=lambda _root, n: {'ref': f'course/l{n:02d}-start'}):
                result = build(root, output)
            self.assertGreater(result['bytes'], 0)
            with zipfile.ZipFile(output) as archive:
                self.assertIn('课程工作台/workbench_web/index.html', archive.namelist())
                self.assertNotIn('课程工作台/web/index.html', archive.namelist())
                self.assertIn('独立客户项目', archive.read('课程工作台/先读我.md').decode())
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                build(root, output)
            self.assertEqual(original, output.read_bytes())

    def test_page_audit_dispatches_to_customer_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'audit'
            with patch.object(page_audit, 'flowerp_root', return_value=root), \
                 patch.object(page_audit, 'python_for', return_value='customer-python'), \
                 patch.object(page_audit.subprocess, 'run') as run:
                run.return_value = subprocess.CompletedProcess([], 0, '{"purchase_id":"fixture"}', '')
                self.assertEqual('fixture', page_audit.prepare(runtime)['purchase_id'])
                self.assertEqual('customer-python', run.call_args.args[0][0])
                self.assertEqual(root, run.call_args.kwargs['cwd'])
                self.assertEqual(str(runtime), json.loads(run.call_args.kwargs['input'])['runtime'])
                run.return_value = subprocess.CompletedProcess([], 2, '', 'business check failed')
                with self.assertRaisesRegex(RuntimeError, 'business check failed'):
                    page_audit.prepare(runtime)
            runtime.mkdir()
            database = runtime / 'flowerp.db'
            database.write_bytes(b'keep-existing-evidence')
            with patch.object(page_audit, 'flowerp_root') as resolve:
                with self.assertRaises(FileExistsError):
                    page_audit.prepare(runtime)
                resolve.assert_not_called()
            self.assertEqual(b'keep-existing-evidence', database.read_bytes())
