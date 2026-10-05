"""L13 localhost HTTP experiment. Real course Eval; isolated task DB; no Codex execution."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from workbench.cockpit import lesson_eval_runner
from workbench.workbench_server import WorkbenchApp, make_handler


def run(runtime: Path) -> dict:
    runtime.mkdir(parents=True, exist_ok=False)
    entered, release = threading.Event(), threading.Event()
    def factory(lesson):
        real_runner = lesson_eval_runner(lesson)
        def evaluate(*args, **kwargs):
            entered.set()
            if not release.wait(20):
                raise TimeoutError("实验等待放行超时")
            return real_runner(*args, **kwargs)
        return evaluate

    app = WorkbenchApp(runtime, eval_factory=factory)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    evidence = dict(basis='reference_localhost_real_eval', real_codex_execution=False,
                    student_achievement=False, erp_increment_proven=False, observations={})
    out = evidence['observations']
    task_id = None
    def request(method, path, body=None, key='L13-original'):
        connection = HTTPConnection('127.0.0.1', server.server_port, timeout=15)
        try:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
            connection.request(method, path, data, {'Content-Type':'application/json', 'Idempotency-Key':key})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
    def spec_count():
        return len(list((runtime/'course').rglob('FDE_SPEC.md')))

    try:
        body = dict(lesson=13, request='复验采购审批与交付证据边界', actor='student-example',
                    business_refs=['PURCHASE:ILLUSTRATIVE-ONLY'])
        code, accepted = request('POST', '/api/v1/delivery/requests', body)
        assert code == 202
        task_id = accepted['task_id']
        assert entered.wait(5) and not release.is_set()
        out['accepted_before_eval_finished'] = dict(http=code, response=accepted)
        code, running = request('GET', accepted['status_url'])
        assert code == 200 and running['status'] == 'evaluating'
        out['running'] = running

        before = spec_count()
        code, replay = request('POST', '/api/v1/delivery/requests', body)
        assert code == 202 and replay['task_id'] == task_id and spec_count() == before
        out['same_key_same_body'] = dict(http=code, task_id=replay['task_id'], spec_count=spec_count())
        conflicts = []
        for field, value in [('request','改成另一项需求'), ('actor','another-student'),
                             ('business_refs',['PURCHASE:OTHER'])]:
            count_before = spec_count()
            code, result = request('POST','/api/v1/delivery/requests',{**body,field:value})
            assert code == 409
            conflicts.append(dict(field=field,http=code,response=result,
                                  specs_before=count_before,specs_after=spec_count()))
        assert len(app.tasks.list()) == 1
        out['key_conflicts'] = conflicts
        out['code_mode_rejected'] = request('POST','/api/v1/delivery/requests',
                                            {**body,'execution_mode':'codex'},'code-mode')
        assert out['code_mode_rejected'][0] == 400
        out['missing_task'] = request('GET','/api/v1/tasks/TASK-MISSING')
        assert out['missing_task'][0] == 404

        release.set()
        final = app.automation.wait(task_id, timeout=30)
        assert final['status'] == 'review' and not final['reviewed_by']
        assert final['result']['summary']['decision'] == 'pass'
        assert final['result']['results'], 'No empty report may stand for a real Eval'
        out['real_eval_waiting_review'] = final

        version_before = final['version']
        app.tasks.append_event(task_id, '教学实验：记录一次查询说明', actor='student-example')
        after_event = app.tasks.get(task_id)
        out['event_version'] = dict(before=version_before, after=after_event['version'],
                                    event_count_before=len(final['events']),event_count_after=len(after_event['events']))
        assert after_event['version'] == version_before and len(after_event['events']) == len(final['events']) + 1

        barrier = threading.Barrier(2)
        def approve(name):
            barrier.wait(timeout=5)
            return request('POST', f'/api/v1/tasks/{task_id}/review',
                           dict(reviewer=name,decision='approve',note='教学实验身份字段；不是账号认证。核对本次真实课程 Eval。'))
        with ThreadPoolExecutor(max_workers=2) as pool:
            reviews = list(pool.map(approve, ['review-example-a','review-example-b']))
        assert sorted(item[0] for item in reviews) == [200,400]
        out['concurrent_reviews'] = reviews
        completed = app.tasks.get(task_id)
        reopened = WorkbenchApp(runtime).tasks.get(task_id)
        assert completed['status'] == reopened['status'] == 'completed'
        assert completed['events'] == reopened['events']
        out['completed_reopened_store'] = reopened
        assert not (runtime/'flowerp.db').exists()
        evidence['verified'] = True
    except Exception as exc:
        evidence.update(verified=False, error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        release.set()
        if task_id:
            app.automation.wait(task_id, timeout=30)
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        (runtime/'report.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    runtime = (args.output or ROOT/'.tmp'/f'l13-task-api-{uuid.uuid4().hex[:10]}').resolve()
    result = run(runtime)
    print(json.dumps({'verified':result['verified'],'report':str(runtime/'report.json')},ensure_ascii=False))
