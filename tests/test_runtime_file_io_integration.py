"""Read-lock recovery must preserve current evidence and reject real changes."""
from contextlib import contextmanager
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from workbench import ci_evidence, file_io, quality_hook, workbench_backup
from workbench.task_store import TaskStore


@contextmanager
def transient_read_lock(path, replacement=None):
    original = Path.open
    attempts = []

    def opened(target, *args, **kwargs):
        mode = args[0] if args else kwargs.get('mode', 'r')
        if target == path and mode in {'r', 'rt', 'rb'}:
            attempts.append(mode)
            if len(attempts) == 1:
                if replacement is not None:
                    with original(target, 'wb') as output:
                        output.write(replacement)
                raise PermissionError(errno.EACCES, 'temporary evidence sharing lock')
        return original(target, *args, **kwargs)

    with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', opened), \
            patch.object(file_io.time, 'sleep'):
        yield attempts


class RuntimeReadIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='runtime-read-integration-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def stock_module(self):
        source = Path(__file__).resolve().parents[1] / 'docs/courses/L06/examples/stock_practice.py'
        spec = importlib.util.spec_from_file_location('stock_read_integration', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_ci_envelope_hashes_changed_disk_report_after_temporary_lock(self):
        report = self.root / 'report.json'
        report.write_text('{"suite":"blocking","summary":{"decision":"pass"}}', encoding='utf-8')
        changed = b'{"suite":"blocking","summary":{"decision":"block"}}'
        with transient_read_lock(report, changed) as attempts:
            envelope = ci_evidence.build_envelope(report, env={'GITHUB_SHA': 'abc', 'GITHUB_RUN_ID': '1'})
        self.assertEqual(2, len(attempts))
        self.assertEqual('block', envelope['report_decision'])
        self.assertEqual(hashlib.sha256(changed).hexdigest(), envelope['report_sha256'])

    def test_persistent_ci_report_denial_does_not_publish_an_envelope(self):
        report, output = self.root / 'report.json', self.root / 'envelope.json'
        report.write_text('{}', encoding='utf-8')
        original = Path.open

        def denied(target, *args, **kwargs):
            if target == report:
                raise PermissionError(errno.EACCES, 'persistent evidence denial')
            return original(target, *args, **kwargs)

        arguments = ['ci-evidence', '--report', str(report), '--output', str(output)]
        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', denied), \
                patch.object(file_io.time, 'sleep'), patch.object(sys, 'argv', arguments), \
                patch.dict(os.environ, {'GITHUB_SHA': 'abc', 'GITHUB_RUN_ID': '1'}):
            with self.assertRaises(PermissionError):
                ci_evidence.main()
        self.assertFalse(output.exists())

    def test_hook_retry_does_not_hide_binding_tampering(self):
        candidate = self.root / 'candidate'
        (candidate / '.git').mkdir(parents=True)
        project = {'id': 'PROJECT-fixture', 'root_path': str(self.root / 'source'),
                   'eval_command': [sys.executable, '-B', 'check.py']}
        package = quality_hook.prepare(self.root / 'runtime', candidate, project,
                                       'TASK-fixture', 'INIT-fixture', 'fixture-preparer')
        binding = Path(package['path']) / 'binding.json'
        with transient_read_lock(binding) as attempts:
            view = quality_hook.view(package, candidate, 'TASK-fixture')
        self.assertEqual('prepared', view['status'])
        self.assertGreaterEqual(len(attempts), 2)
        binding.write_text('{}', encoding='utf-8')
        self.assertEqual('unavailable', quality_hook.view(package, candidate, 'TASK-fixture')['status'])

    def test_hook_preparation_rejects_files_changed_during_read_retry(self):
        for filename in ('binding.json', 'quality_gate.py', 'hooks.json'):
            with self.subTest(file=filename):
                candidate = self.root / filename / 'candidate'
                (candidate / '.git').mkdir(parents=True)
                project = {'id': 'PROJECT-fixture', 'root_path': str(self.root / 'source'),
                           'eval_command': [sys.executable, '-B', 'check.py']}
                original = Path.open
                altered = []

                def changed(target, *args, **kwargs):
                    mode = args[0] if args else kwargs.get('mode', 'r')
                    if target.name == filename and mode == 'rb' and not altered:
                        altered.append(target)
                        with original(target, 'wb') as output:
                            output.write(b'{}')
                        raise PermissionError(errno.EACCES, 'sharing lock during tampering')
                    return original(target, *args, **kwargs)

                with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', changed), \
                        patch.object(file_io.time, 'sleep'):
                    with self.assertRaisesRegex(ValueError, '准备期间'):
                        quality_hook.prepare(self.root / filename / 'runtime', candidate, project,
                                             'TASK-fixture', 'INIT-fixture', 'fixture-preparer')
                self.assertEqual(1, len(altered))

    def test_backup_hash_reads_in_bounded_chunks(self):
        evidence = self.root / 'large-evidence.bin'
        content = b'evidence-block' * 180000
        evidence.write_bytes(content)
        original = workbench_backup.open_read
        reads = []
        case = self

        class BoundedReader:
            def __init__(self, source):
                self.source = source

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.source.close()

            def read(self, size):
                case.assertGreater(size, 0)
                case.assertLessEqual(size, 1024 * 1024)
                reads.append(size)
                return self.source.read(size)

        def streamed(path, mode='rb'):
            return BoundedReader(original(path, mode))

        with patch.object(workbench_backup, 'open_read', streamed):
            actual = workbench_backup._hash(evidence)
        self.assertEqual(hashlib.sha256(content).hexdigest(), actual)
        self.assertGreater(len(reads), 2)

    def test_backup_verification_recovers_a_temporary_archive_lock(self):
        runtime = self.root / 'runtime'
        TaskStore(runtime / 'workbench.db')
        report = runtime / 'reports' / 'evidence.json'
        report.parent.mkdir()
        report.write_text('{"source":"isolated fixture"}', encoding='utf-8')
        result = workbench_backup.BackupService(runtime).create('fixture-maintainer')
        archive = Path(result['archive_path'])
        with transient_read_lock(archive) as attempts:
            verified = workbench_backup.verify_backup(archive)
        self.assertTrue(verified['ok'])
        self.assertEqual(2, len(attempts))
        self.assertEqual(2, verified['files_verified'])

    def test_stock_hash_uses_current_bytes_and_preserves_newline_policy(self):
        stock = self.stock_module()
        source = self.root / 'service.py'
        source.write_bytes(b'value = 1\r\n')
        changed = b'value = 2\r\n'
        with transient_read_lock(source, changed) as attempts:
            digest = stock.sha(source)
        self.assertEqual(2, len(attempts))
        self.assertEqual(hashlib.sha256(changed.replace(b'\r\n', b'\n')).hexdigest(), digest)
        self.assertNotEqual(hashlib.sha256(b'value = 1\n').hexdigest(), digest)

    def test_stock_session_read_recovers_lock_and_keeps_bom_support(self):
        stock = self.stock_module()
        session = self.root / 'session.json'
        value = {'candidate': str(self.root / 'candidate'), 'scope': 'isolated fixture'}
        session.write_text(json.dumps(value), encoding='utf-8-sig')
        with transient_read_lock(session) as attempts:
            actual = stock.read(session)
        self.assertEqual(2, len(attempts))
        self.assertEqual(value, actual)


if __name__ == '__main__':
    unittest.main()
