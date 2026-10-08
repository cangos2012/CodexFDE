const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {dom} = require('./web_dom.cjs');

function setup() {
  const ui = dom(), calls = [], pending = [];
  const html = fs.readFileSync('workbench_web/index.html', 'utf8');
  for (const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const el = ui.element(match[1]);
    el.hidden = /\bhidden\b/.test(match[2]);
    el.disabled = /\bdisabled\b/.test(match[2]);
    el.scrollIntoView = () => {};
    el.focus = () => {};
    Object.defineProperty(el, 'innerHTML', {set() {this.children = []; this.textContent = '';}});
    ui.nodes.set(match[3], el);
  }
  const context = vm.createContext({document: ui.document, Date, setTimeout, clearTimeout,
    crypto: require('node:crypto').webcrypto});
  vm.runInContext(fs.readFileSync('workbench_web/app.js', 'utf8').replace(/boot\(\);\s*$/, ''), context);
  context.api = (url, options) => {
    calls.push({url, options});
    return new Promise((resolve, reject) => pending.push({resolve, reject}));
  };
  context.workspaceView = () => {};
  context.refreshTasks = async () => {};
  ui.node('task-actor').value = '课堂同学';
  return {...ui, context, calls, pending, html};
}

function prepared(overrides = {}) {
  return {
    ready: true, message: '检查条件已就绪', verification_key: 'fixture-verification-key',
    checks: [{name: 'purchase_requires_approval', label: '采购未经审批不能入库', target: 'FlowERP'},
      {name: 'receiving_is_idempotent', label: '相同入库幂等键只生效一次', target: 'FlowERP'}],
    target: {workbench_root: 'D:\\student\\Workbench', project_id: 'PROJ-ERP', product_root: 'D:\\student\\FlowERP'},
    projects: [{id: 'PROJ-ERP', name: '我的 FlowERP', root_path: 'D:\\student\\FlowERP'}],
    limitations: ['L12 只执行列出的 ERP 业务自动检查；Graph 与具名人审按课程手册完成。'],
    issues: [], ...overrides,
  };
}

async function ready(a, lesson = '12', body = prepared()) {
  a.node('task-lesson').value = lesson;
  const operation = a.context.refreshCourseVerification();
  a.pending.at(-1).resolve(body);
  await operation;
}

test('the course composer names its purpose and keeps remarks optional', () => {
  const a = setup();
  assert.match(a.html, /打开课程任务与复验/);
  assert.match(a.html, /＋ 课程任务/);
  assert.match(a.html, /日常新需求从上方“新建交付事项”/);
  const field = a.html.match(/<textarea id="task-request"[^>]*>/)[0];
  assert.doesNotMatch(field, /\brequired\b/);
  assert.match(a.html, /备注只随复验记录保存/);
  assert.equal(a.node('task-submit').disabled, true);
  assert.equal(a.node('mode-codex').disabled, true);
});

test('submission without confirmed prerequisites sends no request', async () => {
  const a = setup();
  a.node('task-lesson').value = '12';
  a.node('task-submit').disabled = false;
  await a.context.submitTask({preventDefault() {}});
  assert.equal(a.calls.length, 0);
  assert.equal(a.node('task-submit').disabled, true);
  assert.match(a.node('task-submit-status').textContent, /尚未核对就绪/);
});

test('the read shows real checks, target and L12 boundaries before enabling submit', async () => {
  const a = setup();
  a.node('task-lesson').value = '12';
  const read = a.context.refreshCourseVerification();
  assert.equal(a.node('task-submit').disabled, true);
  assert.equal(a.calls[0].url, '/api/course/verification?lesson=12');
  a.pending[0].resolve(prepared());
  await read;
  assert.equal(a.node('verification-checks').children.length, 2);
  assert.match(a.node('verification-checks').children[0].textContent, /采购未经审批不能入库.*FlowERP/);
  assert.match(a.node('verification-target').textContent, /D:\\student\\FlowERP/);
  assert.match(a.node('verification-limitations').children[0].textContent, /Graph.*具名人审/);
  assert.equal(a.node('verification-project').value, 'PROJ-ERP');
  assert.equal(a.node('task-submit').disabled, false);
});

