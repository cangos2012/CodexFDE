"""A reviewed hash and the executed/displayed binding must describe one read."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from workbench import file_io, quality_hook

REAL_SLEEP = time.sleep


class HookBindingSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source, self.workspace = root / 'source', root / 'candidate'
        self.source.mkdir()
        self.workspace.mkdir()
        (self.workspace / '.git').mkdir()
        self.package = quality_hook.prepare(root / 'runtime', self.workspace,
            {'id': 'PROJECT-snapshot', 'root_path': str(self.source), 'eval_command': ['reviewed-eval']},
            'TASK-snapshot', 'ITEM-snapshot', 'fixture-reviewer')
        self.binding_path = Path(self.package['path']) / 'binding.json'
        self.binding = json.loads(file_io.read_bytes(self.binding_path))
        self.modified = deepcopy(self.binding)
        self.modified['command'] = ['unreviewed-eval']

    def event(self):
        return io.StringIO(json.dumps({'hook_event_name': 'Stop', 'cwd': str(self.workspace),
                                      'stop_hook_active': False}))

    def test_execution_uses_the_same_binding_bytes_that_passed_hash_review(self):
        original = Path.open
        reads = []

        def changing_second_read(target, mode='r', *args, **kwargs):
            if target == self.binding_path and mode in {'r', 'rt', 'rb'}:
                reads.append(mode)
                if len(reads) > 1:
                    text = json.dumps(self.modified)
                    return io.BytesIO(text.encode()) if mode == 'rb' else io.StringIO(text)
            return original(target, mode, *args, **kwargs)

        evaluated = Mock(return_value={'summary': {'decision': 'pass'}})
        output = io.StringIO()
        with patch.object(Path, 'open', changing_second_read), \
                patch('workbench.project_delivery.CandidateProjectEval', return_value=evaluated) as runner, \
                patch('sys.stdin', self.event()), patch('sys.stdout', output):
            quality_hook.main(self.binding_path, self.package['binding_sha256'])
        self.assertTrue(json.loads(output.getvalue())['continue'])
        self.assertEqual(['reviewed-eval'], runner.call_args.args[3])

    def test_binding_changed_while_read_is_locked_cannot_execute(self):
        original = Path.open
        first = True

        def locked_and_changed(target, mode='r', *args, **kwargs):
            nonlocal first
            if target == self.binding_path and mode in {'r', 'rt', 'rb'} and first:
                first = False
                with original(target, 'w', encoding='utf-8') as stream:
                    stream.write(json.dumps(self.modified))
                raise PermissionError('temporary read lock')
            return original(target, mode, *args, **kwargs)

        output = io.StringIO()
        with patch.object(file_io, '_WINDOWS', True), patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP), \
                patch.object(Path, 'open', locked_and_changed), \
                patch('workbench.project_delivery.CandidateProjectEval') as runner, \
                patch('sys.stdin', self.event()), patch('sys.stdout', output):
            quality_hook.main(self.binding_path, self.package['binding_sha256'])
        self.assertEqual('block', json.loads(output.getvalue())['decision'])
        runner.assert_not_called()

    def test_review_displays_the_binding_content_that_was_hash_checked(self):
        original = Path.open
        reads = []

        def changing_second_read(target, mode='r', *args, **kwargs):
            if target == self.binding_path and mode in {'r', 'rt', 'rb'}:
                reads.append(mode)
                if len(reads) > 1:
                    text = json.dumps(self.modified)
                    return io.BytesIO(text.encode()) if mode == 'rb' else io.StringIO(text)
            return original(target, mode, *args, **kwargs)

        with patch.object(Path, 'open', changing_second_read):
            review = quality_hook.view(self.package, self.workspace, 'TASK-snapshot')
        self.assertEqual('prepared', review['status'])
        self.assertEqual(['reviewed-eval'], json.loads(review['review_files']['binding.json'])['command'])


if __name__ == '__main__':
    unittest.main()
