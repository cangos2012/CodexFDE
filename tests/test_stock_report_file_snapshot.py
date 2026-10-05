"""One L06 report read must bind its hash, contract validation and decision."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from workbench import file_io

REAL_SLEEP = time.sleep


SOURCE = Path(__file__).resolve().parents[1] / 'docs/courses/L06/examples/stock_practice.py'
spec = importlib.util.spec_from_file_location('stock_report_snapshot', SOURCE)
stock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stock)


class StockReportSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.candidate = self.root / 'candidate'
        self.candidate.mkdir()
        (self.candidate / 'value.py').write_text('VALUE = 1\n', encoding='utf-8')
        self.session = {'candidate': self.candidate}
        self.report_path = self.root / 'report.json'
        self.report = {'schema_version': '1.0', 'suite': 'all', 'requested_cases': list(stock.NAMES),
            'results': [{'name': name, 'level': 'observing' if name == 'help_image' else 'blocking',
                         'passed': name != 'l06_stock_consistency'} for name in stock.NAMES],
            'summary': {'total': 4, 'passed': 3, 'blocking_failed': 1,
                        'observing_failed': 0, 'decision': 'block'}}
        self.forged = deepcopy(self.report)
        self.forged['summary']['decision'] = 'pass'
        self.raw = json.dumps(self.report, indent=2).encode('utf-8')
        self.report_path.write_bytes(self.raw)
        self.record = {'cwd': str(self.candidate), 'report_path': str(self.report_path),
            'files': stock.inventory(self.candidate), 'unchanged_during_run': True,
            'report_sha256': hashlib.sha256(self.raw).hexdigest(), 'exit_code': 1}
        self.receipt_path = self.report_path.with_suffix('.receipt.json')
        self.receipt_path.write_text(json.dumps(self.record), encoding='utf-8')

    def test_later_report_read_cannot_replace_a_checked_block_with_pass(self):
        original = Path.open
        reads = []

        def changing_report(target, mode='r', *args, **kwargs):
            if target == self.report_path and mode in {'r', 'rt', 'rb'}:
                reads.append(mode)
                # The former fourth read selected a summary that had never
                # passed the receipt hash or report-contract validation.
                raw = self.raw if len(reads) < 4 else json.dumps(self.forged).encode('utf-8')
                return io.BytesIO(raw) if mode == 'rb' else io.StringIO(raw.decode('utf-8'))
            return original(target, mode, *args, **kwargs)

        output = io.StringIO()
        with patch.object(Path, 'open', changing_report), patch.object(stock, 'verify'), \
                patch('sys.stdout', output):
            stock.review(self.session, self.report_path)
        self.assertEqual('block', json.loads(output.getvalue())['business_decision'])

    def test_report_changed_during_locked_read_is_rejected(self):
        original = Path.open
        first = True

        def locked_and_changed(target, mode='r', *args, **kwargs):
            nonlocal first
            if target == self.report_path and mode in {'r', 'rt', 'rb'} and first:
                first = False
                with original(target, 'wb') as output:
                    output.write(json.dumps(self.forged).encode('utf-8'))
                raise PermissionError('temporary report sharing lock')
            return original(target, mode, *args, **kwargs)

        with patch.object(file_io, '_WINDOWS', True), patch.object(file_io.time, 'sleep', wraps=REAL_SLEEP), \
                patch.object(Path, 'open', locked_and_changed), patch.object(stock, 'verify'):
            with self.assertRaisesRegex(ValueError, 'Candidate or report changed'):
                stock.review(self.session, self.report_path)

    def test_verified_snapshot_preserves_utf8_bom_and_crlf_policy(self):
        raw = b'\xef\xbb\xbf' + self.raw.replace(b'\n', b'\r\n')
        self.report_path.write_bytes(raw)
        self.record['report_sha256'] = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
        self.receipt_path.write_text(json.dumps(self.record), encoding='utf-8')
        output = io.StringIO()
        with patch.object(stock, 'verify'), patch('sys.stdout', output):
            stock.review(self.session, self.report_path)
        self.assertEqual('block', json.loads(output.getvalue())['business_decision'])


if __name__ == '__main__':
    unittest.main()
