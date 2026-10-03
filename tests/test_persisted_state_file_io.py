"""Persisted states remain governed when a Windows sharing lock clears."""
from contextlib import contextmanager
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import graph
from workbench import file_io
from workbench.subagent_coordination import SubagentCoordinator


@contextmanager
def sharing_lock(path, *, replacement=None, persistent=False):
    original = Path.open
    calls = []
    denied = PermissionError(errno.EACCES, 'fixture sharing lock')
    denied.winerror = 32

    def opened(target, mode='r', *args, **kwargs):
        if Path(target) == path and mode in {'r', 'rt', 'rb'}:
            calls.append(target)
            if persistent or len(calls) == 1:
                if replacement is not None and len(calls) == 1:
                    with original(target, 'wb') as output:
                        output.write(replacement)
                raise denied
        return original(target, mode, *args, **kwargs)

    with patch.object(file_io, '_WINDOWS', True), patch.object(Path, 'open', opened), \
            patch.object(file_io.time, 'sleep') as slept:
        yield calls, slept, denied


class PersistedStateReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.candidate = self.root / 'candidate'
        self.candidate.mkdir()
        self.manifest = self.root / 'manifest.json'
        self.manifest_payload = {
            'task_id': 'TASK-FILE-IO', 'candidate_path': str(self.candidate),
            'input_version': 'fixture-input-v1',
            'subtasks': [
                {'name': 'builder', 'prompt': 'fixture build', 'read_set': [],
                 'write_set': ['src/feature.py'], 'resource_set': ['report:builder']},
                {'name': 'reviewer', 'prompt': 'fixture review', 'read_set': [],
                 'write_set': [], 'resource_set': ['report:reviewer']},
            ],
        }
        self.manifest.write_text(json.dumps(self.manifest_payload), encoding='utf-8')
        self.coordinator = SubagentCoordinator(self.root / 'runtime')

    def completed_plan(self):
        plan = self.coordinator.create(self.manifest)
        evidence = self.root / 'fixture-evidence.txt'
        evidence.write_text('fixture output', encoding='utf-8')
        plan['status'] = 'running'
        for subtask in plan['subtasks']:
            subtask.update(status='completed', actor='fixture-agent', evidence=[str(evidence)],
                           started_at='2026-10-03T00:00:00+00:00',
                           ended_at='2026-10-03T00:00:02+00:00')
        path = self.coordinator._path(plan['id'])
        path.write_text(json.dumps(plan), encoding='utf-8')
        return plan, path

    def waiting_state(self):
        path = self.root / 'delivery.json'
        payload = {'status': 'awaiting_human_review', 'rounds': 1, 'trace': [],
                   'report': {'summary': {'blocking_failed': 0, 'decision': 'pass'}},
                   'reviewer': None, 'review_decision': None, 'reviewed_at': None}
        path.write_text(json.dumps(payload), encoding='utf-8')
        return payload, path

    def test_coordinator_reads_changed_manifest_and_still_rejects_resource_conflicts(self):
        changed = json.loads(json.dumps(self.manifest_payload))
        for subtask in changed['subtasks']:
            subtask['resource_set'] = ['report:shared']
        with sharing_lock(self.manifest, replacement=json.dumps(changed).encode('utf-8')) as (calls, slept, _):
            with self.assertRaises(ValueError):
                self.coordinator.create(self.manifest)
        self.assertEqual(2, len(calls))
        slept.assert_called_once()
        self.assertEqual([], list(self.coordinator.root.glob('SUBAGENT-*.json')))

    def test_coordinator_finalize_recovers_temporary_lock(self):
        plan, path = self.completed_plan()
        with sharing_lock(path) as (calls, slept, _):
            result = self.coordinator.finalize(plan['id'], 'main-agent')
        self.assertEqual(2, len(calls))
        slept.assert_called_once()
        self.assertEqual('ready_for_serial_integration', result['status'])
        self.assertTrue(result['events'][-1]['overlap_proved'])

    def test_coordinator_persistent_denial_cannot_publish_ready_state(self):
        plan, path = self.completed_plan()
        before = file_io.read_bytes(path)
        with sharing_lock(path, persistent=True) as (calls, slept, denied):
            with self.assertRaises(PermissionError) as raised:
                self.coordinator.finalize(plan['id'], 'main-agent')
        self.assertIs(denied, raised.exception)
        self.assertEqual(len(file_io._READ_DELAYS) + 1, len(calls))
        self.assertEqual(len(file_io._READ_DELAYS), slept.call_count)
        self.assertEqual(before, file_io.read_bytes(path))

    def test_changed_plan_keeps_completion_evidence_and_overlap_checks(self):
        for invalid in ('incomplete', 'missing_evidence', 'no_overlap'):
            with self.subTest(invalid=invalid):
                plan, path = self.completed_plan()
                if invalid == 'incomplete':
                    plan['subtasks'][0]['status'] = 'failed'
                elif invalid == 'missing_evidence':
                    plan['subtasks'][0]['evidence'] = []
                else:
                    plan['subtasks'][1]['started_at'] = '2026-10-03T00:00:03+00:00'
                    plan['subtasks'][1]['ended_at'] = '2026-10-03T00:00:04+00:00'
                replacement = json.dumps(plan).encode('utf-8')
                with sharing_lock(path, replacement=replacement):
                    with self.assertRaises(ValueError):
                        self.coordinator.finalize(plan['id'], 'main-agent')
                self.assertEqual(replacement, file_io.read_bytes(path))
                self.assertEqual('running', json.loads(replacement)['status'])

    def test_graph_resumes_waiting_after_temporary_lock_without_approval(self):
        _, path = self.waiting_state()
        with sharing_lock(path) as (calls, slept, _), \
                patch.object(graph, 'run_suite') as suite:
            result = graph.run_graph(state_file=path, require_human_review=True)
        self.assertEqual(2, len(calls))
        slept.assert_called_once()
        suite.assert_not_called()
        self.assertEqual('awaiting_human_review', result['status'])
        self.assertIsNone(result['reviewer'])
        self.assertIsNone(result['review_decision'])

    def test_graph_recovers_lock_and_preserves_explicit_named_approval(self):
        _, path = self.waiting_state()
        with sharing_lock(path), patch.object(graph, 'run_suite') as suite:
            result = graph.run_graph(state_file=path, review_decision='approve', reviewer='fixture-reviewer')
        suite.assert_not_called()
        self.assertEqual('completed', result['status'])
        self.assertEqual('fixture-reviewer', result['reviewer'])
        self.assertEqual('approve', result['review_decision'])

    def test_graph_persistent_denial_cannot_publish_approved_state(self):
        _, path = self.waiting_state()
        before = file_io.read_bytes(path)
        with sharing_lock(path, persistent=True) as (calls, slept, denied), \
                patch.object(graph, 'run_suite') as suite:
            with self.assertRaises(PermissionError) as raised:
                graph.run_graph(state_file=path, review_decision='approve', reviewer='fixture-reviewer')
        self.assertIs(denied, raised.exception)
        self.assertEqual(len(file_io._READ_DELAYS) + 1, len(calls))
        self.assertEqual(len(file_io._READ_DELAYS), slept.call_count)
        suite.assert_not_called()
        self.assertEqual(before, file_io.read_bytes(path))

    def test_graph_reads_changed_state_and_does_not_approve_unknown_state(self):
        payload, path = self.waiting_state()
        payload['status'] = 'unrecognized-state'
        with sharing_lock(path, replacement=json.dumps(payload).encode('utf-8')), \
                patch.object(graph, 'run_suite') as suite:
            result = graph.run_graph(state_file=path, review_decision='approve', reviewer='fixture-reviewer')
        suite.assert_not_called()
        self.assertEqual('failed', result['status'])
        self.assertIsNone(result['reviewer'])
        self.assertIsNone(result['review_decision'])
        self.assertIn('未知状态', result['trace'][-1]['reason'])


if __name__ == '__main__':
    unittest.main()
