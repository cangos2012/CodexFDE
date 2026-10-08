from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from workbench.delivery_runtime import RuntimeShellProvider
from workbench.shell_provider import LocalShellProvider, command_allowed, execution_command


class ShellProviderDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.original = root / 'registered-source'
        self.original.mkdir()
        self.source = self.original / 'source.txt'
        self.source.write_bytes(b'registered source must remain unchanged\n')
        self.candidate = root / 'candidate'
        self.candidate.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.candidate / 'value.txt').write_text('before\n', encoding='utf-8')
        (self.candidate / '.gitattributes').write_text('*.txt diff=fixture\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')
        (self.candidate / 'value.txt').write_text('after\n', encoding='utf-8')
        # Any accidental external diff/textconv invocation makes a real Git
        # command fail; diagnostics must use Git's built-in comparison.
        self.git('config', 'diff.fixture.command', 'fixture-external-command-must-not-run')
        self.git('config', 'diff.fixture.textconv', 'fixture-textconv-command-must-not-run')

    def git(self, *arguments):
        return subprocess.run(['git', *arguments], cwd=self.candidate, check=True,
                              capture_output=True, text=True)

    def providers(self):
        return (LocalShellProvider(), RuntimeShellProvider(threading.Event()))

    def test_output_file_is_rejected_before_either_provider_changes_registered_source(self):
        before = self.source.read_bytes()
        for provider in self.providers():
            for subcommand in ('status', 'diff', 'log'):
                for suffix in ([f'--output={self.source}'], ['--output', str(self.source)],
                               [f'--out={self.source}']):
                    with self.subTest(provider=type(provider).__name__, command=subcommand, suffix=suffix):
                        with self.assertRaisesRegex(ValueError, '允许列表'):
                            provider.exec(self.candidate, ['git', subcommand, *suffix])
                        self.assertEqual(before, self.source.read_bytes())

    def test_external_diff_textconv_and_no_index_options_and_abbreviations_are_rejected(self):
        for subcommand in ('status', 'diff', 'log'):
            for option in ('--ext-diff', '--ext-diff=true', '--ext', '--textconv',
                           '--textconv=true', '--text', '--no-index', '--no-index=true', '--no-i'):
                with self.subTest(command=subcommand, option=option):
                    self.assertFalse(command_allowed(['git', subcommand, option]))
                    with self.assertRaises(ValueError):
                        execution_command(['git', subcommand, option])

    def test_regular_diagnostics_work_and_keep_original_request_in_receipt(self):
        before = self.source.read_bytes()
        for provider in self.providers():
            for command in (['git', 'status', '--porcelain'], ['git', 'diff', '--', 'value.txt'],
                            ['git', 'log', '-p', '-1']):
                with self.subTest(provider=type(provider).__name__, command=command):
                    result = provider.exec(self.candidate, command)
                    self.assertEqual(0, result['returncode'], result['stderr'])
                    self.assertEqual(command, result['command'])
                    self.assertEqual(execution_command(command), result['executed_command'])
                    if command[1] == 'status':
                        self.assertEqual(command, result['executed_command'])
                    else:
                        self.assertEqual(['--no-ext-diff', '--no-textconv'], result['executed_command'][2:4])
                    self.assertTrue(result['stdout'])
                    self.assertEqual(before, self.source.read_bytes())
        self.assertIn('--no-ext-diff', execution_command(['git', 'diff']))
        self.assertIn('--no-textconv', execution_command(['git', 'log']))


if __name__ == '__main__':
    unittest.main()
