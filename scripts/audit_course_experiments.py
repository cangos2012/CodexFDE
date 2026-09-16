"""Run local teaching modes with explicit expected exits and preserved evidence.

Does not invoke Codex, remote CI, or real human reviews. Interactive student
deliveries remain separate from these executable teaching experiments.
"""
from __future__ import annotations
import argparse
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def modes(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                if isinstance(node.value, ast.Dict):
                    constants[node.targets[0].id] = [ast.literal_eval(k) for k in node.value.keys]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
            for keyword in node.keywords:
                if keyword.arg == 'choices':
                    return constants[keyword.value.id] if isinstance(keyword.value, ast.Name) else ast.literal_eval(keyword.value)
    return [None]


def matrix(out):
    specs = [
        (6, 'harness_lab', '--report-path', {'blocking': 1, 'error': 1, 'unknown': 2, 'empty': 2, 'wrong-suite': 2, 'write-error': 1}),
        (6, 'import_release_lab', '--report-path', {'gate-fixed': 1}),
        (7, 'order_state_lab', None, {}), (7, 'hook_protocol_lab', None, {}),
        (8, 'atomic_reservation_lab', None, {}), (8, 'ci_signal_lab', None, {'true-red': 1}),
        (8, 'envelope_boundary_lab', None, {}),
        (9, 'cancellation_lab', '--report-path', {'leak': 1}), (9, 'repair_mapping_lab', None, {}),
        (10, 'loop_control_lab', None, {}), (10, 'order_transition_lab', '--report-path', {'refuse-all': 1}),
        (10, 'candidate_loop_lab', '--run-dir', {}),
        (11, 'schedule_lab', None, {}), (11, 'purchase_request_lab', '--report-path', {'premature-stock': 1}),
        (11, 'integration_lab', '--run-dir', {}),
        (12, 'graph_control_lab', None, {}), (12, 'purchase_approval_lab', '--report-path', {'status-write-failure': 1, 'key-collision': 1}),
        (13, 'task_api_lab', '--output', {}), (13, 'completed_restart_lab', None, {}),
        (16, 'restore_lab', '--output-dir', {}),
    ]
    cases = []
    for lesson, script, flag, exits in specs:
        path = ROOT / f'docs/courses/L{lesson:02d}/examples/{script}.py'
        for mode in modes(path):
            name = f'L{lesson:02d}-{script}-{mode or "default"}'
            args = [str(path)] + ([mode] if mode else [])
            report = None
            if flag:
                target = out / name / ('report.json' if flag == '--report-path' else 'run')
                args += [flag, str(target)]
                if flag == '--report-path' and mode not in {'unknown', 'empty', 'wrong-suite', 'write-error'}:
                    report = target
            cases.append((lesson, name, args, exits.get(mode, 0), report))
    for name, args, expected in [
        ('normal', [], 0), ('defect', ['--defect'], 1), ('transfer', ['--opening', '11', '--quantity', '3'], 0),
    ]:
        cases.append((5, 'L05-receiving-'+name, [str(ROOT/'docs/courses/L05/examples/receiving_eval.py'), *args], expected, None))
    for name, arguments, expected in [('normal', [], 0), ('defect', ['--defect'], 1)]:
        cases.append((5, 'L05-scope-'+name, [str(ROOT/'docs/courses/L05/examples/write_scope_eval.py'), *arguments], expected, None))
    for name, args, expected in [
        ('evaluate', ['--evaluate', '--top-k', '2'], 0),
        ('revoked', ['--query', '空库存导出应该报错', '--include-revoked'], 1),
        ('filtered', ['--query', '空库存导出应该报错'], 0),
        ('snapshot', ['--query', '销售导出为零条记录时怎样保留机器可读结构', '--out', str(out/'rag-snapshot.json')], 0),
        ('duplicate', ['--query', '销售导出为零条记录时怎样保留机器可读结构', '--out', str(out/'rag-snapshot.json')], 1),
    ]:
        cases.append((15, 'L15-rag-'+name, [str(ROOT/'docs/courses/L15/examples/memory_rag_lab.py'), *args], expected, None))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--lesson', type=int, action='append', choices=[5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16],
                        help='Fixed-mode labs; file/HTTP/handoff workflows are covered by test_course_experiments.')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for lesson, name, arguments, expected, report in matrix(out):
        if args.lesson and lesson not in args.lesson:
            continue
        command = [sys.executable, '-B', '-X', 'utf8', *arguments]
        start = time.monotonic()
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), timeout=args.timeout)
            result = dict(name=name, command=command, expected_exit=expected, exit_code=completed.returncode,
                          stdout=completed.stdout, stderr=completed.stderr,
                          passed=completed.returncode == expected,
                          seconds=round(time.monotonic()-start, 2))
            if 'ModuleNotFoundError' in completed.stderr or 'ImportError:' in completed.stderr:
                result['passed'] = False
            if report:
                result['report_exists'] = report.is_file()
                result['passed'] &= report.is_file()
                if report.is_file():
                    try:
                        data = json.loads(report.read_text(encoding='utf-8'))
                        if any(x.get('error', {}).get('type') in {'ModuleNotFoundError', 'ImportError'}
                               for x in data.get('results', []) if x.get('error')):
                            result['passed'] = False
                    except (OSError, ValueError, AttributeError, TypeError) as exc:
                        result['passed'] = False
                        result['report_error'] = str(exc)
        except subprocess.TimeoutExpired as exc:
            result = dict(name=name, command=command, passed=False, error='timeout',
                          stdout=str(exc.stdout or ''), stderr=str(exc.stderr or ''))
        results.append(result)
        (out/(name+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (out/'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(('PASS ' if result['passed'] else 'FAIL ')+name, flush=True)
    failed = [r['name'] for r in results if not r['passed']]
    print(json.dumps(dict(total=len(results), failed=failed, evidence=str(out)), ensure_ascii=False), flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
