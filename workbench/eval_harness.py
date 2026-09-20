"""Project Eval evidence: validate results and expose freshness without granting acceptance."""
import hashlib
import json
from pathlib import Path


def fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode('utf-8')).hexdigest()


def validate_project_report(report, returncode):
    if not isinstance(report, dict):
        raise RuntimeError('项目 Eval 报告必须是对象')
    summary = report.get('summary')
    if not isinstance(summary, dict) or summary.get('decision') not in {'pass', 'block'}:
        raise RuntimeError('项目 Eval 报告缺少 pass/block 决策')
    if returncode != (0 if summary['decision'] == 'pass' else 1):
        raise RuntimeError('项目 Eval 退出码与报告结论不一致')
    results = report.get('results')
    if not isinstance(results, list) or not results:
        raise RuntimeError('项目 Eval 必须包含非空分项结果，不能使用空绿灯')
    names = set()
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name'].strip():
            raise RuntimeError('项目 Eval 用例名称无效')
        if row['name'] in names:
            raise RuntimeError('项目 Eval 用例名称重复')
        names.add(row['name'])
        if type(row.get('passed')) is not bool or row.get('level') not in {'blocking', 'observing'}:
            raise RuntimeError('项目 Eval 分项状态或等级无效')
    counts = dict(total=len(results), passed=sum(r['passed'] for r in results),
                  blocking_failed=sum(not r['passed'] and r['level'] == 'blocking' for r in results),
                  observing_failed=sum(not r['passed'] and r['level'] == 'observing' for r in results))
    for key, value in counts.items():
        # Older registered projects may omit the zero observing count.
        actual = summary.get(key, 0 if key == 'observing_failed' else None)
        if type(actual) is not int or actual != value:
            raise RuntimeError('项目 Eval 汇总与逐项结果不一致：' + key)
    if summary['decision'] != ('block' if counts['blocking_failed'] else 'pass'):
        raise RuntimeError('项目 Eval 阻断失败不能声明通过')


def report_view(report, workspace, runtime):
    """Historical reports without a source binding are explicitly unverified."""
    if not report:
        return {'available': False, 'freshness': 'unverified'}
    runner = report.get('runner') or {}
    view = {'available': True, 'summary': report.get('summary'), 'results': report.get('results', []),
            'runner': runner, 'generated_at': report.get('generated_at'), 'freshness': 'unverified'}
    if runner.get('candidate_sha256') and workspace:
        from .daily_delivery import manifest
        try:
            current = fingerprint(manifest(workspace, runtime))
            path = Path(runtime) / report['report_path'] if report.get('report_path') else Path(runner['report_path'])
            valid_file = hashlib.sha256(path.read_bytes()).hexdigest() == report.get('report_sha256')
            view['freshness'] = 'current' if current == runner['candidate_sha256'] and valid_file else 'stale'
        except (OSError, ValueError, KeyError):
            view['freshness'] = 'unavailable'
    return view
