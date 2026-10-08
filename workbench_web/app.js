let selectedTask = null;
let detailVersion = 0;
let listVersion = 0;
let taskCache = [];
let taskFilter = "all";
let progressTimer = null;
let pendingSubmission = null;
let executionPlan = null;
let webCodeAvailable = false;
let composerMode = 'verify';
let courseVerificationState = null;
let courseVerificationReadVersion = 0;
let courseContractReadVersion = 0;
let courseVerificationSubmitting = false;
let courseCodeReadinessMessage = '';
let selectedInitiativeBinding = null;
let deliveryPanel = 'summary';
let workbenchServiceIdentity = null;
let workbenchServiceFrozen = false;
let workbenchFreezeObserver = null;
let workbenchStartupReady = false;
let workbenchStartupPending = null;
let workbenchStartupBlocked = false;
const workbenchWriteButtons = ['save-initiative','decide-initiative','v0-submit','iw-discuss','iw-recheck','iw-defer-people',
  'iw-confirm-prd','iw-confirm','iw-execute','iw-accept','iw-integrate','iw-cancel','iw-release','iw-outcome','iw-reopen',
  'iw-eval-run','iw-loop-save','iw-ci-record','iw-hook-prepare','iw-learning-create','iw-learning-decide','iw-learning-generate',
  'iw-learning-cancel-generation','iw-learning-recall','iw-learning-trial','iw-runtime-profile-save','iw-runtime-pause',
  'iw-runtime-resume','iw-runtime-cancel','iw-subtask-prepare','iw-subtask-start','iw-deployment-prepare','iw-deployment-start',
  'iw-deployment-verify','iw-rollback-confirm','preview-plan-start','action-approve','action-reject','action-verify',
  'task-submit','authorize-code','prepare-code','prepare-preview','project-register','plan-save','migration-prepare','backup-create'];
function workbenchWritesFrozen(){return workbenchServiceFrozen || workbenchStartupBlocked;}
function applyWorkbenchServiceFreeze() {
  for(const id of workbenchWriteButtons){const button=document.getElementById(id);if(button && !button.disabled)button.disabled=true;}
  document.querySelectorAll('#iw-learning-assets button,#iw-runtime-approvals button,#backup-list button,[data-service-write]').forEach(button=>{if(!button.disabled)button.disabled=true;});
}
function freezeWorkbenchService(message) {
  if(!workbenchServiceFrozen && typeof WorkbenchDrafts!=='undefined')WorkbenchDrafts.flush();
  workbenchServiceFrozen=true;executionPlan=null;
  const text=message+'。关键操作已冻结，未提交草稿保留。请重新载入页面并核对服务、运行目录与当前事项；不会自动采用新的服务身份。';
  const banner=document.getElementById('service-identity-status');if(banner){banner.hidden=false;banner.textContent=text;}
  show('data-status',text);
  if(typeof invalidateInitiativeWork==='function')invalidateInitiativeWork(text);
  if(typeof projectPlanState!=='undefined')projectPlanState.readable=false;
  if(typeof migrationState!=='undefined')migrationState.plan=null;
  applyWorkbenchServiceFreeze();
  if(typeof MutationObserver==='function' && document.body && !workbenchFreezeObserver) {
    workbenchFreezeObserver=new MutationObserver(applyWorkbenchServiceFreeze);
    workbenchFreezeObserver.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled']});
  }
}
function checkWorkbenchService(response) {
  if(typeof response.headers?.get!=='function')return;
  const service=response.headers.get('X-Workbench-Service-Instance'),runtime=response.headers.get('X-Workbench-Runtime-Instance');
  if(!service || !runtime || workbenchServiceIdentity && (service!==workbenchServiceIdentity.service || runtime!==workbenchServiceIdentity.runtime)) {
    freezeWorkbenchService('工作台服务实例或运行数据库身份缺失或变化，当前证据身份无法继续核对');throw new Error('工作台服务身份变化或缺失；请重新载入核对');
  }
  if(!workbenchServiceIdentity){workbenchServiceIdentity={service,runtime};if(typeof WorkbenchMutationJournal!=='undefined')WorkbenchMutationJournal.init(runtime);}
}
function selectDeliveryPanel(panel) {
  deliveryPanel = panel === 'evidence' ? 'evidence' : 'summary';
  document.getElementById('delivery-digest').hidden = deliveryPanel !== 'summary';
  document.getElementById('delivery-evidence').hidden = deliveryPanel !== 'evidence';
  document.querySelectorAll('[data-delivery-panel]').forEach(function(button) {
    button.classList.toggle('active', button.dataset.deliveryPanel === deliveryPanel);
    button.setAttribute('aria-pressed', String(button.dataset.deliveryPanel === deliveryPanel));
  });
}
function renderDigest(detail) {
  const container = document.getElementById('delivery-digest');
  container.innerHTML = '';
  const steps = [
    ['需求约定', document.getElementById('evidence-spec-summary').textContent, 'spec-card'],
    ['执行记录', document.getElementById('execution-summary').textContent + '\n' + document.getElementById('evidence-diff').textContent, 'diff-card'],
    ['工作台复验', document.getElementById('evidence-eval').textContent + '\n' + document.getElementById('control-issues').textContent, 'control-card'],
    ['具名验收', document.getElementById('evidence-review').textContent + '\n' + document.getElementById('evidence-review-note').textContent, 'task-actions']
  ];
  steps.forEach(function(step, index) {
    const row = document.createElement('article');
    row.className = 'digest-entry digest-step-' + index;
    const heading = document.createElement('h3');
    heading.textContent = step[0];
    const body = document.createElement('p');
    body.textContent = step[1];
    const button = document.createElement('button');
    button.className = 'digest-link';
    button.type = 'button';
    button.textContent = index === 3 ? '查看验收决定 ↗' : '核对原始证据 ↗';
    button.onclick = function() { focusEvidence(step[2]); };
    row.appendChild(heading); row.appendChild(body); row.appendChild(button);
    container.appendChild(row);
  });
  show('digest-count', '按任务记录整理 · ' + (detail.events || []).length + ' 条原始事件可核对');
  selectDeliveryPanel(deliveryPanel);
}
function chooseComposerMode(mode) {
  composerMode = mode === 'codex' && webCodeAvailable ? 'codex' : 'verify';
  resetCodePlan();
  document.getElementById('verify-fields').hidden = composerMode === 'codex';
  document.getElementById('code-entry').hidden = composerMode !== 'codex';
  document.querySelectorAll('[data-mode]').forEach(function(button) {
    button.classList.toggle('active', button.dataset.mode === composerMode);
    button.setAttribute('aria-pressed', String(button.dataset.mode === composerMode));
  });
  show('mode-help', composerMode === 'verify'
    ? '按所选讲次的固定用例检查现有代码。备注不会生成新的检查，也不会调用 Codex 修改代码。' +
      (!webCodeAvailable && courseCodeReadinessMessage ? '\n代码执行条件：' + courseCodeReadinessMessage : '')
    : courseCodeReadinessMessage || '核对本讲课程范围和执行方案，具名授权后才会启动 Codex。');
  updateCourseVerificationSubmit();
}
function openComposer(binding) {
  try { actorName(); }
  catch(error) { show('identity-status', error.message); return; }
  selectedInitiativeBinding = binding && typeof binding.id === 'string' && binding.id.startsWith('INIT-') ? binding : null;
  chooseComposerMode(composerMode);
  document.getElementById('code-requirement-spec').hidden = !!selectedInitiativeBinding;
  document.querySelector('label[for="code-requirement-spec"]').hidden = !!selectedInitiativeBinding;
  if(selectedInitiativeBinding) show('mode-help', '需求来源：' + binding.id + ' · 版本 ' + binding.version + '。L15/L16 代码执行会使用已保存需求并记录任务关联；仅复验时不建立该关联。');
  document.getElementById('task-composer').showModal();
  refreshCourseVerification();
}
function focusEvidence(id) {
  if (['spec-card', 'diff-card', 'eval-card', 'control-card', 'event-history'].includes(id)) selectDeliveryPanel('evidence');
  const target = document.getElementById(id);
  if (target.tagName === 'DETAILS') target.open = true;
  target.scrollIntoView({behavior:'smooth', block:'center'});
  target.focus({preventScroll:true});
}
function resetCodePlan() {
  executionPlan = null;
  document.getElementById('task-form').hidden = false;
  document.getElementById('code-options').hidden = false;
  document.getElementById('code-plan').hidden = true;
  document.getElementById('code-bootstrap-field').hidden = document.getElementById('task-lesson').value !== '4';
  show('code-status', '');
}

