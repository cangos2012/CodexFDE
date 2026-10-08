"""Real local Eval startup/cleanup faults; no model or human acceptance."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from workbench.eval_harness import fingerprint
from workbench.execution import spawn_owned_process
from workbench.file_io import atomic_write_text
from workbench.project_delivery import CandidateProjectEval


class ProjectEvalFailureTests(unittest.TestCase):
    def assert_failed_attempt(self, *, deny_receipt=False, fail_owner=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, runtime = root / 'candidate', root / 'runtime'
            workspace.mkdir()
            runtime.mkdir()
            subprocess.run(['git', 'init', '--quiet', str(workspace)], check=True,
                           capture_output=True, timeout=10)
            source = b'original candidate\n'
            (workspace / 'value.txt').write_bytes(source)
            task_id = 'TASK-engineering-eval-failure'
            spec = runtime / 'Spec.md'
            spec.write_text('Engineering fixture; no human acceptance.', encoding='utf-8')
            with closing(sqlite3.connect(runtime / 'workbench.db')) as db:
                with db:
                    db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,spec_path TEXT NOT NULL)')
                    db.execute('INSERT INTO tasks VALUES(?,?)', (task_id, str(spec)))
            report = {'summary': {'total': 1, 'passed': 1, 'decision': 'pass',
                                 'blocking_failed': 0, 'observing_failed': 0},
                      'results': [{'name': 'engineering-local-process', 'level': 'blocking',
                                   'passed': True, 'evidence': 'Synthetic local fixture only.'}]}
            code = ('import json;print(json.dumps(' + repr(report) + '))' if fail_owner
                    else 'import time;time.sleep(30)')
            configured = [sys.executable, '-X', 'utf8', '-c', code, '{workspace}', '{report_path}']
            evaluator = CandidateProjectEval(workspace, runtime, task_id, configured, 'engineering-fault', timeout=10)
            original_failure = RuntimeError('engineering Eval second reader start failure')
            captured, commands, streams = [], [], []
            actual_start = threading.Thread.start
            eval_active, reader_count = False, 0

            class FailingClose:
                def __init__(self, owner): self.owner, self.calls = owner, 0
                def close(self):
                    self.calls += 1
                    if self.calls == 1:
                        raise OSError('engineering Eval owner close failure')
                    self.owner.close()

            def capture(command, *args, **kwargs):
                nonlocal eval_active
                process, owner, prefix = spawn_owned_process(command, *args, **kwargs)
                eval_active = command[0] == sys.executable
                if eval_active:
                    if fail_owner:
                        owner = FailingClose(owner)
                    captured.append((process, owner, prefix))
                    commands.append(list(command))
                return process, owner, prefix

            def start(thread):
                nonlocal reader_count
                target = getattr(thread._target, '__name__', '')
                if eval_active and target == 'drain':
                    reader_count += 1
                    if not fail_owner and reader_count == 2:
                        raise original_failure
                actual_start(thread)
                if eval_active and target in {'drain', 'feed'}:
                    streams.append(thread)

            def persist(path, content, *args, **kwargs):
                if deny_receipt and 'project-reports' in Path(path).parts:
                    raise PermissionError('engineering Eval receipt permanent denial')
                return atomic_write_text(path, content, *args, **kwargs)

            try:
                with patch('workbench.execution.spawn_owned_process', side_effect=capture), \
                     patch.object(threading.Thread, 'start', start), \
                     patch('workbench.file_io.atomic_write_text', side_effect=persist), \
                     patch('logging.Logger.error') as log_error, \
                     self.assertRaises(RuntimeError) as raised:
                    evaluator()
                if fail_owner:
                    self.assertIn('engineering Eval owner close failure', str(raised.exception))
                else:
                    self.assertIs(original_failure, raised.exception)
                folders = list((runtime / 'project-reports' / task_id).iterdir())
                self.assertEqual(1, len(folders))
                self.assertFalse((folders[0] / 'report.json').exists())
                self.assertFalse((folders[0] / 'raw-report.json').exists())
                path = folders[0] / 'process.json'
                if deny_receipt:
                    self.assertFalse(path.exists())
                    if hasattr(raised.exception, 'add_note'):
                        self.assertTrue(any('engineering Eval receipt permanent denial' in note
                                            for note in getattr(raised.exception, '__notes__', [])))
                    else:
                        self.assertTrue(any('engineering Eval receipt permanent denial' in str(call)
                                            for call in log_error.call_args_list))
                else:
                    receipt = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual('failed', receipt['status'])
                    self.assertFalse(receipt['success'])
                    self.assertIsNone(receipt['returncode'])
                    self.assertFalse(receipt['process_result_available'])
                    self.assertEqual(type(raised.exception).__name__, receipt['exception_type'])
                    self.assertEqual(str(raised.exception), receipt['error'])
                    self.assertEqual(commands[0], receipt['command'])
                    self.assertEqual(str(workspace), receipt['cwd'])
                    self.assertEqual(str(path.parent / 'report.json'), receipt['command'][-1])
                    self.assertEqual(fingerprint({'value.txt': hashlib.sha256(source).hexdigest()}),
                                     receipt['candidate_sha256'])
                    expected_contract = {'task_id': task_id,
                        'spec_sha256': hashlib.sha256(spec.read_bytes()).hexdigest(),
                        'configuration_sha256': hashlib.sha256(json.dumps(configured, ensure_ascii=False,
                                                                         sort_keys=True).encode()).hexdigest()}
                    self.assertEqual(expected_contract, receipt['contract'])
                self.assertEqual(source, (workspace / 'value.txt').read_bytes())
                self.assertEqual(1, len(captured))
                process, owner, _ = captured[0]
                self.assertIsNotNone(process.poll())
                if fail_owner:
                    self.assertEqual(0, process.returncode)
                self.assertTrue(all(getattr(process, name).closed for name in ('stdin', 'stdout', 'stderr')))
                self.assertTrue(all(not stream.is_alive() for stream in streams))
                if owner:
                    actual_owner = owner.owner if fail_owner else owner
                    self.assertIsNone(actual_owner.handle)
                    if fail_owner:
                        self.assertGreaterEqual(owner.calls, 2)
            finally:
                # Reclaim only the fixture's captured processes, including on red.
                for process, owner, _ in captured:
                    if owner: owner.close()
                    if process.poll() is None: process.kill()
                    process.wait(timeout=5)
                for stream in streams: stream.join(5)
                for process, _, _ in captured:
                    for name in ('stdin', 'stdout', 'stderr'):
                        getattr(process, name).close()

    def test_second_reader_start_failure_records_bound_failed_attempt_and_closes_process(self):
        self.assert_failed_attempt()

    def test_receipt_denial_adds_note_and_preserves_original_stream_failure(self):
        self.assert_failed_attempt(deny_receipt=True)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job owner fault injection')
    def test_owner_cleanup_failure_records_failed_attempt_even_after_successful_exit(self):
        self.assert_failed_attempt(fail_owner=True)


if __name__ == '__main__':
    unittest.main()