test('missing project configuration stops before creation and gives a repair action', async () => {
  const a = setup();
  await ready(a, '12', prepared({ready: false, target: {workbench_root: 'D:\\student\\Workbench'}, projects: [],
    issues: [{code: 'project_missing', message: '尚未登记 FlowERP 项目', action: '回首页添加已有源码目录并创建 .venv'}]}));
  assert.equal(a.node('task-submit').disabled, true);
  assert.equal(a.node('verification-configure').hidden, false);
  assert.match(a.node('verification-issues').children[0].textContent, /尚未登记.*添加已有源码目录.*\.venv/);
  await a.context.submitTask({preventDefault() {}});
  assert.equal(a.calls.length, 1);
  assert.match(a.node('task-submit-status').textContent, /尚未核对就绪/);
});

test('workbench-only checks do not present an ERP project as a missing prerequisite', async () => {
  const a = setup();
  await ready(a, '13', prepared({checks: [{name: 'task_api', label: '工作台任务 API', target: '工作台'}],
    target: {workbench_root: 'D:\\student\\Workbench'}}));
  assert.equal(a.node('verification-project').disabled, true);
  assert.equal(a.node('verification-project').value, '');
  assert.match(a.node('verification-target').textContent, /本讲固定检查不涉及 ERP 源码/);
  assert.equal(a.node('task-submit').disabled, false);
});

test('multiple ERP projects require a choice and send its id in the preparation read', async () => {
  const a = setup();
  await ready(a, '12', prepared({ready: false, target: {workbench_root: 'D:\\student\\Workbench'},
    projects: [{id: 'ERP-ONE', name: 'FlowERP 一班', root_path: 'D:\\one'}, {id: 'ERP-TWO', name: 'FlowERP 二班', root_path: 'D:\\two'}],
    issues: [{code: 'project_required', message: '请选择本次项目', action: '选择后重新核对'}]}));
  assert.equal(a.node('verification-project').children.length, 3);
  a.node('verification-project').value = 'ERP-TWO';
  const read = a.context.refreshCourseVerification();
  assert.equal(a.calls.at(-1).url, '/api/course/verification?lesson=12&project_id=ERP-TWO');
  a.pending.at(-1).resolve(prepared({target: {workbench_root: 'D:\\student\\Workbench', project_id: 'ERP-TWO', product_root: 'D:\\two'}}));
  await read;
  assert.equal(a.node('task-submit').disabled, false);
});

for (const note of ['', '请帮我实现新的销售页面']) test('course submission uses fixed lesson scope and optional remark: ' + (note ? 'filled' : 'empty'), async () => {
  const a = setup();
  await ready(a);
  a.node('task-request').value = note;
  const submission = a.context.submitTask({preventDefault() {}});
  const call = a.calls.at(-1);
  assert.equal(call.url, '/api/v1/delivery/requests');
  const payload = JSON.parse(call.options.body);
  assert.equal(payload.request, 'L12 课程复验' + (note ? '\n复验备注：' + note : ''));
  assert.equal(payload.project_id, 'PROJ-ERP');
  assert.equal(payload.verification_key, 'fixture-verification-key');
  assert.equal(payload.lesson, 12);
  assert.equal(a.node('task-submit').disabled, true);
  a.pending.at(-1).resolve({accepted: true, task_id: 'TASK-COURSE'});
  await submission;
  assert.equal(a.node('task-composer').hidden, true);
});

test('an older lesson response cannot replace the current verification or enable submit', async () => {
  const a = setup();
  a.node('task-lesson').value = '12';
  const first = a.context.refreshCourseVerification();
  a.node('task-lesson').value = '13';
  const second = a.context.refreshCourseVerification();
  a.pending[1].resolve(prepared({checks: [{name: 'task_api', label: '任务 API 检查', target: '工作台'}]}));
  await second;
  a.pending[0].resolve(prepared());
  await first;
  assert.match(a.node('verification-checks').children[0].textContent, /任务 API/);
  assert.doesNotMatch(a.node('verification-checks').children[0].textContent, /采购/);
  assert.equal(a.context.courseVerificationReady(), true);
});