async function prepareCode() {
  executionPlan = null;
  document.getElementById("code-plan").hidden = true;
  show("code-status", "正在核对课程基线与执行条件…");
  try {
    executionPlan = await api('/api/v1/execution/plans', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({lesson:Number(document.getElementById('task-lesson').value), actor:actorName(),
        eval_cases:document.getElementById('code-cases').value.split(/[,，]/).map(function(x){return x.trim();}).filter(Boolean),
        session_ref:document.getElementById('code-baseline').value.trim() || null,
        bootstrap_task_id:document.getElementById('code-bootstrap').value.trim() || null,
        requirement_spec_text:selectedInitiativeBinding ? null : document.getElementById('code-requirement-spec').value.trim() || null,
        initiative_id:selectedInitiativeBinding && selectedInitiativeBinding.id,
        initiative_version:selectedInitiativeBinding && selectedInitiativeBinding.version})});
    show('code-plan-text', '授权人：' + executionPlan.actor + '\n本讲：' + executionPlan.lesson_title + '\n任务：' + executionPlan.request +
      '\n验收要求：\n' + (executionPlan.acceptance || []).map(function(item){return '• ' + item;}).join('\n') +
      '\n\n' + executionPlan.boundary + '\n方案有效期：15 分钟');
    if (executionPlan.non_goals) show('code-plan-text', document.getElementById('code-plan-text').textContent + '\n本次不做：' + executionPlan.non_goals);
    if (executionPlan.material_version) show('code-plan-text', document.getElementById('code-plan-text').textContent +
      '\n课程材料：' + executionPlan.material_version.name + '\n' + executionPlan.material_version.validation);
    if (executionPlan.initiative) show('code-plan-text', document.getElementById('code-plan-text').textContent +
      '\n关联事项：' + executionPlan.initiative.title + ' · 版本 ' + executionPlan.initiative.version + '\n决定人：' + executionPlan.initiative.decision_by);
    if (executionPlan.bootstrap) {
      show('code-plan-text', document.getElementById('code-plan-text').textContent +
        '\n\n前置工作台验收：' + executionPlan.bootstrap.task_id +
        '\n独立复验人：' + executionPlan.bootstrap.evaluated_by +
        '\n接受人：' + executionPlan.bootstrap.reviewed_by);
    }
    show('code-plan-technical', '允许修改：' + executionPlan.write_scope.join('、') + '\n检查用例：' + executionPlan.eval_cases.join('、') +
      '\n起始提交：' + executionPlan.session_commit +
      (executionPlan.bootstrap ? '\n已验收控制源码指纹：' + executionPlan.bootstrap.source_sha256 : '') +
      (executionPlan.requirement_sha256 ? '\n本次需求合同指纹：' + executionPlan.requirement_sha256 : ''));
    document.getElementById('code-plan').hidden = false;
    document.getElementById('task-form').hidden = true;
    document.getElementById('code-options').hidden = true;
    document.getElementById('authorize-code').disabled = workbenchWritesFrozen();
    show('code-status', '尚未执行。确认上面的具体任务后再授权。');
  } catch (error) { show('code-status', String(error.message || error)); }
}

async function authorizeCode() {
  if (!executionPlan) return;
  document.getElementById('authorize-code').disabled = true;
  const plan = executionPlan;
  try {
    const actor = actorName();
    try { localStorage.setItem('workbench-pending-plan', plan.plan_id); } catch (_) { /* Storage is optional. */ }
    await api('/api/v1/execution/plans/' + plan.plan_id + '/authorize', {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({confirmation:plan.confirmation, actor:actor})});
    show('code-status', '已授权，正在创建隔离交付任务…');
    await followExecutionPlan(plan.plan_id);
  } catch (error) {
    show('code-status', '请核对或重试同一方案：' + String(error.message || error));
    document.getElementById('authorize-code').disabled = workbenchWritesFrozen();
  }
}

async function followExecutionPlan(planId) {
  const plan = await api('/api/v1/execution/plans/' + encodeURIComponent(planId));
  if (plan.task_id) {
    document.getElementById('task-composer').close();
    workspaceView('delivery');
    await refreshTasks(plan.task_id);
    if (plan.state === 'failed') {
      stopProgress();
      document.getElementById('execution-recovery').hidden = false;
      show('execution-recovery-status', '原方案已停止：' + (plan.error || '执行未完成') +
        (plan.task_record_error ? '\n' + plan.task_record_error : '') +
        '\n已打开原任务。请先核对失败记录与实际文件，再决定下一次交付。');
      return;
    }
    try { localStorage.removeItem('workbench-pending-plan'); } catch (_) { /* Storage is optional. */ }
    document.getElementById('execution-recovery').hidden = true;
  } else if (plan.state === 'failed') {
    show('code-status', '未能启动：' + plan.error);
    show('execution-recovery-status', '原方案已停止：' + plan.error);
  } else if (plan.state === 'prepared') {
    show('execution-recovery-status', '原方案尚未获授权，没有开始执行。请重新核对需求并准备方案。');
    show('code-status', '尚未授权，未开始执行。请核对方案后再决定。');
  } else {
    show('execution-recovery-status', '原方案正在创建任务，进度会自动更新。无需再次授权。');
    setTimeout(function(){ followExecutionPlan(planId).catch(function(error){
      show('code-status', '进度读取失败，请重试同一方案：' + error.message);
      show('execution-recovery-status', '进度暂时不可读，请再次查看原记录：' + error.message);
      document.getElementById('authorize-code').disabled = workbenchWritesFrozen();
    }); }, 2000);
  }
}

async function resumeExecution() {
  let id;
  try { id = localStorage.getItem('workbench-pending-plan'); } catch (_) { return; }
  if (!id) return;
  try { await followExecutionPlan(id); }
  catch(error) { show('execution-recovery-status', '原记录暂时不可读，请先核对任务列表，不要重复提交：' + error.message); }
}

function stopProgress() {
  if (progressTimer !== null) clearTimeout(progressTimer);
  progressTimer = null;
}

