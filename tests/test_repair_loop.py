import unittest
import tempfile
from pathlib import Path

from workbench.repair_loop import project, validate_config
from workbench.initiative import InitiativeStore
from workbench.initiative_workflow import InitiativeWorkflow
from workbench.task_store import TaskStore
from workbench.project_store import ProjectStore


class Tasks:
    def __init__(self, rows): self.rows = rows
    def get(self, task_id): return self.rows[task_id]


def task(task_id, failures, *, tokens=10, changed=True, status='rework'):
    return {'id': task_id, 'status': status,
            'result': {'results': [{'name': name, 'level': 'blocking', 'passed': False} for name in failures]},
            'events': [{'detail': '受控执行阶段完成', 'evidence': {
                'usage': {'total_tokens': tokens}, 'changed_files': ['flowerp/service.py'] if changed else []}}]}


class RepairLoopTests(unittest.TestCase):
    def test_workbench_persists_loop_config_for_an_initiative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.git').mkdir()
            tasks = TaskStore(root / 'workbench.db')
            projects = ProjectStore(tasks.path)
            projects.create('测试项目', root, [], project_id='PROJECT-LOOP', allow_pending_eval=True)
            initiatives = InitiativeStore(tasks.path)
            item = initiatives.create({'title': '订单状态修复', 'raw_signal': '非法发货',
                                       'source': '业务观察', 'project_id': 'PROJECT-LOOP'}, 'owner')
            service = InitiativeWorkflow(root, root / 'runtime', initiatives, tasks,
                                         enabled=True, projects=projects)
            state = service.get(item['id'])
            saved = service.configure_loop(item['id'], 'owner', state['revision'], {
                'enabled': True, 'max_rounds': 3, 'token_budget': 30000,
                'time_budget_seconds': 900})
            self.assertTrue(saved['repair_loop']['config']['enabled'])
            self.assertEqual(3, saved['repair_loop']['config']['max_rounds'])
            self.assertIn('保存有界修复 Loop', saved['messages'][-1]['text'])

    def test_l10_bounds_reject_more_than_three_rounds(self):
        with self.assertRaisesRegex(ValueError, '最多三轮'):
            validate_config({'enabled': True, 'max_rounds': 4, 'token_budget': 1, 'time_budget_seconds': 1})

    def test_same_blocking_names_stop_and_build_handoff(self):
        tasks = Tasks({'A': task('A', ['illegal_transition_is_blocked']),
                       'B': task('B', ['illegal_transition_is_blocked'])})
        view = project({'enabled': True, 'max_rounds': 3, 'token_budget': 100, 'time_budget_seconds': 900},
                       [{'task_id': 'A', 'at': 100}, {'task_id': 'B', 'at': 110}], tasks, now=120)
        self.assertEqual('stopped_no_progress', view['status'])
        self.assertFalse(view['can_continue'])
        self.assertEqual('B', view['handoff']['last_task_id'])
        self.assertEqual(['illegal_transition_is_blocked'], view['handoff']['remaining_failures'])

    def test_last_change_without_report_is_pending_verification(self):
        row = task('A', [], status='executing')
        row['result'] = None
        view = project({'enabled': True}, [{'task_id': 'A', 'at': 100}], Tasks({'A': row}), now=101)
        self.assertEqual('modified_pending_verification', view['status'])
        self.assertEqual(['末轮修改尚未复验'], view['handoff']['unverified'])

    def test_budget_exhaustion_is_not_success(self):
        view = project({'enabled': True, 'token_budget': 10}, [{'task_id': 'A', 'at': 100}],
                       Tasks({'A': task('A', ['still-red'], tokens=12)}), now=101)
        self.assertEqual('stopped_token_budget', view['status'])
        self.assertEqual(0, view['tokens_remaining'])


if __name__ == '__main__':
    unittest.main()