test('a server precondition rejection invalidates the old target and requires a new read', async () => {
  const a = setup();
  await ready(a);
  const submission = a.context.submitTask({preventDefault() {}});
  const error = new Error('项目目录在核对后发生变化');
  error.code = 'course_verification_not_ready';
  error.verification = prepared({ready: false, issues: [{code: 'target_changed',
    message: '项目目录已变化', action: '重新核对目标目录'}]});
  a.pending.at(-1).reject(error);
  await submission;
  assert.equal(a.node('task-submit').disabled, true);
  assert.equal(a.context.courseVerificationReady(), false);
  assert.equal(a.node('verification-checks').children.length, 0);
  assert.equal(a.node('verification-target').textContent, '');
  assert.match(a.node('verification-status').textContent, /条件已变化.*重新核对条件/);
  assert.match(a.node('task-submit-status').textContent, /尚未创建任务/);
  const calls = a.calls.length;
  await a.context.submitTask({preventDefault() {}});
  assert.equal(a.calls.length, calls);
});

test('remarks exceeding the declared limit are kept for the student to edit without sending', async () => {
  const a = setup();
  await ready(a);
  const note = '长'.repeat(961);
  a.node('task-request').value = note;
  await a.context.submitTask({preventDefault() {}});
  assert.equal(a.calls.length, 1);
  assert.equal(a.node('task-request').value, note);
  assert.match(a.node('task-submit-status').textContent, /最多 960 字.*原文已保留/);
});

test('an explicit server rejection gives its reason instead of suggesting an uncertain retry', async () => {
  const a = setup();
  await ready(a);
  const submission = a.context.submitTask({preventDefault() {}});
  const error = new Error('署名字段格式无效'); error.status = 400;
  a.pending.at(-1).reject(error);
  await submission;
  assert.match(a.node('task-submit-status').textContent, /服务器未接受.*署名字段格式无效/);
  assert.doesNotMatch(a.node('task-submit-status').textContent, /未确认受理结果|重试同一内容/);
});

test('an older failure cannot replace the current preparation and a current failed read removes readiness', async () => {
  const a = setup();
  a.node('task-lesson').value = '12';
  const first = a.context.refreshCourseVerification();
  a.node('task-lesson').value = '14';
  const second = a.context.refreshCourseVerification();
  a.pending[1].resolve(prepared());
  await second;
  a.pending[0].reject(new Error('old offline'));
  await first;
  assert.equal(a.node('task-submit').disabled, false);
  assert.doesNotMatch(a.node('verification-status').textContent, /old offline/);
  const current = a.context.refreshCourseVerification();
  assert.equal(a.node('task-submit').disabled, true);
  a.pending[2].reject(new Error('current offline'));
  await current;
  assert.equal(a.context.courseVerificationReady(), false);
  assert.match(a.node('verification-status').textContent, /current offline.*重新核对条件/);
  assert.equal(a.node('verification-checks').children.length, 0);
});

test('changing project while a read is pending rejects the response for the previous project', async () => {
  const a = setup();
  a.node('task-lesson').value = '12';
  a.node('verification-project').value = 'ERP-ONE';
  const first = a.context.refreshCourseVerification();
  a.node('verification-project').value = 'ERP-TWO';
  a.pending[0].resolve(prepared({target: {project_id: 'ERP-ONE', product_root: 'D:\\one'}}));
  await first;
  assert.equal(a.node('task-submit').disabled, true);
  assert.equal(a.context.courseVerificationReady(), false);
});

test('changing lesson invalidates contract success and errors from earlier reads', async () => {
  const a = setup(), rendered = [];
  a.context.renderContract = body => rendered.push(body.title);
  a.node('task-lesson').value = '12';
  const first = a.context.showCourse('12');
  a.node('task-lesson').value = '13';
  const second = a.context.showCourse('13');
  a.pending[1].resolve({title: 'L13'}); await second;
  a.pending[0].reject(new Error('old contract offline')); await first;
  assert.deepEqual(rendered, ['L13']);
});