function workspaceView(view) {
  const delivery = view === "delivery";
  const decision = view === 'decision';
  if (!delivery) { stopProgress(); ++detailVersion; }
  document.getElementById("view-overview").hidden = view !== "overview";
  document.getElementById("view-course").hidden = view !== "course";
  document.getElementById('view-decision').hidden = !decision;
  document.getElementById("view-delivery").hidden = !delivery;
  show("page-section", delivery ? "交付记录" : view === "course" ? "课程与练习" : "项目交付");
  show("page-title", delivery ? "核对成果，再作出验收决定。" : view === "course" ? "通过真实交付，练习工程能力。" : "从目标，到可验收的结果。");
  document.getElementById("mock-notice").classList.toggle("course-notice", view === "course" || view === "delivery");
  if(view === "overview") refreshProjectHome();
  if (decision) { show('page-section', '事项与决策'); show('page-title', '把这项交付，向前推进一步。'); }
  document.querySelectorAll("[data-view]").forEach(function (button) {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

function openDelivery() {
  workspaceView('delivery');
  const first = taskCache.find(item => item.status.code === 'review') || taskCache[0];
  if (selectedTask || first) return loadDetail(selectedTask || first.task_id);
  return refreshTasks().catch(function () { /* Error is already visible. */ });
}

function renderPipeline(detail) {
  const code = detail.status.code;
  const stage = {queued:0,spec_ready:1,executing:2,evaluating:3,review:4,completed:4,rework:2}[code];
  const stages = ["确认需求", "准备合同", "执行方式", "自动检查", "人工验收"];
  const notes = ["由你限定范围", "保存任务约定", detail.policy && detail.policy.execution_mode === "codex" ? "已授权 Codex" : "本次仅复验", "检查真实结果", "由你接受或打回"];
  const container = document.getElementById("delivery-pipeline");
  container.innerHTML = "";
  stages.forEach(function (label, index) {
    const node = document.createElement("button");
    node.type = 'button';
    node.onclick = function() { focusEvidence(['spec-card','spec-card','diff-card','eval-card','task-actions'][index]); };
    node.className = "pipeline-step" + (stage === index ? " current" : "");
    const title = document.createElement("b");
    title.textContent = String(index + 1).padStart(2,"0") + " · " + label;
    const note = document.createElement("small");
    note.textContent = notes[index];
    node.appendChild(title); node.appendChild(note); container.appendChild(node);
  });
  show("delivery-status", detail.status.title || code);
  document.getElementById("next-action").className = "next-action state-" + code;
  show("decision-title", code === "review" ? "检查已结束，等待你的验收" : code === "rework" ? "这项交付还需要完善" : code === "completed" ? "已验收，保留交付证据" : "查看当前进度与下一步");
  const failure = document.getElementById('delivery-failure');
  failure.hidden = !['failed', 'dead_letter', 'rework'].includes(code);
  const lastEvent = (detail.events || []).slice(-1)[0] || {};
  const failureReason = detail.error || lastEvent.detail || '请展开核验证据，查看最后一条执行记录。';
  show('delivery-failure', failure.hidden ? '' : '本次停止原因：' +
    (failureReason.includes('起始基线没有稳定红灯') ?
      '本讲起始材料已经通过检查，无法证明本次新增了能力。请先更新课程起始材料，再开始交付。原记录已保留。' : failureReason));
  const reviewInput = document.getElementById("review-note");
  reviewInput.hidden = code !== "review";
  document.querySelector('label[for="review-note"]').hidden = code !== "review";
}

function renderWorkflowGraph(graph) {
  show('graph-version', graph.definition.id + ' · v' + graph.version);
  show('graph-summary', '当前节点：' + graph.current + '　责任人：' + graph.owner +
    (graph.waiting ? '　正在等待具名人工决定' : '') +
    (graph.migrated ? '　· 旧任务按当前事实迁移，未补造历史边' : ''));
  const nodes = document.getElementById('graph-nodes');
  nodes.replaceChildren();
  (graph.nodes || []).forEach(function(item) {
    const node = document.createElement('div');
    node.className = 'graph-node state-' + item.state;
    const mark = item.state === 'current' ? '●' : item.state === 'visited' ? '✓' : '○';
    node.textContent = mark + ' ' + item.id;
    nodes.appendChild(node);
  });
  const events = document.getElementById('graph-events');
  events.replaceChildren();
  (graph.events || []).forEach(function(event) {
    const row = document.createElement('li');
    row.textContent = (event.from_node || '开始') + ' → ' + event.to_node + ' · ' +
      event.actor + ' · ' + event.reason;
    events.appendChild(row);
  });
}

async function api(path, options) {
  if(workbenchServiceFrozen)throw new Error('工作台服务身份已变化，操作保持冻结；请重新载入核对');
  const read = !options || !options.method || options.method.toUpperCase() === "GET";
  if(!read && workbenchStartupBlocked)throw new Error('工作台初始化尚未完成，关键操作保持冻结；请使用刷新重新读取服务与能力，不会自动重放提交。');
  const controller = new AbortController();
  const timeoutMs = read ? 10000 : path==='/api/v1/projects' || /\/execution\/(?:daily-)?plans$/.test(path) ? 120000 : 30000;
  const timeoutError = new Error(read ? '读取超时，当前状态尚未确认；请重新读取原记录。' : '提交超时，结果尚未确认；请读取原事项或原方案核对，不要重复授权。');
  timeoutError.code='request_timeout';timeoutError.uncertain=!read;
  let timedOut=false,timer;
  const deadline=new Promise((_,reject)=>{timer=setTimeout(()=>{timedOut=true;reject(timeoutError);controller.abort();},timeoutMs);});
  try {
    const request=Object.assign({ cache: "no-store" },options,{signal:controller.signal});
    if(workbenchServiceIdentity) {
      const headers=typeof Headers==='function' ? new Headers(request.headers || {}) : {...request.headers};
      if(typeof headers.set==='function'){headers.set('X-Workbench-Expected-Service-Instance',workbenchServiceIdentity.service);headers.set('X-Workbench-Expected-Runtime-Instance',workbenchServiceIdentity.runtime);}
      else Object.assign(headers,{'X-Workbench-Expected-Service-Instance':workbenchServiceIdentity.service,'X-Workbench-Expected-Runtime-Instance':workbenchServiceIdentity.runtime});
      request.headers=headers;
    }
    const operation=(async()=>{
      const response = await fetch(path, request);
      if(timedOut)throw timeoutError;
      checkWorkbenchService(response);
      const body = await response.json();
      if(timedOut)throw timeoutError;
      if(workbenchServiceFrozen)throw new Error('工作台服务身份已变化，操作保持冻结；请重新载入核对');
      if(body?.error==='instance_changed'){freezeWorkbenchService(body.message || '工作台服务实例已变化');throw new Error(body.message || '服务身份不一致');}
      if (!response.ok) {
        const error = new Error(body.message || body.error || path);
        error.status = response.status;
        error.body = body;
        error.code = body.error;
        if (body.error === 'course_verification_not_ready') {
          error.verification = body.verification;
        }
        throw error;
      }
      return body;
    })();
    return await Promise.race([operation,deadline]);
  } finally {
    clearTimeout(timer);
  }
}

function show(id, text) {
  const node = document.getElementById(id);
  if (node) node.textContent = text;
}

function laneLabel(lane) {
  return lane === "erp" ? "FlowERP 案例" : "造台";
}

function ownerKind(ownerId) {
  const id = String(ownerId || "");
  if (id === "automation") return "工作台";
  if (id === "agent:reviewer") return "复验者";
  if (id.startsWith("agent:")) return "Codex";
  return "人";
}

function actorName() {
  const input = document.getElementById('task-actor');
  const name = input.value.trim();
  if (!name || name.length > 80 || name.toLowerCase().startsWith('agent:')) {
    input.scrollIntoView({block:'center'});
    input.focus({preventScroll:true});
    throw new Error(!name ? '请先填写你的姓名或课堂昵称，再开始交付。' :
      name.length > 80 ? '署名请控制在 80 个字以内。' : '不能使用 agent: 开头的执行器署名，请填写你的姓名或课堂昵称。');
  }
  show('identity-status', '已使用你的署名：' + name + '。决定会与证据一起保存。');
  return name;
}

function renderContract(course) {
  show("stage-band", "L" + String(course.lesson).padStart(2, "0") + " · " + (course.stage_band || ""));
  show("lesson-title", course.title || "");
  show("construction-stage", course.construction_stage || "");
  show("codex-role", course.codex_role || "");
  show("write-scope", (course.write_scope || []).join("、") || "本讲无额外写集");
  show("acceptance", (course.acceptance || []).join("；") || "本讲未声明验收点");
  show("eval-contract", (course.eval_cases || []).join("、") || "本讲未声明 Eval");
  const empty = document.getElementById("honest-empty");
  empty.hidden = !course.honest_empty;
  show(
    "bootstrap-state",
    course.bootstrap_state === "bootstrapped" ? "已自举：能查到 PERSONAL-WORKBENCH" : "尚未构造：不要把参考终态的命令当成自己的 V0.1",
  );
}

function renderTasks(items, selectedTaskId) {
  const list = document.getElementById("task-list");
  taskCache = items;
  const demoNotice = document.getElementById('mock-notice');
  if (demoNotice) demoNotice.hidden = !items.some(item => (item.business_refs || []).includes('MOCK:COURSE-SHOWCASE'));
  const guide = document.getElementById('first-steps-guide');
  if (guide && items.length) guide.open = false;
  show("metric-total", items.length);
  show("metric-review", items.filter(function (item) { return item.status.code === "review"; }).length);
  show("metric-rework", items.filter(function (item) { return item.status.code === "rework"; }).length);
  show("review-count", items.filter(function (item) { return item.status.code === "review"; }).length);
  items = items.filter(function (item) {
    if (taskFilter === 'active') return ['queued','spec_ready','executing','evaluating'].includes(item.status.code);
    if (taskFilter === 'terminal') return ['completed','failed','dead_letter'].includes(item.status.code);
    return taskFilter === "all" || item.status.code === taskFilter;
  });
  if (!items.length) {
    list.textContent = taskFilter === "all" ? "还没有交付任务。L01～L03 工作台正在被你造出来；L04 起可新建任务。" : "这个分类下暂无任务。";
    return;
  }
  list.innerHTML = "";
  items.forEach(function (view) {
    const button = document.createElement("button");
    button.className = "task";
    button.type = "button";
    if (view.task_id === selectedTaskId) button.classList.add("active");
    const lane = document.createElement("span");
    lane.className = "lane" + (view.lane === "erp" ? " lane-erp" : "");
    lane.textContent = laneLabel(view.lane);
    button.appendChild(lane);
    const name = document.createElement("span");
    name.className = "task-name";
    name.textContent = view.request || "未命名任务";
    button.title = name.textContent;
    const meta = document.createElement("span");
    meta.className = "task-meta";
    meta.textContent = ((view.status && (view.status.title || view.status.label)) || "未知阶段") + " · " + (view.task_id || "").replace("TASK-", "");
    button.appendChild(name); button.appendChild(meta);
    button.onclick = function () {
      list.querySelectorAll(".task").forEach(function (node) { node.classList.remove("active"); });
      button.classList.add("active");
      loadDetail(view.task_id).then(function () {
        const evidence = document.getElementById('evidence-card');
        if (selectedTask === view.task_id && evidence) evidence.scrollIntoView({behavior:'smooth', block:'start'});
      });
    };
    list.appendChild(button);
  });
}

function evalFailureMessage(item) {
  const error = item.error;
  const detail = error && typeof error === 'object' ? error.message : error;
  const evidence = item.evidence;
  return String(detail || (evidence && typeof evidence === 'object' ? JSON.stringify(evidence) : evidence) || item.message || '原报告未提供具体原因，请查看检查记录。');
}

function courseEvalDiagnostics(evalView) {
  if (Array.isArray(evalView.diagnostics) && evalView.diagnostics.length) return evalView.diagnostics;
  return (evalView.results || []).filter(function(item) { return item && !item.passed; }).map(function(item) {
    return {name: item.name, label: item.label || item.name, message: evalFailureMessage(item),
      action: '先核对原始原因和目标目录；配置问题先补齐环境，代码问题修复后在原任务再跑复验。复验只检查，不会自动修改代码。'};
  });
}

function renderCases(cases, results, diagnostics, checkLabels) {
  const list = document.getElementById("eval-cases");
  list.innerHTML = "";
  if (!cases || !cases.length) {
    const item = document.createElement("li");
    item.textContent = "还没有 Eval 报告。提交后才会跑本讲用例。";
    list.appendChild(item);
    return;
  }
  cases.forEach(function (item) {
    const diagnostic = (diagnostics || []).find(function(row) { return row.name === item.name; });
    const original = (results || []).find(function(row) { return row.name === item.name; });
    const mapped = checkLabels && Object.prototype.hasOwnProperty.call(checkLabels, item.name) ? checkLabels[item.name] : null;
    const label = (typeof mapped === 'string' && mapped) || (diagnostic && diagnostic.label) ||
      item.label || (original && original.label) || item.name || '未命名';
    const row = document.createElement("li");
    row.className = item.passed ? "case-pass" : "case-fail";
    row.textContent = (item.passed ? "通过" : "失败") + " · " +
      label + (item.name && label !== item.name ? '（' + item.name + '）' : '') +
      (item.level ? " · " + item.level : "") +
      (!item.passed && original ? '\n原始原因：' + evalFailureMessage(original) : '');
    list.appendChild(row);
  });
}

function renderEvalDiagnostics(evalView) {
  const diagnostics = courseEvalDiagnostics(evalView);
  const list = document.getElementById('eval-diagnostics');
  list.innerHTML = '';
  diagnostics.forEach(function(item) {
    const row = document.createElement('li');
    row.textContent = (item.kind === 'environment' ? '配置问题' : '未通过') + ' · ' + (item.label || item.name || '检查') +
      '\n原因：' + item.message + '\n处理：' + (item.action || '对照原报告修复后再在原任务复验。');
    list.appendChild(row);
  });
  const target = evalView.verification_target;
  show('eval-target', target ? '本报告检查目录：' + [target.workbench_root && '工作台 ' + target.workbench_root,
    target.product_root && 'FlowERP ' + target.product_root].filter(Boolean).join('；') : '');
  return diagnostics;
}

function renderControlSurface(surface) {
  const container = document.getElementById('control-surface');
  container.innerHTML = '';
  show('control-thesis', surface && surface.thesis ? surface.thesis : '控制面尚未生成。');
  const components = surface && Array.isArray(surface.components) ? surface.components : [];
  if (!components.length) {
    container.textContent = '还没有 control surface 投影，不能据此判断 Harness 外壳。';
    show('control-issues', '控制面缺失');
    return;
  }
  components.forEach(function(item) {
    const row = document.createElement('article');
    row.className = 'control-gate state-' + (item.state || 'unknown');
    const title = document.createElement('b');
    title.textContent = item.label || item.id || '未命名闸门';
    const state = document.createElement('span');
    state.textContent = item.state || 'unknown';
    const summary = document.createElement('p');
    summary.textContent = item.summary || '';
    row.appendChild(title);
    row.appendChild(state);
    row.appendChild(summary);
    container.appendChild(row);
  });
  const issues = surface && Array.isArray(surface.issues) ? surface.issues : [];
  show('control-issues', issues.length ? '控制面缺口：' + issues.join('、') : '四件套控制面已可核对。');
}

function renderActions(detail) {
  const actions = detail.allowed_actions || [];
  const verify = document.getElementById("action-verify");
  const approve = document.getElementById("action-approve");
  const reject = document.getElementById("action-reject");
  verify.hidden = actions.indexOf("run") < 0;
  approve.hidden = actions.indexOf("approve") < 0;
  reject.hidden = actions.indexOf("reject") < 0;
  if (detail.policy && detail.policy.execution_mode === 'codex') {
    verify.hidden = true;
    if (!(detail.events || []).some(function(event){return event.detail === '课程红绿差分判定已完成' && event.evidence && event.evidence.accepted === true;})) approve.hidden = true;
  }
  [verify, approve, reject].forEach(function (button) { button.disabled = workbenchWritesFrozen(); });
  verify.onclick = function () { runVerify(detail.task_id); };
  approve.onclick = function () { runReview(detail.task_id, "approve"); };
  reject.onclick = function () { runReview(detail.task_id, "reject"); };
}

async function preparePreview(taskId) {
  return openPlatformPreview(taskId,'task');
}

function renderEvidence(detail) {
  workspaceView("delivery");
  show('page-title', detail.request || '交付与验收');
  renderPipeline(detail);
  document.getElementById("task-detail").hidden = false;
  document.getElementById("evidence-empty").hidden = true;
  show("evidence-task-id", detail.task_id);
  const next = (detail.status && detail.status.next_action) || "先提交并复验";
  show("next-action", "下一步：" + next);
  show("evidence-request", detail.request || "");
  show("evidence-lane", laneLabel(detail.lane) + " · " + (detail.requirement_id || ""));
  show('evidence-business-refs', (detail.business_refs || []).join('\n') || '尚未关联业务对象');
  const initiativeEvent = (detail.events || []).find(event=>event.detail === '已关联具名决定的事项与冻结合同');
  const initiative = initiativeEvent && initiativeEvent.evidence;
  show('evidence-initiative', initiative ? '来源事项：' + initiative.title + ' · ' + initiative.id + ' · 版本 ' + initiative.version + ' · 决定人 ' + initiative.decision_by : '未关联事项记录');
  const owner = detail.status && detail.status.owner;
  show("evidence-owner", ((detail.status && detail.status.title) || "") + " / " + ownerKind(owner && owner.id) + " · " + ((owner && owner.label) || ""));
  const spec = Object.assign({}, detail.spec || {}, (detail.spec && detail.spec.content) || {});
  show("evidence-spec", spec.text || ['source','goal','non_goals','constraints','acceptance','done'].map(function(key,index) {
    return spec[key] ? ['来源','目标','本次不做','约束','验收用例','完成定义'][index] + '\n' + spec[key] : '';
  }).filter(Boolean).join('\n\n') || spec.title || spec.path || '尚无 Spec');
  show("evidence-spec-summary", (spec.goal || spec.title || "尚无任务约定").split("\n\n")[0]);
  show("evidence-scope", ((detail.policy && detail.policy.write_scope) || []).join("、") || "未声明写集");
  const evalView = detail.eval || {};
  const diagnostics = renderEvalDiagnostics(evalView);
  show("evidence-eval", evalView.available
    ? (({pass:"检查通过",block:"检查未通过"}[evalView.decision] || "结果未知") + " · 阻断失败 " + (evalView.blocking_failed || 0) + " 项" +
      (diagnostics.length ? '\n' + (diagnostics[0].label || diagnostics[0].name) + '：' + diagnostics[0].message +
        '\n' + (diagnostics[0].action || '修复后在原任务复验。') : ''))
    : "还没有 Eval 报告");
  const review = detail.review || {};
  show("evidence-review", review.reviewed_by
    ? (({approve:"已接受交付",reject:"已打回返工"}[review.decision] || "已记录审核") + " · " + review.reviewed_by)
    : (review.required ? "等待具名人审" : "尚未进入人审"));
  show("evidence-review-note", review.note || "尚无审核理由");
  const files = (detail.execution && detail.execution.changed_files) || [];
  const isCode = detail.policy && detail.policy.execution_mode === "codex";
  const canPreview = isCode && ['review','completed'].includes((detail.status || {}).code) &&
    (detail.events || []).some(event=>event.detail === '课程红绿差分判定已完成' && event.evidence && event.evidence.accepted === true);
  document.getElementById('candidate-preview').hidden = !canPreview;
  document.getElementById('preview-link').hidden = true;
  document.getElementById('prepare-preview').disabled = workbenchWritesFrozen();
  document.getElementById('prepare-preview').onclick = function(){ preparePreview(detail.task_id); };
  show('preview-status', '');
  const stopped = ['failed', 'dead_letter'].includes((detail.status || {}).code);
  show('role-human', review.reviewed_by ? '已由 ' + review.reviewed_by + ' 留下审核决定' : stopped ? '先核对停止原因与实际改动' : '限定范围 · 等待具名验收');
  show('role-codex', isCode ? (detail.execution && detail.execution.available ? '已留下执行记录，点击核对改动' : stopped ? '本次已停止，执行记录尚不完整' : '已授权，尚待执行证据') : '本次未调用，仅运行复验');
  renderControlSurface(detail.control_surface);
  const controlReady = detail.control_surface && detail.control_surface.ready;
  show('role-workbench', controlReady ? 'Harness 四件套已有可核对闸门' : stopped ? '控制面有缺口，请先核对停止原因' : '正在装载 Harness 控制面');
  show("execution-summary", isCode ? "本次已授权 Codex 修改代码" : "本次仅复验，未调用 Codex");
  show("evidence-diff", files.length ? files.join("\n") : isCode ? "尚无已记录的文件改动，请结合执行事件核对。" : "本次不修改文件；自动检查结果不能证明完成了新功能。");
  renderCases(evalView.cases, evalView.results, diagnostics, evalView.check_labels);
  renderActions(detail);
  renderEvents(detail.events);
  renderV0Evidence(detail);
  renderDigest(detail);
}

function renderV0Evidence(detail) {
  let panel=document.getElementById('v0-evidence-history');
  if(!panel){panel=document.createElement('details');panel.id='v0-evidence-history';document.getElementById('diff-card').appendChild(panel);}
  panel.replaceChildren();
  const heading=document.createElement('summary');heading.textContent='每轮调用、完整输出与检查命令';panel.appendChild(heading);
  const overview=document.createElement('pre');
  overview.textContent=JSON.stringify({contract_sha256:(detail.spec || {}).sha256,
    authorization:detail.policy, summary:detail.delivery_summary}, null, 2);
  panel.appendChild(overview);
  (detail.events || []).forEach(event=>{
    const evidence=event.evidence || {};
    if(!evidence.attempt_id && !evidence.validation)return;
    const row=document.createElement('section'), text=document.createElement('pre');
    text.textContent=JSON.stringify({event:event.id, at:event.created_at, attempt:evidence.attempt_id,
      invocation:evidence.invocation, returncode:evidence.returncode, timed_out:evidence.timed_out,
      provenance:evidence.provenance, validation:evidence.validation},null,2);
    row.appendChild(text);
    ['stdout','stderr','diff'].forEach(key=>{
      if(!(evidence.artifacts || {})[key])return;
      const link=document.createElement('a');
      link.href='/api/v1/tasks/'+encodeURIComponent(detail.task_id)+'/artifacts/'+event.id+'/'+key;
      link.target='_blank';link.rel='noopener';link.textContent='查看完整 '+key+'　';row.appendChild(link);
    });
    panel.appendChild(row);
  });
  const summary=detail.delivery_summary;
  if(summary)show('evidence-review-note', ((detail.review || {}).note || '尚无审核理由') + '\n剩余风险：' + summary.remaining_risks.join('；'));
}

function renderEvents(events) {
  const list = document.getElementById("task-events");
  list.innerHTML = "";
  const items = Array.isArray(events) ? events : [];
  show("event-count", "展开任务事件（" + items.length + " 条）");
  if (!items.length) {
    list.textContent = "尚无可查询的事件，不能据此认定执行成功。";
    return;
  }
  items.forEach(function (event) {
    const row = document.createElement("li");
    const heading = document.createElement("p");
    heading.textContent = "事件 " + event.id + " · " + (event.created_at || "时间未记录") +
      " · " + (event.actor || "未记录操作人") + " · " +
      (event.from_status || "起点") + " → " + (event.to_status || "未知状态");
    row.appendChild(heading);
    const description = document.createElement("p");
    description.textContent = event.detail || "无说明";
    row.appendChild(description);
    if (event.evidence !== null && event.evidence !== undefined) {
      const evidence = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "查看该事件的核验数据";
      const data = document.createElement("pre");
      data.textContent = JSON.stringify(event.evidence, null, 2);
      evidence.appendChild(summary);
      evidence.appendChild(data);
      row.appendChild(evidence);
    }
    list.appendChild(row);
  });
}

function renderUpgrade(upgrade) {
  if (!upgrade.available) {
    show("upgrade-text", upgrade.message || "还没有工作台升级记录");
    return;
  }
  show(
    "upgrade-text",
    (upgrade.classification || "") + " · " + (upgrade.status || "") + " · " + (upgrade.failure_signature || upgrade.id || ""),
  );
}

function clearEvidence(message) {
  show("delivery-status", "等待读取");
  document.getElementById("task-detail").hidden = true;
  document.getElementById("evidence-empty").hidden = false;
  show("evidence-empty", message);
  show("next-action", "请重新读取任务证据后再操作。");
  ["action-verify", "action-approve", "action-reject"].forEach(function (id) {
    document.getElementById(id).hidden = true;
    document.getElementById(id).disabled = true;
  });
}

async function refreshTasks(selectedTaskId) {
  stopProgress();
  const version = ++listVersion;
  ++detailVersion;
  if (selectedTaskId) selectedTask = selectedTaskId;
  clearEvidence("正在刷新任务，旧证据暂不可用于审核。");
  taskCache = [];
  document.getElementById("task-list").textContent = "正在读取最新任务…";
  show("data-status", "正在读取最新任务…");
  ["metric-total", "metric-review", "metric-rework", "review-count"].forEach(function (id) { show(id, "—"); });
  try {
    const tasks = await api("/api/v1/delivery/views?limit=20");
    if (version !== listVersion) return;
    if (!Array.isArray(tasks.items)) throw new Error("任务列表格式不完整");
    renderTasks(tasks.items, selectedTask);
    show("data-status", "任务列表读取于 " + new Date().toLocaleTimeString() + "；可点击刷新核对变化。");
    if (selectedTask) await loadDetail(selectedTask);
    else clearEvidence("还没有选中任务，请从列表选择。");
  } catch (error) {
    if (version !== listVersion) return;
    ++detailVersion;
    document.getElementById("task-list").textContent = "任务列表不可用，请恢复服务后重试。";
    clearEvidence("无法读取最新证据，已停止显示旧结论。");
    show("data-status", "读取失败：" + String(error.message || error));
    throw error;
  }
}

async function loadDetail(taskId, polling) {
  stopProgress();
  if (selectedTask !== taskId) deliveryPanel = 'summary';
  selectedTask = taskId;
  const version = ++detailVersion;
  if (!polling) clearEvidence("正在读取 " + taskId + " 的最新证据…");
  try {
    const detail = await api("/api/v1/delivery/views/" + encodeURIComponent(taskId));
    const graph = detail.workflow_graph;
    if (version !== detailVersion) return;
    if (detail.task_id !== taskId || !detail.status || !detail.status.code) throw new Error("任务证据与请求不一致");
    renderEvidence(detail);
    if (graph) renderWorkflowGraph(graph);
    const index = taskCache.findIndex(function (item) { return item.task_id === taskId; });
    if (index >= 0) { taskCache[index] = detail; renderTasks(taskCache, taskId); }
    const pendingCodeGate = detail.status.code === 'review' && detail.policy && detail.policy.execution_mode === 'codex' &&
      !(detail.events || []).some(function(event){return event.detail === '课程红绿差分判定已完成';});
    const running = pendingCodeGate || ["queued", "spec_ready", "executing", "evaluating"].includes(detail.status.code);
    show("data-status", "任务读取于 " + new Date().toLocaleTimeString() + (running ? "；正在自动更新进度。" : "；本阶段已停止自动更新，可手动刷新。"));
    if (running) progressTimer = setTimeout(function () { loadDetail(taskId, true); }, 2000);
  } catch (error) {
    if (version !== detailVersion) return;
    clearEvidence("任务读取失败，旧结论不可用于审核：" + String(error.message || error));
  }
}

async function showCourse(lesson) {
  const version = ++courseContractReadVersion;
  if (!lesson) return;
  try {
    const course = await api("/api/course/current?lesson=" + encodeURIComponent(lesson));
    if (version === courseContractReadVersion && document.getElementById('task-lesson').value === String(lesson)) renderContract(course);
  } catch (error) {
    if (version === courseContractReadVersion && document.getElementById('task-lesson').value === String(lesson)) throw error;
  }
}

function courseVerificationReady() {
  const state = courseVerificationState;
  return !!state && state.context.ready === true && state.context.checks.length > 0 &&
    state.lesson === document.getElementById('task-lesson').value &&
    state.projectId === document.getElementById('verification-project').value;
}

function updateCourseVerificationSubmit() {
  document.getElementById('task-submit').disabled = composerMode !== 'verify' ||
    courseVerificationSubmitting || workbenchWritesFrozen() || !courseVerificationReady();
}

function courseVerificationList(id, entries) {
  const list = document.getElementById(id);
  list.innerHTML = '';
  entries.forEach(function(text) {
    const item = document.createElement('li');
    item.textContent = text;
    list.appendChild(item);
  });
}

function renderCourseVerification(context, lesson, requestedProjectId) {
  const select = document.getElementById('verification-project');
  const checksProduct = context.checks.some(function(check) { return check.target === 'erp' || check.target === 'FlowERP'; });
  select.innerHTML = '';
  const automatic = document.createElement('option');
  automatic.value = '';
  automatic.textContent = !checksProduct ? '本讲固定检查不涉及 ERP 项目' : context.projects.length
    ? '选择 ERP 项目（只有一个时自动采用）' : context.target.product_root ? '使用已配置的 FlowERP 项目' : '尚未配置 FlowERP 项目';
  select.appendChild(automatic);
  context.projects.forEach(function(project) {
    const option = document.createElement('option');
    option.value = String(project.id);
    option.textContent = project.name + ' · ' + project.root_path;
    select.appendChild(option);
  });
  const projectId = checksProduct ? String(context.target.project_id || requestedProjectId || '') : '';
  select.value = projectId;
  select.disabled = !checksProduct || context.projects.length === 0;
  courseVerificationState = {lesson: lesson, projectId: projectId, context: context};
  courseVerificationList('verification-checks', context.checks.map(function(check) {
    return (check.label || check.name) + ' · ' + (check.target === 'erp' ? 'FlowERP' : check.target === 'workbench' ? '工作台' : check.target || '课程检查');
  }));
  show('verification-target', '工作台目录：' + (context.target.workbench_root || '尚未确认') +
    '\nERP 目录：' + (checksProduct ? context.target.product_root || '尚未配置' : '本讲固定检查不涉及 ERP 源码') +
    (projectId ? '\nERP 项目：' + projectId : ''));
  courseVerificationList('verification-issues', context.issues.map(function(issue) {
    return issue.message + (issue.action ? '。处理：' + issue.action : '');
  }));
  document.getElementById('verification-configure').hidden = context.issues.length === 0;
  courseVerificationList('verification-limitations', context.limitations);
  show('verification-status', context.message || (context.ready ? '检查条件已就绪。请核对条目与目标后开始。' : '检查条件尚未就绪。请先处理上面的配置问题。'));
  show('task-submit-status', context.ready ? '只运行以上固定用例；通过后仍需具名验收。' : '尚未开始复验，也未创建失败任务。请补齐条件后重新核对。');
  updateCourseVerificationSubmit();
}

async function refreshCourseVerification() {
  const version = ++courseVerificationReadVersion;
  const lesson = document.getElementById('task-lesson').value;
  const projectId = document.getElementById('verification-project').value;
  courseVerificationState = null;
  updateCourseVerificationSubmit();
  courseVerificationList('verification-checks', []);
  courseVerificationList('verification-issues', []);
  courseVerificationList('verification-limitations', []);
  show('verification-target', '');
  document.getElementById('verification-configure').hidden = true;
  if (!lesson) {
    show('verification-status', '请先选择讲次，再核对本次检查和目标项目。');
    show('task-submit-status', '选择讲次并核对条件后，才能开始课程复验。');
    return;
  }
  show('verification-status', '正在核对本讲固定用例、目标目录与运行条件…');
  show('task-submit-status', '条件尚未读取完成，请等待核对结果。');
  try {
    const context = await api('/api/course/verification?lesson=' + encodeURIComponent(lesson) +
      (projectId ? '&project_id=' + encodeURIComponent(projectId) : ''));
    if (version !== courseVerificationReadVersion || lesson !== document.getElementById('task-lesson').value ||
        projectId !== document.getElementById('verification-project').value) return;
    if (!context || typeof context.ready !== 'boolean' || !Array.isArray(context.checks) ||
        !context.target || !Array.isArray(context.projects) || !Array.isArray(context.limitations) || !Array.isArray(context.issues)) {
      throw new Error('课程复验条件格式不完整');
    }
    renderCourseVerification(context, lesson, projectId);
  } catch (error) {
    if (version !== courseVerificationReadVersion || lesson !== document.getElementById('task-lesson').value ||
        projectId !== document.getElementById('verification-project').value) return;
    courseVerificationState = null;
    updateCourseVerificationSubmit();
    show('verification-status', '条件读取失败：' + String(error.message || error) + '。点击“重新核对条件”后再开始。');
    show('task-submit-status', '未开始复验。旧的就绪结果已失效。');
  }
}

async function submitTask(event) {
  event.preventDefault();
  const lesson = document.getElementById("task-lesson").value;
  let actor;
  try { actor = actorName(); }
  catch(error) { show('task-submit-status', error.message); return; }
  if (composerMode !== 'verify' || !courseVerificationReady()) {
    updateCourseVerificationSubmit();
    show('task-submit-status', '本讲检查与目标项目尚未核对就绪。请先处理提示，再点击“重新核对条件”。');
    return;
  }
  const note = document.getElementById("task-request").value.trim();
  if (note.length > 960) {
    show('task-submit-status', '复验备注最多 960 字，请精简后再提交。原文已保留，不会自动截断。');
    document.getElementById('task-request').focus();
    return;
  }
  const request = 'L' + String(lesson).padStart(2, '0') + ' 课程复验' + (note ? '\n复验备注：' + note : '');
  const button = document.getElementById("task-submit");
  if (button.disabled) return;
  const refs = document.getElementById('task-business-refs').value.split(/[,，\n]/).map(function(ref){return ref.trim();}).filter(Boolean);
  const payload = JSON.stringify({ lesson: Number(lesson), actor: actor, request: request, business_refs: refs,
    project_id: courseVerificationState.projectId || null,
    verification_key: courseVerificationState.context.verification_key });
  if (!pendingSubmission || pendingSubmission.payload !== payload) {
    pendingSubmission = {payload: payload, key: crypto.randomUUID()};
  }
  courseVerificationSubmitting = true;
  updateCourseVerificationSubmit();
  show("task-submit-status", "正在提交，受理后即可查看检查进度…");
  try {
    const created = await api("/api/v1/delivery/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": pendingSubmission.key },
      body: pendingSubmission.payload,
    });
    if (!created.accepted || !created.task_id) throw new Error("未收到完整的受理凭据，请重试同一需求核对。");
    pendingSubmission = null;
    document.getElementById("task-request").value = "";
    document.getElementById("task-composer").close();
    workspaceView("delivery");
    show("task-submit-status", "已受理 " + created.task_id + "，可在交付页查看进度。");
    try { await refreshTasks(created.task_id); }
    catch (error) { show("data-status", "任务 " + created.task_id + " 已受理，但进度暂不可读。请刷新核对，无需重新提交。"); }
  } catch (error) {
    if (error.code === 'course_verification_not_ready') {
      ++courseVerificationReadVersion;
      courseVerificationState = null;
      pendingSubmission = null;
      courseVerificationList('verification-checks', []);
      show('verification-target', '');
      const issues = error.verification && Array.isArray(error.verification.issues) ? error.verification.issues : [];
      courseVerificationList('verification-issues', issues.length ? issues.map(function(issue) {
        return issue.message + (issue.action ? '。处理：' + issue.action : '');
      }) : [String(error.message || error)]);
      document.getElementById('verification-configure').hidden = issues.length === 0;
      show('verification-status', '复验条件已变化：' + String(error.message || error) + '。请点击“重新核对条件”，重新确认检查对象。');
      show('task-submit-status', '尚未创建任务。请补齐或重新核对条件后再提交。');
    } else if (error.status) {
      show('task-submit-status', '服务器未接受本次提交：' + String(error.message || error) + '。请先处理提示后再提交。');
    } else {
      show("task-submit-status", "未确认受理结果：" + String(error.message || error) + "。重试同一内容会复用本次提交编号。");
    }
  } finally {
    courseVerificationSubmitting = false;
    updateCourseVerificationSubmit();
  }
}

async function runVerify(taskId) {
  const button = document.getElementById("action-verify");
  button.disabled = true;
  show("action-status", "正在复验…");
  try {
    const view = await api("/api/v1/tasks/" + taskId + "/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: actorName() }),
    });
    await refreshTasks(view.task_id);
    show("action-status", "复验完成，状态 " + ((view.status && view.status.code) || ""));
  } catch (error) {
    show("action-status", "复验失败：" + String(error.message || error));
  } finally {
    button.disabled = workbenchWritesFrozen();
  }
}

