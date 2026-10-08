"""Advanced capabilities use the same workbench HTTP and initiative identity."""
import json


def learning_metrics(app):
    with app.tasks.connect() as db:
        eligible = {r['id'] for r in db.execute("SELECT id FROM initiatives WHERE title NOT LIKE '[Mock课程演示]%'")}
        assets = [json.loads(r[0]) for r in db.execute('SELECT payload FROM learning_assets')]
        bindings = [(r['id'], r['task_id'], json.loads(r['payload'])) for r in db.execute('SELECT id,task_id,initiative_id,payload FROM learning_bindings') if r['initiative_id'] in eligible]
        outcomes = []
        for binding_id, task_id, payload in bindings:
            outcomes += [json.loads(r[0]) for r in db.execute("SELECT payload FROM learning_runs WHERE binding_id=? AND phase='outcome'", (binding_id,))]
    assets = [a for a in assets if a.get('source', {}).get('initiative_id') in eligible]
    rework = 0
    for _, task_id, _ in bindings:
        if not task_id:
            continue
        task = app.tasks.get(task_id)
        if task['status'] in {'rework', 'failed', 'dead_letter'}:
            rework += sum((e.get('evidence') or {}).get('duration_ms', 0) / 1000 for e in task['events'] if e.get('detail') == '受控执行阶段完成')
    return dict(eligible_initiatives=len(eligible), assets=len(assets), adoptions=sum(len(p.get('assets', [])) for _, _, p in bindings),
                successes=sum(o['passed'] is True for o in outcomes), failures=sum(o['passed'] is False for o in outcomes),
                failure_reasons=[{'task_id': o.get('task_id'), 'reason': o.get('note')} for o in outcomes if not o['passed']],
                rework_seconds=rework, repeated_failure_reduction='待测', sample_count=len(outcomes), scope='真实事项记录，排除课程演示')


def get(app, path, query):
    parts = path.strip('/').split('/')
    if path == '/api/v1/mutations/receipt':
        if set(query) != {'operation', 'key'} or any(len(values) != 1 for values in query.values()):
            raise ValueError('回执查询须提供唯一的operation和key')
        return 200, app.mutations.get(query['operation'][0], query['key'][0])
    if path.startswith('/api/v1/harness/'):
        if not app.harness_api:
            return 503, {'error': 'advanced_disabled', 'message': '请用--enable-advanced-runtime启动高级运行能力'}
        from urllib.parse import urlencode
        target = path.replace('/api/v1/harness/', '/api/v1/', 1)
        if query:
            target += '?' + urlencode(query, doseq=True)
        response = app.harness_api.dispatch('GET', target, {}, {})
        return response.status, response.body
    if len(parts) == 5 and parts[:3] == ['api', 'v1', 'projects'] and parts[-1] == 'plan':
        return 200, app.project_plans.get(parts[3])
    if len(parts) == 5 and parts[:3] == ['api', 'v1', 'initiatives']:
        if parts[-1] == 'runtime':
            return 200, {**app.delivery_runtime.view(parts[3]), 'advanced_enabled': app.advanced_enabled}
        if parts[-1] == 'deployments':
            return 200, app.deployments.list(parts[3])
    if len(parts) == 5 and parts[:3] == ['api', 'v1', 'tasks'] and parts[-1] == 'preview-plan':
        return 200, app.previews.plan(parts[3])
    if path == '/api/v1/migration/plan':
        from .migration import migration_plan
        return 200, migration_plan(app.runtime, app.projects)
    if path == '/api/v1/learning/metrics':
        return 200, learning_metrics(app)
    return None


def post(app, path, body, headers, address):
    parts = path.strip('/').split('/')
    handled = (path.startswith('/api/v1/harness/') or path == '/api/v1/migration/prepare' or
               (len(parts) == 5 and parts[:3] == ['api', 'v1', 'projects'] and parts[-1] == 'plan') or
               (len(parts) >= 6 and parts[:3] == ['api', 'v1', 'initiatives'] and parts[4] in {'runtime', 'deployments'}))
    if not handled:
        return None
    # The HTTP entry point has already validated Host and Origin for every route.
    if address not in {'127.0.0.1', '::1'}:
        return 403, {'error': 'cross_origin', 'message': '请从本机工作台操作'}
    actor = app.initiative_workflow.actor(body.get('actor'))
    if path.startswith('/api/v1/harness/'):
        if not app.harness_api:
            return 503, {'error': 'advanced_disabled', 'message': '高级运行未启用'}
        response = app.harness_api.dispatch('POST', path.replace('/api/v1/harness/', '/api/v1/', 1), dict(headers), body)
        return response.status, response.body
    key = body.get('submission_key')
    revision = body.get('expected_revision')
    def mutate(producer, status=200):
        return status, app.mutations.run(path, key, body, producer)
    if parts[:3] == ['api', 'v1', 'projects']:
        return mutate(lambda: app.project_plans.save(parts[3], body, actor, revision))
    if path == '/api/v1/migration/prepare':
        if body.get('confirmed') is not True:
            raise ValueError('请核对迁移边界后明确准备迁移包')
        from .migration import prepare_migration
        # Backup requires an exclusive span; do not reserve a DB mutation while frozen.
        return mutate(lambda: prepare_migration(app.runtime, app.projects, actor, app.backup_busy), 201)
    item_id, area, action = parts[3:6]
    if area == 'deployments':
        service = app.deployments
        if action == 'prepare':
            return mutate(lambda: service.prepare(item_id, actor, revision, body.get('profile_id')), 201)
        if action == 'start':
            return mutate(lambda: service.start(item_id, actor, revision, body.get('plan_id'), body.get('confirmed')), 202)
        if action == 'rollback':
            return mutate(lambda: service.rollback(item_id, actor, revision, body.get('deployment_id'), body.get('confirmed')), 202)
        if action == 'verify':
            return mutate(lambda: service.verify(item_id, actor, revision, body.get('deployment_id'), body.get('business_evidence'), body.get('conclusion')))
    if area == 'runtime':
        service = app.delivery_runtime
        if action == 'control':
            return mutate(lambda: service.control(item_id, body.get('action'), actor, revision,
                                                  body.get('candidate_sha256', ''),
                                                  run_id=body.get('run_id'),
                                                  session_id=body.get('session_id'),
                                                  control_revision=body.get('control_revision')))
        if not app.advanced_enabled:
            return 503, {'error': 'advanced_disabled', 'message': '请用--enable-advanced-runtime启用分工与工具授权'}
        if action == 'profile':
            return mutate(lambda: service.select_profile(item_id, body.get('profile_id'), actor, revision))
        if action == 'approvals' and len(parts) == 7:
            return mutate(lambda: service.decide_approval(item_id, parts[6], body.get('decision'), actor, revision, body.get('note', '')))
        if action == 'subtasks' and len(parts) == 7:
            if parts[-1] == 'prepare':
                return mutate(lambda: service.prepare_subtasks(item_id, actor, revision, body.get('subtasks'), max_workers=body.get('max_workers', 2)), 201)
            if parts[-1] == 'start':
                app.project_plans.assert_ready(item_id)
                from .migration import assert_migration_preflight
                assert_migration_preflight(app.runtime, app.initiatives.get(item_id)['project_id'])
                return mutate(lambda: service.start_subtasks(item_id, actor, revision, key, body.get('plan_id')), 202)
    return 404, {'error': 'not_found'}
