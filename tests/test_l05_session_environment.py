"""Run the session helper against real venvs; this is maintenance evidence."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
import venv


EXAMPLES = Path(__file__).resolve().parents[1] / 'docs/courses/L05/examples'


class SessionEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.windows = os.name == 'nt'
        cls.shell = (shutil.which('powershell') or shutil.which('pwsh')) if cls.windows else shutil.which('zsh')
        if not cls.shell or not shutil.which('git'):
            raise unittest.SkipTest('A native course shell and Git are required')
        cls.reference_temp = tempfile.TemporaryDirectory(prefix='l05-reference-')
        cls.reference = Path(cls.reference_temp.name) / '参考 environment'
        venv.create(cls.reference, with_pip=False)
        cls.python = cls.reference / ('Scripts/python.exe' if cls.windows else 'bin/python')

    @classmethod
    def tearDownClass(cls):
        cls.reference_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='l05-control-')
        self.addCleanup(self.temp.cleanup)
        self.control = Path(self.temp.name) / '课程 control'
        self.control.mkdir()
        package = self.control / 'workbench'
        package.mkdir()
        (package / '__init__.py').write_text('# Environment-selection fixture\n', encoding='utf8')
        self.examples = self.control / 'docs/courses/L05/examples'
        self.examples.mkdir(parents=True)
        for name in ('session.ps1', 'session.zsh', 'record_command.py'):
            shutil.copy2(EXAMPLES / name, self.examples / name)
        for args in (['init', '-q'], ['config', 'user.name', 'Maintenance QA'],
                     ['config', 'user.email', 'maintenance@example.invalid']):
            subprocess.run(['git', '-C', str(self.control), *args], check=True, capture_output=True)
        self.pointer = self.control / '.runtime/l05-practice/latest-session.txt'
        self.probe_number = 0

    def run_helper(self, *, resume=None, latest=False, activated=True):
        self.probe_number += 1
        output = Path(self.temp.name) / f'probe-{self.probe_number}.json'
        environment = os.environ.copy()
        environment.pop('VIRTUAL_ENV', None)
        if activated:
            environment['VIRTUAL_ENV'] = str(self.reference)
        if self.windows:
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            invocation = '. ' + quote(self.examples / 'session.ps1')
            if latest:
                invocation += ' -Latest'
            elif resume:
                invocation += ' -Resume ' + quote(resume)
            code = ("$ErrorActionPreference = 'Stop'\ntry {\n" + invocation + '\n'
                    + '$l05Session | ConvertTo-Json -Compress | Set-Content -Encoding utf8 -LiteralPath '
                    + quote(output) + '\n} catch { [Console]::Error.WriteLine($_); exit 1 }\n')
            script = Path(self.temp.name) / f'probe-{self.probe_number}.ps1'
            script.write_text(code, encoding='utf-8-sig')
            command = [self.shell, '-NoProfile', '-NonInteractive', '-File', str(script)]
        else:
            invocation = 'source ' + shlex.quote(str(self.examples / 'session.zsh'))
            if latest:
                invocation += ' --latest'
            elif resume:
                invocation += ' ' + shlex.quote(str(resume))
            code = invocation + ' || exit $?\n' + 'printf \'%s\\n\' "$l05Session" > ' + shlex.quote(str(output)) + '\n'
            script = Path(self.temp.name) / f'probe-{self.probe_number}.zsh'
            script.write_text(code, encoding='utf8')
            command = [self.shell, '-f', str(script)]
        result = subprocess.run(command, cwd=self.control, env=environment,
                                capture_output=True, text=True, encoding='utf8', timeout=60)
        session = json.loads(output.read_text('utf-8-sig')) if output.exists() else None
        return result, session

    def test_activated_reference_environment_creates_and_resumes_same_session(self):
        result, session = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        # macOS may canonicalize /var to /private/var; resolving the launcher
        # itself would instead hide that different venvs share a base Python.
        launcher = Path(session['python'])
        self.assertEqual(launcher.parent.parent.resolve(), self.reference.resolve())
        self.assertEqual(launcher.name, self.python.name)
        self.assertEqual(Path(session['control']).resolve(), self.control.resolve())
        saved = Path(self.pointer.read_text('utf-8-sig').strip())
        before = saved.read_bytes()
        for arguments in ({'latest': True}, {'resume': saved}):
            with self.subTest(arguments=arguments):
                result, resumed = self.run_helper(**arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(resumed, session)
                self.assertEqual(saved.read_bytes(), before)
        self.assertFalse((self.control / '.venv').exists())

    def test_missing_venv_rejects_before_creating_session(self):
        result, session = self.run_helper(activated=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(session)
        self.assertFalse(self.pointer.exists())

    def test_resume_keeps_borrowed_environment_after_local_venv_is_created(self):
        result, session = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = Path(self.pointer.read_text('utf-8-sig').strip())
        before = saved.read_bytes()
        venv.create(self.control / '.venv', with_pip=False)
        result, resumed = self.run_helper(latest=True, activated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(resumed, session)
        self.assertEqual(saved.read_bytes(), before)

    def test_resume_rejects_different_control_or_interpreter_and_preserves_evidence(self):
        result, session = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = Path(self.pointer.read_text('utf-8-sig').strip())
        original_bytes = original.read_bytes()
        for field, value in (('control', str(Path(self.temp.name))),
                             ('python', str(Path(self.temp.name) / 'other-python'))):
            with self.subTest(field=field):
                edited = dict(session, **{field: value})
                candidate = Path(self.temp.name) / f'mismatched-{field}.json'
                candidate.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf8')
                before = candidate.read_bytes()
                result, restored = self.run_helper(resume=candidate)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(restored)
                self.assertEqual(candidate.read_bytes(), before)
                self.assertEqual(original.read_bytes(), original_bytes)
                self.assertEqual(Path(self.pointer.read_text('utf-8-sig').strip()), original)


if __name__ == '__main__':
    unittest.main()