async function runReview(taskId, decision) {
  const note = document.getElementById("review-note").value.trim();
  show("action-status", "正在提交审核…");
  try {
    const view = await api("/api/v1/tasks/" + taskId + "/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer: actorName(), decision: decision, note: note }),
    });
    await refreshTasks(view.task_id);
    show("action-status", "审核结果：" + ((view.review && view.review.decision) || decision));
  } catch (error) {
    show("action-status", "审核失败：" + String(error.message || error));
  }
}

function focusIdentity() {
  const input = document.getElementById('task-actor');
  input.scrollIntoView({behavior:'smooth', block:'center'});
  input.focus({preventScroll:true});
  show('identity-status', '填写姓名或课堂昵称。它会记录在你的任务和验收决定上。');
}
function readCurrentContract() {
  const card = document.getElementById('contract-card');
  const details = card.querySelector('details');
  if (details) details.open = true;
  card.setAttribute('tabindex', '-1');
  card.scrollIntoView({behavior:'smooth', block:'center'});
  card.focus({preventScroll:true});
}
function refreshWorkbenchStartup() {
  if(workbenchServiceFrozen)return Promise.resolve(false);
  if(workbenchStartupReady)return Promise.resolve(true);
  if(workbenchStartupPending)return workbenchStartupPending;
  workbenchStartupBlocked=true;
  const pending=(async()=>{
    try {
      const health = await api("/api/health");
      if(health.surface!=="workbench")throw new Error('当前端口不是本仓库工作台，请核对服务身份与启动端口');
      if(typeof WorkbenchDrafts!=='undefined') {
        WorkbenchDrafts.init(health.runtime_instance || health.runtime);
        document.getElementById('clear-local-drafts').onclick=()=>{WorkbenchDrafts.clearAll();if(typeof WorkbenchMutationJournal!=='undefined')WorkbenchMutationJournal.clear();};
        if(typeof trackInitiativeDraft==='function')trackInitiativeDraft(currentInitiative);
      }
      if(typeof initWorkbenchBackups==='function')initWorkbenchBackups();
      const capabilities = await api('/api/v1/delivery/capabilities');
      const readiness = capabilities.code_readiness;
      webCodeAvailable = !!capabilities.web_code_execution && (!readiness || readiness.ready === true);
      document.getElementById('mode-codex').disabled = true;
      courseCodeReadinessMessage = readiness ? readiness.message : webCodeAvailable ? '执行方案经过你的确认后，才会启动 Codex。' : '当前工作台仅开放复验，代码执行入口尚未启用。';
      document.getElementById('execution-setup').hidden = webCodeAvailable;
      chooseComposerMode('verify');
      if (health.erp_url) document.getElementById("erp-link").href = health.erp_url;
      const thesis = health.thesis || {};
      show("thesis", [thesis.workbench, thesis.flowerp, thesis.codex].filter(Boolean).join(" · "));
      renderContract(await api("/api/course/current"));
      await refreshTasks();
      renderUpgrade(await api("/api/cockpit/upgrade"));
      if(workbenchServiceFrozen)return false;
      workbenchStartupReady=true;workbenchStartupBlocked=false;
      document.getElementById('mode-codex').disabled=!webCodeAvailable;
      ['save-initiative','decide-initiative'].forEach(id=>document.getElementById(id).disabled=false);
      updateCourseVerificationSubmit();
      document.getElementById('prepare-code').disabled=!webCodeAvailable;
      if(typeof projectPending!=='undefined' && typeof projectRegistrationAvailable!=='undefined')document.getElementById('project-register').disabled=projectPending || !projectRegistrationAvailable;
      const currentDetail=taskCache.find(item=>item.task_id===selectedTask);
      if(currentDetail && !document.getElementById('task-detail').hidden){renderActions(currentDetail);document.getElementById('prepare-preview').disabled=false;}
      show('data-status','服务与能力已重新核对。提交、授权和验收仍需你主动操作。');
      return true;
    }catch(error){
      workbenchStartupReady=false;
      document.getElementById('mode-codex').disabled=true;
      if(!workbenchServiceFrozen)show('data-status','初始化读取未完成，关键操作保持冻结：'+error.message+'。服务恢复后可点击刷新重新读取；不会自动提交、确认或授权。');
      show('lesson-title',String(error.message || error));
      return false;
    }
  })().finally(()=>{if(workbenchStartupPending===pending)workbenchStartupPending=null;});
  workbenchStartupPending=pending;return pending;
}
async function boot() {
  document.getElementById('back-to-tasks').onclick = function () {
    document.getElementById('delivery-task-browser').scrollIntoView({behavior:'smooth', block:'start'});
  };
  document.getElementById('focus-identity').onclick = focusIdentity;
  document.getElementById('read-current-contract').onclick = readCurrentContract;
  document.getElementById('start-guided-delivery').onclick = openComposer;
  try { document.getElementById('execution-recovery').hidden = !localStorage.getItem('workbench-pending-plan'); } catch (_) { /* Storage is optional. */ }
  document.getElementById('resume-execution').onclick = resumeExecution;
  const identity = document.getElementById('task-actor');
  identity.value = '';
  try { localStorage.removeItem('workbench-actor'); } catch (_) { /* Storage is optional. */ }
  identity.addEventListener('change', function() {
    try { localStorage.removeItem('workbench-actor'); } catch (_) { /* Storage is optional. */ }
    try { actorName(); } catch(error) { show('identity-status', error.message); }
  });
  initInitiatives();
  initProjectHome();
  document.querySelectorAll('[data-delivery-panel]').forEach(function(button) {
    button.onclick = function() { selectDeliveryPanel(button.dataset.deliveryPanel); };
  });
  document.querySelectorAll('[data-mode]').forEach(function(button) {
    button.onclick = function() { chooseComposerMode(button.dataset.mode); };
  });
  document.querySelectorAll('[data-evidence]').forEach(function(button) {
    button.onclick = function() { focusEvidence(button.dataset.evidence); };
  });
  document.getElementById('prepare-code').onclick = prepareCode;
  document.getElementById('authorize-code').onclick = authorizeCode;
  document.getElementById('edit-code').onclick = resetCodePlan;
  document.querySelectorAll("[data-view]").forEach(function (button) {
    button.onclick = function () {
      workspaceView(button.dataset.view);
      if (button.dataset.view === 'decision') refreshInitiatives();
      if (button.dataset.view === 'delivery') openDelivery();
    };
  });
  document.querySelectorAll("[data-filter]").forEach(function (button) {
    button.onclick = function () {
      taskFilter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach(function (item) { item.classList.toggle("active", item === button); });
      renderTasks(taskCache, selectedTask);
    };
  });
  ["new-task-side"].forEach(function (id) {
    document.getElementById(id).onclick = openComposer;
  });
  ["new-task", "new-task-hero"].forEach(function (id) {
    document.getElementById(id).onclick = function () {
      workspaceView('decision'); refreshInitiatives();
      if (!initiativeDirty) showInitiative(null);
    };
  });
  document.getElementById("close-composer").onclick = function () { document.getElementById("task-composer").close(); };
  document.querySelector(".brand").onclick = function (event) { event.preventDefault(); workspaceView("overview"); };
  document.getElementById("task-form").addEventListener("submit", submitTask);
  document.getElementById('verification-project').addEventListener('change', refreshCourseVerification);
  document.getElementById('verification-refresh').onclick = refreshCourseVerification;
  document.getElementById('verification-configure').onclick = function() {
    document.getElementById('task-composer').close();
    workspaceView('overview');
    document.getElementById('open-project-registration').click();
  };
  let refreshPending=null;
  document.getElementById("refresh-tasks").onclick = function () {
    if(refreshPending)return refreshPending;
    const initialized=workbenchStartupReady;
    const pending=(async()=>{
      if(!await refreshWorkbenchStartup())return;
      const reads=[];
      if(!document.getElementById("view-overview").hidden)reads.push(refreshProjectHome());
      if(!document.getElementById("view-decision").hidden)reads.push(refreshInitiatives(),refreshInitiativeWork());
      // Startup already loaded task evidence; concurrent refreshes reuse it.
      if(initialized)reads.push(refreshTasks(selectedTask).catch(function () { /* Error is already visible. */ }));
      await Promise.all(reads);
    })().finally(()=>{if(refreshPending===pending)refreshPending=null;});
    refreshPending=pending;return pending;
  };
  document.getElementById("task-lesson").addEventListener("change", function () {
    document.getElementById('code-bootstrap-field').hidden = this.value !== '4';
    refreshCourseVerification();
    showCourse(this.value).catch(function (error) {
      show("task-submit-status", "合同读取失败：" + String(error.message || error));
    });
  });
  await refreshWorkbenchStartup();
}

boot();
