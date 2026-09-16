"""L06 runnable teaching experiment; isolated SQLite, no production data changes."""
from __future__ import annotations
import argparse
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from workbench.course_experiments import ensure_product_process
ensure_product_process(__file__)
from flowerp.import_export import ImportExportService
from flowerp.identity import SYSTEM_PRINCIPAL, IdentityService
from flowerp.models import Conflict
from flowerp.store import ERPStore
from eval.cases import receiving_is_idempotent


def load_runner():
    spec = importlib.util.spec_from_file_location('l06_teaching_runner', Path(__file__).with_name('runner_starter.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(stage: str, report_path: Path, count: int = 3):
    """The bad adapter deliberately commits valid rows separately. Never copy it into production."""
    runner = load_runner()
    if stage != 'false-green':
        source = Path(__file__).with_name('runner_starter.py').read_text(encoding='utf8')
        source = source.replace('blocking_failed = 0', "blocking_failed = sum(not r['passed'] and r['level']=='blocking' for r in results)")
        exec(compile(source, '<teaching corrected runner>', 'exec'), runner.__dict__)

    def csv_text(invalid=False):
        return 'sku,name,sales_price_cents\n' + ''.join(
            f'NEW-{i},{"" if invalid and i == count else "演示商品"+str(i)},1290\n'
            for i in range(1, count+1))

    def submit(service, text):
        if stage == 'fixed':
            job = service.validate_csv(SYSTEM_PRINCIPAL, 'products', text, 'launch.csv')
            service.commit(SYSTEM_PRINCIPAL, job['id'])
        else:
            # Explicit teaching defect: skip invalid rows and commit each valid row.
            for row in csv.DictReader(io.StringIO(text)):
                if not row['name']:
                    continue
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=['sku','name','sales_price_cents'])
                writer.writeheader(); writer.writerow(row)
                job = service.validate_csv(SYSTEM_PRINCIPAL, 'products', buffer.getvalue())
                service.commit(SYSTEM_PRINCIPAL, job['id'])

    def scenario(invalid):
        with tempfile.TemporaryDirectory(prefix='l06-import-') as directory:
            store = ERPStore(Path(directory)/'case.db')
            IdentityService(store).ensure_local_defaults()
            service = ImportExportService(store)
            before = store.rows('SELECT sku,name,sales_price_cents FROM product_master ORDER BY sku')
            rejected = False
            try:
                submit(service, csv_text(invalid))
            except Conflict:
                rejected = True
            after = store.rows('SELECT sku,name,sales_price_cents FROM product_master ORDER BY sku')
            if invalid:
                observed = f'rows={count}; rejected={rejected}; added={len(after)-len(before)}'
                assert rejected and after == before, 'AC-BATCH: expected rejected=True, added=0; '+observed
            else:
                observed = f'rows={count}; added={len(after)-len(before)}'
                assert not rejected and len(after)-len(before) == count, observed
                assert all(r['sales_price_cents']==1290 for r in after if r['sku'].startswith('NEW-')), after
            return observed

    def preview_is_read_only():
        with tempfile.TemporaryDirectory(prefix='l06-preview-') as directory:
            store = ERPStore(Path(directory)/'case.db')
            IdentityService(store).ensure_local_defaults()
            before = store.rows('SELECT * FROM product_master ORDER BY id')
            job = ImportExportService(store).validate_csv(SYSTEM_PRINCIPAL,'products',csv_text())
            assert job['status']=='ready'
            assert store.rows('SELECT * FROM product_master ORDER BY id')==before
            return 'preview ready; product_master unchanged; staging job retained'

    def help_image():
        raise AssertionError('教学设定：选读帮助缺辅助图片，操作文字完整；待补图')

    entries = [('valid_batch','blocking',lambda:scenario(False)),
               ('invalid_batch_no_write','blocking',lambda:scenario(True)),
               ('preview_no_product_write','blocking',preview_is_read_only),
               ('l05_receiving_reference','blocking',receiving_is_idempotent),
               ('help_image','observing',help_image)]
    report, code = runner.run(entries,report_path=report_path)
    print(json.dumps({'stage':stage,'summary':report['summary'],'report':str(report_path.resolve())},ensure_ascii=False))
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['false-green','gate-fixed','fixed'])
    parser.add_argument('--report-path',type=Path,required=True)
    parser.add_argument('--rows',type=int,default=3)
    args = parser.parse_args()
    if not 2 <= args.rows <= 100:
        parser.error('--rows must be between 2 and 100')
    raise SystemExit(run(args.stage,args.report_path,args.rows))
