"""Import the actual L05 files, stage runnable L06 checks and record teaching gaps."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from workbench.external_project import flowerp_root

L05=('tests/test_l05_receiving.py','tests/test_l05_scope.py','eval/l05_scope.py')
FROZEN=L05+('tests/test_l06_runner.py','eval/l06_checks.py','eval/harness.py')


def sha(path):return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def prepare(candidate,l05_session,output):
    session=json.loads(l05_session.read_text('utf-8-sig'))
    previous=json.loads((Path(session['run'])/'submission.json').read_text('utf-8-sig'))
    source=Path(previous['isolation']['path']).resolve();candidate=candidate.resolve()
    frozen=json.loads((Path(session['run'])/'frozen-checks.json').read_text('utf-8-sig'))
    if source==candidate:raise ValueError('L05 source must be distinct from L06 candidate')
    if output.exists():raise FileExistsError(output)
    examples=Path(__file__).parent
    copies={candidate/n:source/n for n in L05}
    copies.update({candidate/'eval/l06_runner.py':examples/'runner_starter.py',
                   candidate/'eval/l06_checks.py':examples/'checks_starter.py',
                   candidate/'tests/test_l06_runner.py':examples/'test_runner_contract.py'})
    for target,origin in copies.items():
        if target.exists():raise FileExistsError(target)
        if not origin.is_file():raise FileNotFoundError(origin)
    for name in L05:
        if sha(source/name)!=frozen['files'][name]:raise ValueError('L05 checks changed after freeze: '+name)
    registry=candidate/'eval/harness.py';content=registry.read_text('utf8')
    anchor='if __name__ == "__main__":'
    if content.count(anchor)!=1 or 'l06_stock_consistency' in content:raise ValueError('unexpected candidate Harness registry')
    service=candidate/'flowerp/service.py';code=service.read_text('utf8')
    prerequisite=None
    if '    def export_inventory(' not in code:
        reference=flowerp_root()/'flowerp/service.py'
        reference_text=reference.read_text('utf8')
        methods=[node for node in ast.walk(ast.parse(reference_text)) if isinstance(node,ast.FunctionDef) and node.name=='export_inventory']
        if len(methods)!=1:raise ValueError('reference export prerequisite is ambiguous')
        method=methods[0]
        excerpt='\n'.join(reference_text.splitlines()[method.lineno-1:method.end_lineno])+'\n\n'
        anchor_method='    def inventory_events('
        if code.count(anchor_method)!=1:raise ValueError('cannot restore export prerequisite safely')
        code=code.replace(anchor_method,excerpt+anchor_method)
        prerequisite={'reason':'historical L06 tag lacks the course export facade',
                      'source':str(reference),'source_sha256':sha(reference),
                      'copied_method':'ERPService.export_inventory','claim':'prerequisite scaffold, not a personal increment'}
    start=code.index('    def export_inventory(');end=code.index('\n    def ',start+5)
    original=code[start:end]
    if original.count("{row['available']}")!=1:raise ValueError('cannot locate the CSV teaching field; do not guess')
    changed=original.replace("{row['available']}","{row['on_hand']}")
    for target,origin in copies.items():target.write_bytes(origin.read_bytes())
    registrations='''from .l06_checks import ENTRIES, harness_contract
EVALS.extend(ENTRIES + [("l06_harness_contract", "blocking", harness_contract)])


'''
    registry.write_text(content.replace(anchor,registrations+anchor),encoding='utf8')
    service.write_text(code[:start]+changed+code[end:],encoding='utf8')
    evidence={'l05_task':previous['task']['id'],'l05_candidate':str(source),'candidate':str(candidate),
              'copied_l05':{n:sha(candidate/n) for n in L05},
              'prerequisite_restoration':prerequisite,
              'teaching_gaps':['CSV available intentionally uses on_hand','minimal Harness intentionally loses blocking failures'],
              'existing_gap':'course-prepare removes the excessive-reservation guard',
              'allowed_repair':['flowerp/service.py','eval/l06_runner.py'],'frozen_files':list(FROZEN)}
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),'utf8');return evidence


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);p.add_argument('--l05-session',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(prepare(a.candidate,a.l05_session,a.output),ensure_ascii=False,indent=2))
