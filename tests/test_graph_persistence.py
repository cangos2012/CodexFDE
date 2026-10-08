"""Graph approvals retain the last durable state when metadata writes fail."""
import errno
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from agent import graph
from workbench import file_io

REAL_SLEEP = time.sleep


class GraphPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='graph-persistence-')
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'graph' / 'delivery.json'
        report = {'summary': {'blocking_failed': 0, 'decision': 'pass'}}
        with patch.object(graph, 'run_suite', return_value=report):
            pending = graph.run_graph(state_file=self.path, require_human_review=True)
        self.assertEqual('awaiting_human_review', pending['status'])
        self.before = file_io.read_bytes(self.path)

    @staticmethod
    def denied():
        error = PermissionError(errno.EACCES, 'fixture Windows metadata sharing lock')
        error.winerror = 32
        return error

    def reject_direct_overwrite(self, target, mode='r', *args, **kwargs):
        if target == self.path and any(value in mode for value in 'wax+'):
            raise self.denied()
        return self.original_open(target, mode, *args, **kwargs)

    def test_named_approval_is_durable_without_rerunning_eval(self):
        with patch.object(graph, 'run_suite') as suite:
            approved = graph.run_graph(state_file=self.path, review_decision='approve', reviewer='fixture-reviewer')
        suite.assert_not_called()
        persisted = json.loads(file_io.read_bytes(self.path))
        self.assertEqual(approved, persisted)
        self.assertEqual('completed', persisted['status'])
        self.assertEqual('fixture-reviewer', persisted['reviewer'])
        self.assertEqual('approve', persisted['review_decision'])
        self.assertTrue(persisted['reviewed_at'])
        self.assertEqual('awaiting_human_review', persisted['trace'][-1]['from'])

    def test_transient_replace_lock_retries_and_keeps_old_state_until_install(self):
        self.original_open = Path.open
        original_replace = Path.replace
        attempts = []

        def replace(source, target):
            self.assertEqual(self.path, target)
            self.assertEqual(self.before, file_io.read_bytes(self.path))
            attempts.append(source)
            if len(attempts) == 1:
                raise self.denied()
            return original_replace(source, target)

        def opened(target, mode='r', *args, **kwargs):
            return self.reject_direct_overwrite(target, mode, *args, **kwargs)

        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', opened), \
                patch.object(Path, 'replace', replace), patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep, \
                patch.object(graph, 'run_suite') as suite:
            approved = graph.run_graph(state_file=self.path, review_decision='approve', reviewer='fixture-reviewer')
        suite.assert_not_called()
        self.assertEqual(2, len(attempts))
        sleep.assert_called_once_with(file_io._READ_DELAYS[0])
        self.assertEqual('completed', approved['status'])
        self.assertEqual(approved, json.loads(file_io.read_bytes(self.path)))
        self.assertEqual([self.path], list(self.path.parent.iterdir()))

    def test_permanent_replace_denial_retains_awaiting_review_bytes(self):
        self.original_open = Path.open
        denied = self.denied()

        def opened(target, mode='r', *args, **kwargs):
            return self.reject_direct_overwrite(target, mode, *args, **kwargs)

        with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', opened), \
                patch.object(Path, 'replace', side_effect=denied) as replace, \
                patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP) as sleep, patch.object(graph, 'run_suite') as suite:
            with self.assertRaises(PermissionError) as raised:
                graph.run_graph(state_file=self.path, review_decision='approve', reviewer='fixture-reviewer')
        self.assertIs(denied, raised.exception)
        self.assertEqual(len(file_io._READ_DELAYS) + 1, replace.call_count)
        self.assertEqual(len(file_io._READ_DELAYS), sleep.call_count)
        suite.assert_not_called()
        self.assertEqual(self.before, file_io.read_bytes(self.path))
        self.assertEqual('awaiting_human_review', json.loads(self.before)['status'])
        self.assertEqual([self.path], list(self.path.parent.iterdir()))


if __name__ == '__main__':
    unittest.main()
