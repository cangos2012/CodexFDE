from pathlib import Path
import tempfile
import unittest
import json
import hashlib
import subprocess
import os
import sys
from unittest.mock import patch

from workbench.setup_desktop import prepare_materials, prepare, initialize_reference, run as setup_run


class SetupDesktopTests(unittest.TestCase):
    def test_component_check_succeeds_when_customer_package_is_unavailable(self):
        # Skip installation and material setup; execute the real component check
        # in a child process that cannot import the independent customer package.
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True)
            python.touch()
            checks = []

            def run_step(command, cwd):
                if '-c' not in command:
                    return ''
                checks.append(command)
                code = (f'import sys; sys.path.insert(0, {str(repository)!r}); '
                        "sys.modules['flowerp'] = None; " + command[-1])
                return setup_run([sys.executable, '-X', 'utf8', '-c', code], cwd)

            with patch('workbench.setup_desktop.prepare_materials'), \
                 patch('workbench.setup_desktop.run', side_effect=run_step):
                self.assertEqual(0, prepare(root))
            self.assertEqual(1, len(checks))
            self.assertFalse((root / '.runtime/startup-logs/environment-setup.log').exists())

    def reference_fixture(self, root):
        subprocess.run(['git', 'init', '--quiet'], cwd=root, check=True)
        (root / 'source.txt').write_bytes(b'reference\n')
        (root / 'package-manifest.json').write_text(json.dumps({'schema_version': 1, 'files': {
            'source.txt': hashlib.sha256(b'reference\n').hexdigest()}}), encoding='utf-8')

    def test_initial_commit_excludes_extra_files_and_preserves_later_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.reference_fixture(root)
            (root / 'private.txt').write_text('must remain untracked')
            initialize_reference(root)
            tracked = subprocess.check_output(['git', 'ls-tree', '--name-only', 'HEAD'], cwd=root).decode()
            self.assertNotIn('private.txt', tracked)
            self.assertIn('source.txt', tracked)
            (root / 'source.txt').write_bytes(b'learner modification\n')
            initialize_reference(root)
            diff = subprocess.check_output(['git', 'diff', '--', 'source.txt'], cwd=root).decode()
            self.assertIn('+learner modification', diff)

    def test_changed_distribution_is_not_claimed_as_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.reference_fixture(root)
            (root / 'source.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '文件已经变化'):
                initialize_reference(root)
            self.assertFalse((root / '.git/index').exists())

    def test_preexisting_staging_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.reference_fixture(root)
            subprocess.run(['git', 'add', 'source.txt'], cwd=root, check=True)
            original = (root / '.git/index').read_bytes()
            with self.assertRaisesRegex(RuntimeError, '已有暂存修改'):
                initialize_reference(root)
            self.assertEqual(original, (root / '.git/index').read_bytes())

    def test_archive_without_bundle_does_not_adopt_parent_repository(self):
        with tempfile.TemporaryDirectory() as directory, patch('workbench.setup_desktop.shutil.which', return_value='git'), patch('workbench.setup_desktop.run') as run:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, '缺少版本记录'):
                prepare_materials(root)
            run.assert_not_called()
            self.assertFalse((root / '.git').exists())

    def test_fetch_refusal_stops_before_installation_without_force(self):
        with tempfile.TemporaryDirectory() as directory, patch('workbench.setup_desktop.shutil.which', return_value='git'), patch('workbench.setup_desktop.run', side_effect=RuntimeError('tag conflict')) as run:
            root = Path(directory)
            (root / '.git').mkdir()
            (root / 'course-materials.bundle').write_bytes(b'fixture')
            with self.assertRaisesRegex(RuntimeError, 'tag conflict'):
                prepare(root)
            self.assertEqual(1, run.call_count)
            command = run.call_args.args[0]
            self.assertIn('--atomic', command)
            self.assertNotIn('--force', command)
            self.assertFalse((root / '.venv').exists())

    def test_incomplete_environment_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch('workbench.setup_desktop.prepare_materials'), patch('workbench.setup_desktop.run') as run:
            root = Path(directory)
            (root / '.venv').mkdir()
            marker = root / '.venv' / 'keep.txt'
            marker.write_text('keep')
            with self.assertRaisesRegex(RuntimeError, '不会自动删除'):
                prepare(root)
            self.assertEqual('keep', marker.read_text())
            run.assert_not_called()