test('failure diagnostics show the Chinese meaning, original reason and action as text', () => {
  const a = setup(), hostile = '<img src=x onerror=alert(1)>';
  const evaluation = {verification_target: {product_root: 'D:\\student\\FlowERP'},
    diagnostics: [{name: 'receiving_is_idempotent', label: '相同入库键只生效一次', kind: 'environment',
      message: '缺少独立项目 .venv ' + hostile, action: '先配置虚拟环境，再在原任务复验'}]};
  const rows = a.context.renderEvalDiagnostics(evaluation);
  assert.equal(rows.length, 1);
  assert.match(a.node('eval-diagnostics').children[0].textContent, /配置问题.*相同入库键只生效一次/);
  assert.match(a.node('eval-diagnostics').children[0].textContent, /缺少独立项目 \.venv/);
  assert.ok(a.node('eval-diagnostics').children[0].textContent.includes(hostile));
  assert.equal(a.node('eval-diagnostics').children[0].children.length, 0);
  assert.match(a.node('eval-target').textContent, /D:\\student\\FlowERP/);
  a.context.renderEvalDiagnostics({});
  assert.equal(a.node('eval-diagnostics').children.length, 0);
  assert.equal(a.node('eval-target').textContent, '');
});

test('historical reports keep raw errors when diagnostics are unavailable', () => {
  const a = setup();
  a.context.renderEvalDiagnostics({results: [{name: 'historical_case', passed: false, error: {message: 'original missing field: approval_by'}}]});
  assert.match(a.node('eval-diagnostics').children[0].textContent, /original missing field: approval_by/);
  assert.match(a.node('eval-diagnostics').children[0].textContent, /复验只检查.*不会自动修改代码/);
});

test('passed and failed check rows use backend Chinese labels and retain their raw names', () => {
  const a = setup();
  a.context.renderCases([
    {name: 'receiving_is_idempotent', passed: true, level: 'blocking'},
    {name: 'purchase_requires_approval', passed: false, level: 'blocking'},
  ], [{name: 'purchase_requires_approval', passed: false, error: {message: 'approval missing'}}], [], {
    receiving_is_idempotent: '相同入库幂等键只生效一次',
    purchase_requires_approval: '采购未经审批不能入库',
  });
  const rows = a.node('eval-cases').children;
  assert.match(rows[0].textContent, /通过 · 相同入库幂等键只生效一次（receiving_is_idempotent） · blocking/);
  assert.match(rows[1].textContent, /失败 · 采购未经审批不能入库（purchase_requires_approval） · blocking/);
  assert.match(rows[1].textContent, /原始原因：approval missing/);
});

test('historical rows without backend labels keep the original name and render labels as text', () => {
  const a = setup();
  a.context.renderCases([{name: 'historical_case', passed: true, level: 'blocking'}]);
  assert.equal(a.node('eval-cases').children[0].textContent, '通过 · historical_case · blocking');
  const hostile = '<img src=x onerror=alert(1)>';
  a.context.renderCases([{name: 'other_case', passed: true}], [], [], {other_case: hostile});
  assert.ok(a.node('eval-cases').children[0].textContent.includes(hostile));
  assert.equal(a.node('eval-cases').children[0].children.length, 0);
});

test('verification controls respect service freeze and code execution approval gates', async () => {
  const a = setup();
  await ready(a);
  vm.runInContext('workbenchServiceFrozen = true;', a.context);
  a.context.updateCourseVerificationSubmit();
  assert.equal(a.node('task-submit').disabled, true);
  vm.runInContext('workbenchServiceFrozen = false; webCodeAvailable = true;', a.context);
  a.context.chooseComposerMode('codex');
  assert.equal(a.node('verify-fields').hidden, true);
  assert.equal(a.node('task-submit').disabled, true);
  assert.doesNotMatch(a.node('mode-help').textContent, /不会调用 Codex 修改代码/);
  assert.equal(a.calls.filter(call => call.options?.method === 'POST').length, 0);
  a.context.chooseComposerMode('verify');
  assert.equal(a.node('task-submit').disabled, false);
});
