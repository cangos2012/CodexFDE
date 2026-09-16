"""Create an explicit ledger-defect teaching copy. Never overwrite a directory."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from workbench.course_experiments import copy_experiment_sources

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    target=args.output.resolve()
    if target.exists(): parser.error('output already exists; choose a new empty location')
    target.mkdir(parents=True)
    copy_experiment_sources(target, packages=('flowerp',))
    source=target/'flowerp/service.py'
    text=source.read_text(encoding='utf-8')
    needle='            if exists:\n                row = conn.execute('
    if text.count(needle)!=1: parser.error('source shape changed; inspect before preparing this fixture')
    replacement='''            if exists:
                # Explicit teaching defect: replay writes another ledger row.
                conn.execute(
                    "INSERT INTO inventory_events(event_key,sku,quantity,reserved_delta,event_type,reference) VALUES(?,?,?,?,?,?)",
                    (event_key + ":duplicate:" + uuid.uuid4().hex, sku, quantity, 0, "receive", reference),
                )
                row = conn.execute('''
    source.write_text(text.replace(needle,replacement),encoding='utf-8')
    (target/'FIXTURE.md').write_text('L05 explicit teaching defect: a replay appends an extra inventory event while returning unchanged stock. This copy is not the course-submit baseline or a production incident. Only local temporary databases are used by the external check.\n',encoding='utf-8')
    print(target)

if __name__=='__main__': main()
