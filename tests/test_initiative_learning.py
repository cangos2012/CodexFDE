"""Cross-item reuse through the real workflow with independent Eval subprocesses."""
from pathlib import Path
import unittest

from eval.workbench_contracts import LocalDeliveryFixture
from workbench.feedback import add_feedback, review_feedback
from workbench.initiative_workflow import InitiativeWorkflow


class InitiativeLearningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = LocalDeliveryFixture()
        self.addCleanup(self.fixture.close)

    def test_source_trial_publish_and_default_reuse_keep_three_item_evidence(self):
        f = self.fixture
        source, asset = f.workflow_asset()
        f.integrate(source)
        trial = f.item('value trial B')
        f.value = 3
        f.prepare(trial, trials=True, choices=[f.choice(asset)])
        state = f.execute(trial)
        self.assertEqual('review', state['stage'], state.get('error'))
        self.assertEqual('2', (f.source / 'value.txt').read_text())
        self.assertEqual(0, state['learning']['metrics']['reuse_passed'])
        with self.assertRaisesRegex(ValueError, '独立事项'):
            f.learning.govern(source['id'], asset['id'], 'fixture-peer', 'publish', 'Eval alone is insufficient')
        f.accept(trial)
        binding = f.state(trial)['learning']['bindings'][0]
        self.assertEqual(['precheck', 'implement', 'eval', 'review', 'outcome'], [r['phase'] for r in binding['runs']])
        self.assertTrue(binding['runs'][-1]['payload']['passed'])
        self.assertEqual('fixture-reviewer', binding['runs'][-1]['payload']['reviewed_by'])
        f.integrate(trial)
        f.learning.govern(source['id'], asset['id'], 'fixture-peer', 'publish', 'Independent trial accepted')
        reuse = f.item('value reuse C')
        f.value = 4
        f.prepare(reuse, choices=[f.choice(asset)])
        state = f.execute(reuse)
        self.assertEqual('review', state['stage'], state.get('error'))
        task = f.tasks.get(state['active_task_id'])
        self.assertEqual(0, task['result']['runner']['process_returncode'])
        self.assertTrue(Path(task['result']['runner']['process_path']).is_file())
        self.assertIn(asset['id'], task['spec']['done'])
        f.accept(reuse)
        f.integrate(reuse)
        self.assertEqual('4', (f.source / 'value.txt').read_text())
        self.assertEqual(1, f.learning.view(reuse['id'])['metrics']['reuse_passed'])
        restored = InitiativeWorkflow(f.source, f.runtime, f.items, f.tasks, projects=f.projects)
        self.assertEqual(f.learning.view(reuse['id'])['bindings'], restored.get(reuse['id'])['learning']['bindings'])

    def test_failed_reuse_revokes_version_keeps_binding_and_allows_new_candidate(self):
        f = self.fixture
        source, asset = f.workflow_asset()
        trial = f.item('value failing trial B')
        f.value = -1
        f.prepare(trial, trials=True, choices=[f.choice(asset)])
        state = f.execute(trial)
        self.assertEqual('rework', state['stage'], state.get('error'))
        self.assertEqual('revoked', f.learning.get(asset['id'])['state'])
        self.assertEqual(1, f.learning.view(trial['id'])['metrics']['reuse_failed'])
        binding = f.learning.view(trial['id'])['bindings'][0]
        self.assertEqual(asset['sha256'], binding['assets'][0]['sha256'])
        self.assertEqual(asset['id'], binding['assets'][0]['snapshot']['id'])
        self.assertFalse(binding['runs'][-1]['payload']['passed'])
        self.assertEqual([], f.learning.recall(f.item('value after failure')['id'], 'value', trials=True)['matches'])
        replacement = f.learning.create(source['id'], 'fixture-author',
            f.candidate(asset['source']['task_id'], supersedes=asset['id'], content='Revised positive value instructions'))
        self.assertEqual(2, replacement['version'])
        self.assertEqual('candidate', replacement['state'])
        self.assertEqual('revoked', f.learning.get(asset['id'])['state'])

    def test_revoked_adoption_blocks_before_task_creation(self):
        f = self.fixture
        source, asset = f.workflow_asset()
        trial = f.item('value trial B')
        f.prepare(trial, trials=True, choices=[f.choice(asset)])
        f.learning.govern(source['id'], asset['id'], 'fixture-peer', 'revoke', 'Withdraw before execution')
        with self.assertRaisesRegex(ValueError, '撤回'):
            f.call(trial, 'execute')
        self.assertIsNone(f.state(trial)['active_task_id'])
        self.assertEqual(1, len(f.tasks.list()))

    def test_changed_candidate_or_report_cannot_be_counted_as_successful_reuse(self):
        f = self.fixture
        _, asset = f.workflow_asset()
        trial = f.item('value trial B')
        f.prepare(trial, trials=True, choices=[f.choice(asset)])
        state = f.execute(trial)
        self.assertEqual('review', state['stage'], state.get('error'))
        candidate = Path(state['workspace']) / 'value.txt'
        original = candidate.read_bytes()
        candidate.write_text('99', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '检查后发生变化'):
            f.accept(trial)
        candidate.write_bytes(original)
        task = f.tasks.get(state['active_task_id'])
        report = f.runtime / task['result']['report_path']
        report.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            f.accept(trial)
        self.assertEqual(0, f.learning.view(trial['id'])['metrics']['reuse_passed'])
        self.assertEqual('review', f.tasks.get(task['id'])['status'])

    def test_failed_manual_recheck_revokes_trial_and_records_failed_outcome(self):
        f = self.fixture
        _, asset = f.workflow_asset()
        trial = f.item('value trial B')
        f.prepare(trial, trials=True, choices=[f.choice(asset)])
        state = f.execute(trial)
        self.assertEqual('review', state['stage'], state.get('error'))
        (Path(state['workspace']) / 'value.txt').write_text('-1', encoding='utf-8')
        f.call(trial, 'run_eval')
        state = f.wait(trial)
        self.assertEqual('rework', state['stage'], state.get('error'))
        self.assertEqual('revoked', f.learning.get(asset['id'])['state'])
        self.assertEqual(1, f.learning.view(trial['id'])['metrics']['reuse_failed'])
        outcome = f.learning.view(trial['id'])['bindings'][0]['runs'][-1]['payload']
        self.assertIn('path', outcome['report'])
        feedback = add_feedback(state['active_task_id'], 'fixture-recheck', 'Recheck blocked negative value',
                                'Review before reuse', f.tasks.path)
        review_feedback(feedback['id'], 'fixture-peer', 'accept', 'Checked real recheck receipt', f.tasks.path)
        memory = f.learning.create(trial['id'], 'fixture-author',
            f.candidate(state['active_task_id'], 'memory', feedback_id=feedback['id']))
        self.assertEqual(state['active_task_id'], memory['source']['task_id'])

    def test_restart_interrupts_inflight_reuse_and_never_replays_codex(self):
        f = self.fixture
        _, asset = f.workflow_asset()
        trial = f.item('value trial B')
        f.prepare(trial, trials=True, choices=[f.choice(asset)])
        state = f.execute(trial)
        self.assertEqual('review', state['stage'], state.get('error'))
        data = f.service._load(trial['id'])
        data['stage'] = 'executing'
        f.service._save(data)
        with f.tasks.connect() as db:
            db.execute("UPDATE tasks SET status='executing' WHERE id=?", (state['active_task_id'],))
        restored = InitiativeWorkflow(f.source, f.runtime, f.items, f.tasks, projects=f.projects)
        self.assertEqual('interrupted', restored.get(trial['id'])['stage'])
        self.assertEqual('failed', f.tasks.get(state['active_task_id'])['status'])
        self.assertEqual('revoked', f.learning.get(asset['id'])['state'])
        self.assertFalse(restored.workers)
        self.assertEqual(1, f.learning.view(trial['id'])['metrics']['reuse_failed'])


if __name__ == '__main__':
    unittest.main()
