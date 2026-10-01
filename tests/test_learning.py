"""Governance tests use local automated fixtures, never student or live evidence."""
import copy
import unittest

from eval.workbench_contracts import LocalDeliveryFixture
from workbench.feedback import add_feedback, review_feedback
from workbench.learning import LearningStore, canonical


class LearningGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = LocalDeliveryFixture()
        self.addCleanup(self.fixture.close)
        self.source, self.task_id = self.fixture.accepted_source()
        self.store = self.fixture.learning

    def asset(self, kind='memory', **changes):
        return self.store.create(self.source['id'], 'fixture-author',
            self.fixture.candidate(self.task_id, kind, **changes))

    def publish_memory(self, **changes):
        asset = self.asset(**changes)
        return self.store.govern(self.source['id'], asset['id'], 'fixture-peer', 'approve', 'Independent fixture review')

    def test_source_must_belong_to_item_and_have_named_passing_acceptance(self):
        other = self.fixture.item('unrelated value item')
        with self.assertRaisesRegex(ValueError, '来源任务不属于'):
            self.store.create(other['id'], 'fixture-author', self.fixture.candidate(self.task_id))
        self.fixture.prepare(other)
        state = self.fixture.execute(other)
        self.assertEqual('review', state['stage'])
        with self.assertRaisesRegex(ValueError, '已验收任务'):
            self.store.create(other['id'], 'fixture-author', self.fixture.candidate(state['active_task_id']))

    def test_governance_rejects_ai_self_review_and_changed_source_report(self):
        asset = self.asset()
        for actor in ('codex', 'agent:reviewer', '待确认', 'fixture-author'):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                self.store.govern(self.source['id'], asset['id'], actor, 'approve', 'review')
        task = self.fixture.tasks.get(self.task_id)
        report = self.fixture.runtime / task['result']['report_path']
        report.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '报告已被替换'):
            self.store.govern(self.source['id'], asset['id'], 'fixture-peer', 'approve', 'review')
        self.assertEqual('candidate', self.store.get(asset['id'])['state'])

    def test_recall_respects_project_source_exclusions_budget_and_conflicts(self):
        first = self.publish_memory()
        second = self.publish_memory(title='Independent conclusion on value')
        self.assertEqual([], self.store.recall(self.source['id'], 'value')['matches'])
        item = self.fixture.item('value next item')
        packet = self.store.recall(item['id'], 'value')
        self.assertEqual({first['id'], second['id']}, {m['id'] for m in packet['matches']})
        self.assertEqual(1, len(packet['conflicts']))
        self.assertEqual([], self.store.recall(item['id'], 'negative-only value')['matches'])
        self.assertEqual([], self.store.recall(item['id'], 'value', budget=1)['matches'])
        other_project = self.fixture.register('other-project')
        other_item = self.fixture.item('value another project', project=other_project)
        self.assertEqual([], self.store.recall(other_item['id'], 'value')['matches'])
        with self.assertRaisesRegex(ValueError, '跨项目'):
            self.store.govern(other_item['id'], first['id'], 'fixture-peer', 'revoke', 'wrong scope')

    def test_each_recalled_version_needs_explicit_choice_and_reason(self):
        asset = self.publish_memory()
        item = self.fixture.item()
        recall = self.store.recall(item['id'], 'value')
        for choices in ([], [{'id': asset['id'], 'adopt': None, 'reason': 'unsure'}],
                        [{'id': asset['id'], 'adopt': True, 'reason': ''}],
                        [{'id': 'LEARN-foreign', 'adopt': True, 'reason': 'wrong'}]):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                self.store.decide(item['id'], recall['id'], choices, 'fixture-adopter')
        with self.assertRaisesRegex(ValueError, '召回记录不属于'):
            self.store.decide(self.source['id'], recall['id'], [self.fixture.choice(asset)], 'fixture-adopter')
        decision = self.store.decide(item['id'], recall['id'], [self.fixture.choice(asset, adopt=False)], 'fixture-adopter')
        self.assertFalse(decision['choices'][0]['adopt'])

    def test_only_one_reviewed_workflow_can_be_bound(self):
        assets = [self.asset('workflow', title='Workflow ' + str(i), conflict_key='topic-' + str(i)) for i in range(2)]
        item = self.fixture.item()
        self.assertEqual([], self.store.recall(item['id'], 'value', trials=True)['matches'])
        for asset in assets:
            self.store.govern(self.source['id'], asset['id'], 'fixture-peer', 'approve', 'allow trial')
        packet = self.store.recall(item['id'], 'value', trials=True)
        with self.assertRaisesRegex(ValueError, '一个受控流程'):
            self.store.decide(item['id'], packet['id'], [self.fixture.choice(a) for a in assets], 'fixture-adopter')
        with self.assertRaisesRegex(ValueError, '独立事项'):
            self.store.govern(self.source['id'], assets[0]['id'], 'fixture-peer', 'publish', 'no trial execution')

    def test_revoked_or_superseded_version_blocks_execution_but_preserves_binding(self):
        first = self.publish_memory()
        item = self.fixture.item()
        packet = self.store.recall(item['id'], 'value')
        decision = self.store.decide(item['id'], packet['id'], [self.fixture.choice(first)], 'fixture-adopter')
        binding = self.store.bind(item['id'], 'contract-plan', decision, self.fixture.source, 'fixture-adopter')
        original = copy.deepcopy(self.store.binding(binding['id']))
        second = self.publish_memory(supersedes=first['id'], content='Revised value conclusion')
        self.assertEqual(2, second['version'])
        self.assertEqual('superseded', self.store.get(first['id'])['state'])
        self.assertEqual(original, self.store.binding(binding['id']))
        with self.assertRaisesRegex(ValueError, '被替代'):
            self.store.validate_binding(binding['id'], self.fixture.source)
        self.store.govern(self.source['id'], second['id'], 'fixture-peer', 'revoke', 'withdrawn')
        self.assertEqual([], self.store.recall(item['id'], 'value')['matches'])

    def test_adoption_snapshot_tampering_is_detected(self):
        asset = self.publish_memory()
        item = self.fixture.item()
        packet = self.store.recall(item['id'], 'value')
        decision = self.store.decide(item['id'], packet['id'], [self.fixture.choice(asset)], 'fixture-adopter')
        binding = self.store.bind(item['id'], 'tamper-plan', decision, self.fixture.source, 'fixture-adopter')
        payload = {key: value for key, value in binding.items() if key != 'sha256'}
        payload['assets'][0]['reason'] = 'replaced decision'
        with self.fixture.tasks.connect() as db:
            db.execute('UPDATE learning_bindings SET payload=? WHERE id=?', (canonical(payload), binding['id']))
        with self.assertRaisesRegex(ValueError, '采用快照被修改'):
            self.store.validate_binding(binding['id'], self.fixture.source)

    def test_recipe_checks_parameters_path_boundary_and_changed_file(self):
        recipe = self.fixture.candidate(self.task_id)['recipe']
        recipe['parameters'] = ['policy']
        recipe['preconditions'][0]['path'] = '${policy}'
        asset = self.asset('workflow', recipe=recipe)
        prepared = LearningStore.preconditions(asset, {'policy': 'policy.txt'}, self.fixture.source)
        self.assertTrue(prepared['checks'][0]['passed'])
        for parameters in ({}, {'policy': '../value.txt'}, {'policy': '.git/config'}, {'policy': 'missing.txt'},
                           {'policy': 'policy.txt', 'extra': 'x'}):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                LearningStore.preconditions(asset, parameters, self.fixture.source)
        self.store.govern(self.source['id'], asset['id'], 'fixture-peer', 'approve', 'allow trial')
        item = self.fixture.item()
        packet = self.store.recall(item['id'], 'value', trials=True)
        choice = self.fixture.choice(asset) | {'parameters': {'policy': 'policy.txt'}}
        decision = self.store.decide(item['id'], packet['id'], [choice], 'fixture-adopter')
        binding = self.store.bind(item['id'], 'recipe-plan', decision, self.fixture.source, 'fixture-adopter')
        (self.fixture.source / 'policy.txt').write_text('positive value contract changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '依据已变化'):
            self.store.validate_binding(binding['id'], self.fixture.source)

    def test_recipe_cannot_skip_eval_review_or_confirmed_authorization(self):
        original = self.fixture.candidate(self.task_id)['recipe']
        for change in ({'steps': original['steps'][:3]}, {'eval_entry': 'optional'}, {'authorization': 'automatic'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                LearningStore.recipe(original | change)
        recipe = copy.deepcopy(original)
        recipe['steps'][-1]['role'] = 'codex'
        with self.assertRaisesRegex(ValueError, '职责'):
            LearningStore.recipe(recipe)

    def test_failure_source_requires_accepted_feedback_and_options_stay_in_item(self):
        failed = self.fixture.item('value failure')
        self.fixture.value = -1
        self.fixture.prepare(failed)
        state = self.fixture.execute(failed)
        task_id = state['active_task_id']
        feedback = add_feedback(task_id, 'fixture', 'Actual project Eval blocked negative value',
                                'Review failure before proposing reuse', self.fixture.tasks.path)
        self.assertEqual([], self.store.source_options(failed['id'])['tasks'])
        candidate = self.fixture.candidate(task_id, 'memory', feedback_id=feedback['id'])
        with self.assertRaisesRegex(ValueError, '具名接受'):
            self.store.create(failed['id'], 'fixture-author', candidate)
        review_feedback(feedback['id'], 'fixture-peer', 'accept', 'Checked failed process receipt', self.fixture.tasks.path)
        options = self.store.source_options(failed['id'])
        self.assertEqual([task_id], [t['id'] for t in options['tasks']])
        self.assertFalse(options['tasks'][0]['eligible_success'])
        self.assertEqual([feedback['id']], [f['id'] for f in options['feedback']])
        asset = self.store.create(failed['id'], 'fixture-author', candidate)
        self.assertTrue(asset['source']['evolution_id'])
        self.assertEqual([], self.store.source_options(self.source['id'])['feedback'])
        self.assertTrue(self.store.source_options(self.source['id'])['tasks'][0]['eligible_success'])

    def test_reopened_item_keeps_real_task_source_from_completed_cycle(self):
        self.fixture.integrate(self.source)
        self.fixture.call(self.source, 'reopen', 'next local value change')
        state = self.fixture.state(self.source)
        self.assertIsNone(state['active_task_id'])
        self.assertEqual([self.task_id], [t['id'] for t in state['learning_sources']['tasks']])
        self.assertEqual(self.task_id, self.asset()['source']['task_id'])


if __name__ == '__main__':
    unittest.main()
