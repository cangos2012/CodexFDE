/* Advanced delivery stays within the same initiative and authoritative runtime. */
let platformState={itemId:null,epoch:0,runtime:null,runtimeReadable:false,runtimePending:false,runtimeRead:0,runtimeAt:0,
  deployment:null,deployments:null,rollback:null,deploymentReadable:false,deploymentRead:0,deploymentAt:0,preview:null,subtaskDirty:false,initiativePlan:null,planAt:0,planRead:0,planError:''};
let projectPlanState={id:null,data:null,read:0,readable:false,at:0,pending:false};
let migrationState={plan:null,package:null,pending:false,intent:''};
const platformKeys=new Map();
let candidatePreviewSerial=0;
const pe=id=>document.getElementById(id);
const ptext=(tag,text)=>{const el=document.createElement(tag);el.textContent=String(text ?? '');return el;};
const plines=value=>String(value || '').split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
function platformKey(operation,fields) {
  const signature=operation+':'+JSON.stringify(fields);
  if(!platformKeys.has(signature))platformKeys.set(signature,crypto.randomUUID());
  return platformKeys.get(signature);
}
function platformBody(operation,fields,revision) {
  const actor=actorName();
  if(!actor)throw new Error('请先填写操作署名');
  return {actor,expected_revision:revision,submission_key:platformKey(operation,{actor,expected_revision:revision,...fields}),...fields};
}
async function platformPost(url,body){
  const entry=typeof WorkbenchMutationJournal==='undefined' ? null : WorkbenchMutationJournal.begin(url,body.submission_key);
  const response=await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(entry)WorkbenchMutationJournal.acknowledge(entry);
  return response;
}
function platformInput(label,value='',tag='input',field='') {
  const box=ptext('label',label),input=document.createElement(tag);input.value=value;input.dataset.field=field;
  if(tag==='textarea')input.rows=2;box.append(input);return {box,input};
}
function platformDisable(host,disabled){const frozen=typeof workbenchWritesFrozen==='function' && workbenchWritesFrozen();pe(host)?.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=disabled || frozen);}
function resetPlatformInitiative(item) {
  if(typeof WorkbenchDrafts!=='undefined')WorkbenchDrafts.detach(['runtime-subtasks','deployment']);
  platformState={itemId:item?.id || null,epoch:platformState.epoch+1,runtime:null,runtimeReadable:false,runtimePending:false,
    runtimeRead:0,runtimeAt:0,deployment:null,deployments:null,rollback:null,deploymentReadable:false,deploymentRead:0,deploymentAt:0,preview:null,subtaskDirty:false,initiativePlan:null,planAt:0,planRead:0,planError:''};
  for(const id of ['iw-runtime-approvals','iw-runtime-subtasks','iw-subtask-editor','iw-deployment-history','iw-causal-steps'])pe(id)?.replaceChildren();
  for(const id of ['iw-runtime-identity','iw-runtime-budget','iw-runtime-evidence','iw-subtask-plan','iw-deployment-plan','iw-rollback-command'])if(pe(id))pe(id).textContent='';
  for(const id of ['iw-deployment-business','iw-learning-guidance','iw-learning-generation-id','iw-learning-evidence-refs'])if(pe(id))pe(id).value='';
  if(pe('iw-subtask-workers'))pe('iw-subtask-workers').value='2';
  pe('preview-plan-dialog')?.close();
  ++candidatePreviewSerial;
  if(pe('iw-rollback-plan'))pe('iw-rollback-plan').hidden=true;
  invalidatePlatformRuntime('正在读取本事项的运行记录…');
}
function invalidatePlatformRuntime(message) {
  platformState.runtimeReadable=false;platformState.deploymentReadable=false;platformState.preview=null;platformState.deployment=null;platformState.rollback=null;
  if(pe('iw-runtime-status'))pe('iw-runtime-status').textContent='状态不可读：'+message;
  platformDisable('iw-runtime-panel',true);if(pe('iw-runtime-refresh'))pe('iw-runtime-refresh').disabled=false;
  if(pe('iw-deployment-status'))pe('iw-deployment-status').textContent='状态不可读，请重新核对后操作。';
  platformDisable('iw-deployment-panel',true);
  if(pe('preview-plan-start'))pe('preview-plan-start').disabled=true;
  if(pe('iw-deployment-start'))pe('iw-deployment-start').hidden=true;
  if(pe('iw-causal-status'))pe('iw-causal-status').textContent='当前投影未完成核对，旧证据仅供追溯。';
}
function refreshPlatformRuntime() {
  const id=platformState.itemId;if(!id)return Promise.resolve();
  const epoch=platformState.epoch;
  return shareWorkbenchRead([id,epoch,initiativeReadGeneration],'runtime',async()=>{
    const read=++platformState.runtimeRead;
    try {
      const data=await api('/api/v1/initiatives/'+encodeURIComponent(id)+'/runtime');
      if(epoch!==platformState.epoch || read!==platformState.runtimeRead)return;
      if(data.initiative_id!==id || !Number.isInteger(data.revision) || !data.state)throw new Error('运行记录与本事项不一致');
      platformState.runtime=data;platformState.runtimeReadable=true;platformState.runtimeAt=Date.now();renderPlatformRuntime(data);
    }catch(error){if(epoch===platformState.epoch && read===platformState.runtimeRead)invalidatePlatformRuntime(error.message);}
  });
}
function renderPlatformRuntime(data) {
  if(!initiativeWorkReadable){invalidatePlatformRuntime('请先重新读取并核对本事项进展。');return;}
  const busy=platformState.runtimePending,active=['running','queued','pausing','cancelling','awaiting_approval'].includes(data.state),advanced=data.advanced_enabled!==false;
  const profileEditable=advanced && !active && ['idle','clarifying','ready','rework','failed','interrupted','cancelled'].includes(initiativeWork?.stage);
  const editable=advanced && !active && initiativeWork?.stage==='confirmed';
  platformDisable('iw-runtime-panel',false);
  pe('iw-runtime-status').textContent='当前状态：'+data.state+(data.error ? ' · '+data.error : '')+(!advanced ? ' · 分工与工具授权尚未启用；请以 --enable-advanced-runtime 重启工作台。' : '');
  pe('iw-runtime-identity').textContent='事项 '+data.initiative_id+' · Run '+(data.run_id || '尚未开始')+' · 任务 '+(data.task_id || '尚未创建')+' · Session '+(data.session_id || '尚未创建');
  const select=pe('iw-runtime-profile'),previous=select.value;select.replaceChildren();
  for(const profile of data.profiles || []){const option=ptext('option',profile.name || profile.id);option.value=profile.id;select.append(option);}
  select.value=(data.profiles || []).some(p=>p.id===previous) && profileEditable ? previous : data.profile_id || '';
  select.disabled=busy || !profileEditable;pe('iw-runtime-profile-save').disabled=busy || !profileEditable || !select.value;
  const b=data.budget || {};
  pe('iw-runtime-budget').textContent='Token '+(b.tokens_used ?? 0)+' / '+(b.token_budget ?? '未设定')+' · 时间 '+Math.round(b.elapsed_seconds || 0)+' / '+(b.time_budget_seconds ?? '未设定')+' 秒 · 并行上限 '+(b.max_workers ?? '未设定');
  for(const action of ['pause','resume','cancel']){const button=pe('iw-runtime-'+action);button.hidden=!data['can_'+action];button.disabled=busy;}
  pe('iw-runtime-evidence').textContent=JSON.stringify({candidate_sha256:data.candidate_sha256,evidence:data.evidence},null,2);
  const approvals=pe('iw-runtime-approvals'),approvalSignature=JSON.stringify([data.initiative_id,data.run_id,data.approvals]);
  if(approvals.dataset.signature!==approvalSignature) {
  approvals.replaceChildren();approvals.dataset.signature=approvalSignature;
  if(!(data.approvals || []).length)approvals.append(ptext('p','当前没有工具授权请求。'));
  for(const approval of data.approvals || []) {
    const row=document.createElement('article');row.append(ptext('h4',approval.tool_id+' · '+approval.status),
      ptext('pre',JSON.stringify({id:approval.id,args:approval.args,args_sha256:approval.args_sha256,candidate_sha256:approval.candidate_sha256,actor:approval.actor,note:approval.note},null,2)));
    if(approval.status==='pending') {
      const note=platformInput('本次允许或拒绝的依据','','textarea');row.append(note.box);
      for(const [decision,label] of [['allow','核对以上动作，允许一次'],['deny','拒绝本次动作']]) {
        const button=ptext('button',label);button.type='button';button.disabled=busy;
        button.onclick=()=>runtimeAction('approvals/'+encodeURIComponent(approval.id),{decision,note:note.input.value.trim()});row.append(button);
      }
    }
    approvals.append(row);
  }
  }
  approvals.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=busy || !advanced);
  const tasks=pe('iw-runtime-subtasks');tasks.replaceChildren();
  if(!(data.subtasks || []).length)tasks.append(ptext('p','尚未启动子任务。先说明职责与文件范围，再核对并授权。'));
  for(const task of data.subtasks || []) {
    const row=document.createElement('article');row.append(ptext('h4',(task.name || task.id)+' · '+task.status),
      ptext('p',task.prompt || ''),
      ptext('p','读取：'+(task.read_set || []).join('、')+'；修改：'+((task.write_set || []).join('、') || '只读')),
      ptext('p',task.error || ''),ptext('pre',JSON.stringify({id:task.id,task_id:task.task_id,workspace:task.workspace,evidence:task.evidence},null,2)));tasks.append(row);
  }
  for(const id of ['iw-subtask-add','iw-subtask-prepare','iw-subtask-workers'])pe(id).disabled=busy || !editable;
  if(data.subtask_plan_id && !platformState.subtaskDirty && [2,3,4].includes(b.max_workers))pe('iw-subtask-workers').value=String(b.max_workers);
  pe('iw-subtask-editor').querySelectorAll('input,textarea,button').forEach(el=>el.disabled=busy || !editable);
  pe('iw-subtask-start').hidden=!data.subtask_plan_id || platformState.subtaskDirty;pe('iw-subtask-start').disabled=busy || !editable || data.state!=='prepared';
  if(data.subtask_plan_id)pe('iw-subtask-plan').textContent=(platformState.subtaskDirty ? '分工草稿已变化，请重新核对后授权。旧准备记录：\n' : '本次待授权分工：\n')+JSON.stringify({plan_id:data.subtask_plan_id,profile_id:data.profile_id,max_workers:b.max_workers,candidate_sha256:data.candidate_sha256,subtasks:data.subtasks},null,2);
  trackRuntimeDraft(data);
  if(initiativeWork)renderCausalChain(initiativeWork);
}
async function runtimeAction(action,fields={}) {
  if(!platformState.runtimeReadable || platformState.runtimePending || !initiativeWorkReadable)return;
  const epoch=platformState.epoch,id=platformState.itemId,data=platformState.runtime;
  invalidateInitiativeReads();platformState.runtimePending=true;renderPlatformRuntime(data);
  try {
    const response=await platformPost('/api/v1/initiatives/'+encodeURIComponent(id)+'/runtime/'+action,
      platformBody(id+'/runtime/'+action,fields,data.revision));
    if(epoch!==platformState.epoch)return;
    if(response.initiative_id && response.initiative_id!==id)throw new Error('返回的运行记录不属于本事项');
    if(action==='subtasks/prepare'){platformState.subtaskDirty=false;pe('iw-subtask-plan').textContent=JSON.stringify(response,null,2);}
    await refreshInitiativeWork({force:true,afterMutation:true});
  }catch(error){if(epoch===platformState.epoch)invalidatePlatformRuntime('操作结果待核对：'+error.message);}
  finally{if(epoch===platformState.epoch){platformState.runtimePending=false;if(platformState.runtimeReadable)renderPlatformRuntime(platformState.runtime);}}
}
function subtaskDraftRows() {
  return [...pe('iw-subtask-editor').children].map(row=>Object.fromEntries([...row.querySelectorAll('[data-field]')].map(input=>[input.dataset.field,input.value])));
}
function subtaskPayload() {
  return subtaskDraftRows().map(row=>({name:row.name.trim(),prompt:row.prompt.trim(),read_set:plines(row.read_set),write_set:plines(row.write_set),resource_set:plines(row.resource_set)}));
}
function addSubtaskRow(values={}) {
  const row=document.createElement('article');
  for(const [field,label,tag] of [['name','子任务名称','input'],['prompt','职责、预期成果与交接','textarea'],['read_set','允许读取的文件（每行一个）','textarea'],['write_set','允许修改的文件（每行一个；留空为只读）','textarea'],['resource_set','共享资源（每行一个）','textarea']]) {
    const value=Array.isArray(values[field]) ? values[field].join('\n') : values[field] || '';
    row.append(platformInput(label,value,tag,field).box);
  }
  const remove=ptext('button','移除此条草稿');remove.type='button';remove.onclick=()=>{row.remove();platformState.subtaskDirty=true;pe('iw-subtask-start').hidden=true;pe('iw-subtask-editor').dispatchEvent(new Event('input',{bubbles:true}));};row.append(remove);pe('iw-subtask-editor').append(row);
}
function trackRuntimeDraft(data) {
  if(typeof WorkbenchDrafts==='undefined')return;
  WorkbenchDrafts.track('runtime-subtasks',{project:initiativeWork?.project?.id || '',item:data.initiative_id,base:data.run_id || 'new'},
    ()=>({rows:subtaskDraftRows(),max_workers:Number(pe('iw-subtask-workers').value)}),fields=>{pe('iw-subtask-editor').replaceChildren();for(const row of fields.rows || [])addSubtaskRow(row);pe('iw-subtask-workers').value=String([2,3,4].includes(fields.max_workers)?fields.max_workers:2);platformState.subtaskDirty=true;pe('iw-subtask-start').hidden=true;},pe('iw-subtask-editor'));
}
async function refreshPlatformProjectPlan(force=false) {
  const id=pe('home-project').value;pe('project-plan-panel').hidden=!id || id==='all';
  if(!id || id==='all'){++projectPlanState.read;projectPlanState.id=null;return;}
  if(!force && projectPlanState.id===id && Date.now()-projectPlanState.at<15000)return;
  projectPlanState.id=id;projectPlanState.readable=false;pe('project-plan-edit').disabled=true;
  pe('project-plan-architecture').textContent='';
  pe('project-plan-status').textContent='正在读取项目计划…';const read=++projectPlanState.read;
  try {
    const data=await api('/api/v1/projects/'+encodeURIComponent(id)+'/plan');
    if(read!==projectPlanState.read || id!==pe('home-project').value)return;
    if(data.project_id!==id || !Number.isInteger(data.revision) || !Array.isArray(data.milestones))throw new Error('项目计划身份无法核对');
    projectPlanState.data=data;projectPlanState.readable=true;projectPlanState.at=Date.now();renderProjectPlan(data);
  }catch(error){if(read===projectPlanState.read){projectPlanState.data=null;pe('project-plan-status').textContent='计划不可读：'+error.message;pe('project-plan-objective').textContent='';pe('project-plan-milestones').replaceChildren();}}
}
function renderProjectPlan(data) {
  pe('project-plan-edit').disabled=projectPlanState.pending;
  pe('project-plan-status').textContent='计划版本 '+data.revision+(data.blocked ? ' · 有依赖待解决' : '');
  pe('project-plan-objective').textContent=data.objective || '尚未登记项目目标；现有事项可以继续。';
  pe('project-plan-architecture').textContent=(data.architecture_refs || []).map(ref=>typeof ref==='string'?ref:ref.path+' · '+ref.sha256).join('\n');
  const list=pe('project-plan-milestones');list.replaceChildren();
  for(const m of data.milestones || []) {
    const row=document.createElement('article');row.append(ptext('h3',m.id+' · '+m.title+' · '+m.status),ptext('p','通过标准：'+(Array.isArray(m.acceptance) ? m.acceptance.join('；') : m.acceptance || '')),
      ptext('p','依赖：'+((m.depends_on || []).join('、') || '无')+((m.blocked_by || []).length ? ' · 尚待 '+m.blocked_by.join('、') : '')));
    for(const id of m.initiative_ids || []){const button=ptext('button','打开事项 '+id);button.type='button';button.onclick=()=>openProjectInitiative(id);row.append(button);}
    const create=ptext('button','为此里程碑记录事项');create.type='button';create.onclick=()=>{workspaceView('decision');showInitiative(null);initiativeInput('project').value=data.project_id;initiativeInput('title').value=m.title;initiativeInput('raw').value='对应里程碑 '+m.id+'：'+m.title;initiativeInput('acceptance').value=Array.isArray(m.acceptance)?m.acceptance.join('\n'):m.acceptance || '';initiativeDirty=true;pe('initiative-status').textContent='保存新事项后，请在项目计划中关联该事项编号。';};row.append(create);list.append(row);
  }
}
function planDraft() {
  return {objective:pe('plan-objective').value,architecture_refs:plines(pe('plan-architecture').value),milestones:[...pe('plan-rows').children].map(row=>Object.fromEntries([...row.querySelectorAll('[data-field]')].map(el=>[el.dataset.field,el.value])))};
}
function addMilestoneRow(values={}) {
  const row=document.createElement('article');
  for(const [field,label,tag] of [['id','里程碑编号','input'],['title','里程碑标题','input'],['acceptance','通过标准','textarea'],['depends_on','依赖的里程碑编号（每行一个）','textarea'],['initiative_ids','关联的事项编号（每行一个）','textarea'],['evidence','判断与验收证据（确认完成时必填）','textarea']]) {
    row.append(platformInput(label,Array.isArray(values[field])?values[field].join('\n'):values[field] || '',tag,field).box);
  }
  const status=platformInput('里程碑判断',values.status || 'planned','select','status');
  for(const [value,label] of [['planned','已计划'],['active','正在推进'],['completed','依据已接受事项确认完成'],['needs_revalidation','需要重新核验']]){const option=ptext('option',label);option.value=value;status.input.append(option);}status.input.value=values.status || 'planned';row.append(status.box);
  const remove=ptext('button','移除此里程碑');remove.type='button';remove.onclick=()=>{row.remove();pe('plan-rows').dispatchEvent(new Event('input',{bubbles:true}));};row.append(remove);pe('plan-rows').append(row);
}
function openProjectPlan() {
  if(!projectPlanState.readable)return;const data=projectPlanState.data;
  pe('plan-error').textContent='';pe('plan-objective').value=data.objective || '';pe('plan-architecture').value=(data.architecture_refs || []).map(ref=>typeof ref==='string'?ref:ref.path).join('\n');pe('plan-rows').replaceChildren();
  for(const m of data.milestones || [])addMilestoneRow(m);
  pe('project-plan-dialog').showModal();
  if(typeof WorkbenchDrafts!=='undefined')WorkbenchDrafts.track('project-plan',{project:data.project_id,item:'plan',base:data.revision},planDraft,
    fields=>{pe('plan-objective').value=fields.objective || '';pe('plan-architecture').value=(fields.architecture_refs || []).join('\n');pe('plan-rows').replaceChildren();for(const m of fields.milestones || [])addMilestoneRow(m);},pe('project-plan-dialog'));
}
async function saveProjectPlan() {
  if(!projectPlanState.readable || projectPlanState.pending)return;const data=projectPlanState.data,fields=planDraft();
  fields.milestones=fields.milestones.map(m=>({...m,acceptance:m.acceptance.trim(),depends_on:plines(m.depends_on),initiative_ids:plines(m.initiative_ids)}));
  const snapshot=typeof WorkbenchDrafts!=='undefined' ? WorkbenchDrafts.capture('project-plan') : null;
  projectPlanState.pending=true;platformDisable('project-plan-dialog',true);
  try{await platformPost('/api/v1/projects/'+encodeURIComponent(data.project_id)+'/plan',platformBody('plan/'+data.project_id,fields,data.revision));
    if(snapshot)WorkbenchDrafts.clearSubmitted(snapshot);pe('project-plan-dialog').close();await refreshPlatformProjectPlan(true);await refreshProjectHome();
  }catch(error){pe('plan-error').textContent='保存结果待核对：'+error.message;projectPlanState.readable=false;await refreshPlatformProjectPlan(true);}
  finally{projectPlanState.pending=false;platformDisable('project-plan-dialog',false);}
}
function renderPlatformWorkflow(data) {
  if(platformState.itemId!==data.id)return;
  renderCausalChain(data);
  if(platformState.runtimeReadable)renderPlatformRuntime(platformState.runtime);
  else {platformDisable('iw-runtime-panel',true);pe('iw-runtime-refresh').disabled=false;}
  if(platformState.deploymentReadable && platformState.deployments)renderDeployments(platformState.deployments);
  else platformDisable('iw-deployment-panel',true);
  const profiles=data.project?.deployment_profiles || [],select=pe('iw-deployment-profile'),previous=select.value;select.replaceChildren();
  for(const profile of profiles){const option=ptext('option',profile.name || profile.id);option.value=profile.id;select.append(option);}
  if(profiles.some(p=>p.id===previous))select.value=previous;
  pe('iw-deployment-prepare').disabled=!profiles.length || !['integrated','released','observed'].includes(data.stage) || !initiativeWorkReadable || !platformState.deploymentReadable || platformState.runtimePending;
  if(!profiles.length)pe('iw-deployment-status').textContent='本项目未配置受控发布。可在管理项目中登记，或在下方登记已完成的人工发布。';
}
function refreshPlatformViews({force=false}={}) {
  const data=initiativeWork;if(!initiativeWorkReadable || !data || platformState.itemId!==data.id)return Promise.resolve();
  const reads=[];
  if(force || Date.now()-platformState.runtimeAt>5000)reads.push(refreshPlatformRuntime());
  if(data.project?.id && (force || Date.now()-platformState.planAt>15000))reads.push(refreshInitiativeProjectPlan(data.project.id));
  if((force || ['integrated','released','observed'].includes(data.stage)) && (force || Date.now()-platformState.deploymentAt>5000))reads.push(refreshDeployments());
  return Promise.all(reads);
}
function refreshInitiativeProjectPlan(projectId) {
  const epoch=platformState.epoch;
  return shareWorkbenchRead([platformState.itemId,epoch,initiativeReadGeneration],'project-plan/'+projectId,async()=>{
    const read=++platformState.planRead;platformState.planAt=Date.now();
    try{const data=await api('/api/v1/projects/'+encodeURIComponent(projectId)+'/plan');
      if(epoch!==platformState.epoch || read!==platformState.planRead)return;
      if(data.project_id!==projectId || !Number.isInteger(data.revision) || !Array.isArray(data.milestones))throw new Error('项目计划与事项所属项目不一致');
      platformState.initiativePlan=data;platformState.planError='';if(initiativeWork)renderCausalChain(initiativeWork);
    }catch(error){if(epoch===platformState.epoch && read===platformState.planRead){platformState.initiativePlan=null;platformState.planError=error.message;if(initiativeWork)renderCausalChain(initiativeWork);}}
  });
}
function renderCausalChain(data) {
  const list=pe('iw-causal-steps');if(!list)return;list.replaceChildren();
  pe('iw-causal-status').textContent='各阶段分别保留结果；自动检查通过后仍需人审，集成后仍需发布与效果验证。';
  const plan=platformState.initiativePlan || (!platformState.planError && projectPlanState.readable && projectPlanState.data?.project_id===data.project?.id ? projectPlanState.data : null);
  const milestone=plan?.milestones.find(m=>(m.initiative_ids || []).includes(data.id));
  const stages=[['项目目标与里程碑',plan ? {objective:plan.objective,revision:plan.revision,milestone} : {status:platformState.planError ? '项目计划不可读：'+platformState.planError : '尚无已读取的项目计划',project_id:data.project?.id}],
    ['事项与冻结合同',{initiative_id:data.id,initiative_version:data.initiative_version,documents:data.documents,confirmations:data.document_confirmations}],
    ['计划、分工与授权',platformState.runtimeReadable ? platformState.runtime : {status:'运行记录尚未核对'}],
    ['实际改动与自动检查',{task_id:data.active_task_id,diff:data.task?.diff,eval:data.eval_harness,iterations:data.iterations}],
    ['具名验收与源码集成',{stage:data.stage,integration:data.integration,review:(data.task?.events || []).filter(e=>/审核|验收|接受/.test(e.detail || ''))}],
    ['实际发布与业务效果',{deployments:platformState.deploymentReadable ? platformState.deployments?.items : '发布记录尚未核对',records:data.delivery_records,completed_cycles:data.completed_cycles}],
    ['经验提炼与后续采用',{generations:data.learning?.generations,bindings:data.learning?.bindings,metrics:data.learning?.metrics}]];
  for(const [title,evidence] of stages){const li=document.createElement('li'),details=document.createElement('details');details.append(ptext('summary',title),ptext('pre',JSON.stringify(evidence,null,2)));li.append(details);list.append(li);}
}
function refreshDeployments() {
  const id=platformState.itemId,epoch=platformState.epoch;if(!id)return Promise.resolve();
  return shareWorkbenchRead([id,epoch,initiativeReadGeneration],'deployments',async()=>{
    const read=++platformState.deploymentRead;
    try{const data=await api('/api/v1/initiatives/'+encodeURIComponent(id)+'/deployments');
      if(epoch!==platformState.epoch || read!==platformState.deploymentRead)return;
      if(!Array.isArray(data.items) || data.items.some(item=>item.initiative_id && item.initiative_id!==id))throw new Error('发布记录无法核对');
      platformState.deployments=data;platformState.deploymentReadable=true;platformState.deploymentAt=Date.now();renderDeployments(data);
    }catch(error){if(epoch===platformState.epoch && read===platformState.deploymentRead){platformState.deploymentReadable=false;pe('iw-deployment-status').textContent='发布状态不可读：'+error.message;platformDisable('iw-deployment-panel',true);}}
  });
}
function deploymentItems(){return (platformState.deployments?.items || []).slice().sort((a,b)=>(a.started_at || a.prepared_at || 0)-(b.started_at || b.prepared_at || 0));}
function latestDeployment(){const items=deploymentItems(),selected=pe('iw-deployment-select').value;return items.find(d=>(d.deployment_id || d.id)===selected) || items.slice(-1)[0] || null;}
function renderDeployments(data) {
  if(!initiativeWorkReadable){platformDisable('iw-deployment-panel',true);return;}
  platformDisable('iw-deployment-panel',false);
  const list=pe('iw-deployment-history');list.replaceChildren();
  for(const item of data.items){const details=document.createElement('details');details.append(ptext('summary',(item.deployment_id || item.id)+' · '+item.status),ptext('pre',JSON.stringify(item,null,2)));list.append(details);}
  const select=pe('iw-deployment-select'),previous=select.value;select.replaceChildren();
  for(const item of deploymentItems()){const option=ptext('option',(item.deployment_id || item.id)+' · '+item.status);option.value=item.deployment_id || item.id;select.append(option);}
  select.value=data.items.some(item=>(item.deployment_id || item.id)===previous) ? previous : deploymentItems().slice(-1)[0]?.deployment_id || deploymentItems().slice(-1)[0]?.id || '';select.disabled=!data.items.length;
  const latest=latestDeployment();
  const canVerify=latest?.status==='awaiting_business_review',canRollback=latest && !['running','rolling_back','rolled_back'].includes(latest.status) && (latest.rollback_command || []).length>0;
  if(platformState.rollback && (!canRollback || platformState.rollback.deployment_id!==(latest?.deployment_id || latest?.id))){platformState.rollback=null;pe('iw-rollback-plan').hidden=true;}
  pe('iw-deployment-verify').hidden=!canVerify;pe('iw-deployment-rollback').hidden=!canRollback;
  ['iw-deployment-business','iw-deployment-conclusion','iw-deployment-verify'].forEach(id=>pe(id).disabled=!initiativeWorkReadable || !canVerify);
  pe('iw-deployment-rollback').disabled=!initiativeWorkReadable || !canRollback;
  if(latest)pe('iw-deployment-status').textContent=latest.status==='awaiting_business_review' ? '健康检查通过，仍待指定验收人 '+(initiativeWork?.reviewer || '')+' 核对真实业务结果。' : '当前发布状态：'+latest.status+(latest.error ? ' · '+latest.error : '');
  if(initiativeWork)renderCausalChain(initiativeWork);
  if(initiativeWork)pe('iw-deployment-prepare').disabled=!(initiativeWork.project?.deployment_profiles || []).length || !['integrated','released','observed'].includes(initiativeWork.stage) || !initiativeWorkReadable;
  if(typeof WorkbenchDrafts!=='undefined')WorkbenchDrafts.track('deployment',{project:initiativeWork?.project?.id || '',item:platformState.itemId,base:latest?.deployment_id || latest?.id || 'new'},
    ()=>({business_evidence:pe('iw-deployment-business').value}),fields=>{pe('iw-deployment-business').value=fields.business_evidence || '';},pe('iw-deployment-panel'));
  if(platformState.runtimePending)platformDisable('iw-deployment-panel',true);
}
async function deploymentAction(action,fields) {
  if(!initiativeWorkReadable || !initiativeWork || !platformState.deploymentReadable || platformState.runtimePending)return;
  const id=platformState.itemId,epoch=platformState.epoch;
  invalidateInitiativeReads();platformState.runtimePending=true;platformDisable('iw-deployment-panel',true);
  try {
    const data=await platformPost('/api/v1/initiatives/'+encodeURIComponent(id)+'/deployments/'+action,platformBody(id+'/deployments/'+action,fields,initiativeWork.revision));
    if(epoch!==platformState.epoch)return;
    pe('iw-deployment-status').textContent='当前发布状态：'+(data.status || '已记录')+'。请核对健康检查与业务验证证据。';
    if(action==='prepare'){platformState.deployment=data;pe('iw-deployment-plan').textContent=JSON.stringify(data,null,2);pe('iw-deployment-start').hidden=false;}
    else{platformState.deployment=null;platformState.rollback=null;pe('iw-deployment-start').hidden=true;pe('iw-rollback-plan').hidden=true;}
    await refreshInitiativeWork({force:true,afterMutation:true});return data;
  }catch(error){if(epoch===platformState.epoch){platformState.deployment=null;pe('iw-deployment-start').hidden=true;platformState.deploymentReadable=false;pe('iw-deployment-status').textContent='操作结果待核对，不能重复授权：'+error.message;}}
  finally{if(epoch===platformState.epoch){platformState.runtimePending=false;if(platformState.deploymentReadable){platformDisable('iw-deployment-panel',false);if(initiativeWork)renderPlatformWorkflow(initiativeWork);}}}
}
function previewIsCurrent(plan) {
  if(!plan || plan.serial!==candidatePreviewSerial || typeof workbenchWritesFrozen==='function' && workbenchWritesFrozen())return false;
  if(plan.source==='task')return typeof selectedTask!=='undefined' && selectedTask===plan.task_id && detailVersion===plan.view_version;
  return initiativeWorkReadable && platformState.epoch===plan.view_version && initiativeWork?.task?.id===plan.task_id;
}
async function openPlatformPreview(taskId=initiativeWork?.task?.id,source='initiative') {
  if(source==='initiative' && (!initiativeWorkReadable || !initiativeWork?.task) || source==='task' && (typeof selectedTask==='undefined' || selectedTask!==taskId))return;
  const task=taskId,context={task_id:task,source,view_version:source==='task'?detailVersion:platformState.epoch,serial:++candidatePreviewSerial};platformState.preview=null;
  if(source==='initiative'){iw('preview-frame').hidden=true;iw('preview-frame').removeAttribute('src');}
  const status=pe(source==='task'?'preview-status':'iw-preview-status'),link=pe(source==='task'?'preview-link':'iw-preview-link');link.hidden=true;status.textContent='正在核对候选与预览配置…';
  pe('preview-plan-dialog').showModal();pe('preview-plan-start').disabled=true;pe('preview-plan-evidence').textContent='';pe('preview-plan-status').textContent='正在核对候选与预览配置…';
  try{const data=await api('/api/v1/tasks/'+encodeURIComponent(task)+'/preview-plan');
    if(!previewIsCurrent(context)){if(context.serial===candidatePreviewSerial)pe('preview-plan-status').textContent='当前任务视图已变化，请关闭后重新读取预览方案。';return;}
    if(data.task_id!==task)throw new Error('预览方案不属于本任务');
    if(data.available===false)throw new Error(data.notice || '本项目候选暂不可预览，请先登记预览配置');
    if(!data.legacy && (!data.plan_id || !Number.isInteger(data.configuration_revision) || !data.expected_candidate_sha256))throw new Error('预览方案缺少候选与配置绑定');
    platformState.preview={...data,...context};pe('preview-plan-evidence').textContent=JSON.stringify(data,null,2);pe('preview-plan-status').textContent='请核对启动命令、候选来源与独立数据目录；本次预览不代表发布。';status.textContent='方案已读取；请在对话框核对并明确确认启动。';pe('preview-plan-start').disabled=false;
  }catch(error){if(previewIsCurrent(context)){pe('preview-plan-status').textContent='预览方案不可用：'+error.message;status.textContent='预览方案不可用：'+error.message;}}
}
async function startPlatformPreview() {
  const plan=platformState.preview;if(!previewIsCurrent(plan)){pe('preview-plan-start').disabled=true;pe('preview-plan-status').textContent='当前任务视图已变化，请关闭后重新读取预览方案。';return;}
  const status=pe(plan.source==='task'?'preview-status':'iw-preview-status'),link=pe(plan.source==='task'?'preview-link':'iw-preview-link');pe('preview-plan-start').disabled=true;
  try{const result=await platformPost('/api/v1/tasks/'+encodeURIComponent(plan.task_id)+'/preview',platformBody('preview/'+plan.task_id,
    {plan_id:plan.plan_id,configuration_revision:plan.configuration_revision,expected_candidate_sha256:plan.expected_candidate_sha256 || plan.candidate_sha256,confirmed:true},initiativeWork?.task?.id===plan.task_id?initiativeWork.revision:undefined));
    if(!previewIsCurrent(plan))return;
    if(result.task_id!==plan.task_id || !/^http:\/\/(127\.0\.0\.1|localhost):\d+(?:\/|$)/.test(result.url || ''))throw new Error('预览链接身份无法核对');
    if(!plan.legacy && (result.plan_id!==plan.plan_id || result.configuration_revision!==plan.configuration_revision || result.expected_candidate_sha256!==plan.expected_candidate_sha256))throw new Error('预览进程与已核对方案的候选或配置不一致');
    link.href=result.url;link.hidden=false;status.textContent='隔离预览已就绪，请从链接在独立窗口核对。'+(result.notice || '');pe('preview-plan-dialog').close();platformState.preview=null;
  }catch(error){if(previewIsCurrent(plan)){platformState.preview=null;pe('preview-plan-status').textContent='启动结果待核对：'+error.message+'。请重新读取方案。';status.textContent='启动结果待核对：'+error.message;}}
}
async function openMigration() {
  pe('migration-dialog').showModal();pe('migration-prepare').disabled=true;pe('migration-download').hidden=true;migrationState.plan=null;migrationState.package=null;migrationState.intent=crypto.randomUUID();
  pe('migration-status').textContent='正在读取当前依赖与迁移边界…';pe('migration-plan').textContent='';
  try{const data=await api('/api/v1/migration/plan');migrationState.plan=data;pe('migration-plan').textContent=JSON.stringify({runtime_root:data.runtime_root,projects:(data.projects || []).map(({source_manifest,...project})=>project),dependencies:data.dependencies,missing_external_dependencies:data.missing_external_dependencies},null,2);pe('migration-boundary').textContent=data.boundary || '';pe('migration-mapping').value=JSON.stringify(Object.fromEntries([...new Set([...(data.projects || []).map(p=>p.root_path),...(data.dependencies || []).filter(d=>d.path && !d.inside_runtime).map(d=>d.path)])].map(path=>[path,'填写新机器真实对应路径'])),null,2);pe('migration-prepare').disabled=false;pe('migration-status').textContent='核对实际项目与运行依赖后再准备包。';renderMigrationCommand();}
  catch(error){pe('migration-status').textContent='迁移依据不可读：'+error.message;}
}
function renderMigrationCommand() {
  const archive=migrationState.package?.archive_path || '<迁移包绝对路径>',target=pe('migration-target').value.trim() || '<新运行目录绝对路径>';
  const quote=value=>"'"+String(value).replace(/'/g,"''")+"'";
  pe('migration-command').textContent='python -X utf8 -m workbench.cli restore-workbench-migration '+quote(archive)+' --runtime-dir '+quote(target)+' --mapping-file '+quote('mapping.json');
}
async function prepareMigration() {
  if(!migrationState.plan || migrationState.pending)return;migrationState.pending=true;pe('migration-prepare').disabled=true;
    try{const data=await platformPost('/api/v1/migration/prepare',platformBody('migration/'+migrationState.intent,{confirmed:true},undefined));migrationState.package=data;
    pe('migration-status').textContent='迁移包已准备：'+data.archive_path+'\nSHA256：'+data.sha256;
    if(data.download_url){pe('migration-download').href=data.download_url;pe('migration-download').hidden=false;}renderMigrationCommand();
  }catch(error){pe('migration-status').textContent='准备结果待核对：'+error.message;}
  finally{migrationState.pending=false;pe('migration-prepare').disabled=!!migrationState.package || typeof workbenchWritesFrozen==='function' && workbenchWritesFrozen();}
}
async function openLearningMetrics() {
  pe('learning-metrics-dialog').showModal();pe('learning-metrics-status').textContent='正在读取真实复用记录…';pe('learning-metrics-values').replaceChildren();
  try{const data=await api('/api/v1/learning/metrics'),labels={eligible_initiatives:'可作为来源的事项',assets:'版本化经验与流程',adoptions:'跨事项采用',successes:'复用成功',failures:'复用失败',rework_seconds:'返工耗时（秒）',repeated_failure_reduction:'重复失败减少情况',sample_count:'观察样本'};
    for(const [key,label] of Object.entries(labels)){const row=document.createElement('div');row.append(ptext('dt',label),ptext('dd',data[key] ?? '待测'));pe('learning-metrics-values').append(row);}pe('learning-metrics-status').textContent='基于已留存证据的统计；没有证据的指标显示待测。';
  }catch(error){pe('learning-metrics-status').textContent='指标不可读：'+error.message;}
}
function initPlatform() {
  if(!pe('iw-runtime-panel'))return;
  if(!['2','3','4'].includes(pe('iw-subtask-workers').value))pe('iw-subtask-workers').value='2';
  pe('iw-runtime-refresh').onclick=()=>refreshInitiativeWork({force:true});
  pe('iw-runtime-profile-save').onclick=()=>runtimeAction('profile',{profile_id:pe('iw-runtime-profile').value});
  for(const action of ['pause','resume','cancel'])pe('iw-runtime-'+action).onclick=()=>runtimeAction('control',{action,candidate_sha256:platformState.runtime?.candidate_sha256});
  pe('iw-subtask-add').onclick=()=>{addSubtaskRow();platformState.subtaskDirty=true;pe('iw-subtask-start').hidden=true;pe('iw-subtask-editor').dispatchEvent(new Event('input',{bubbles:true}));};
  pe('iw-subtask-editor').addEventListener('input',()=>{platformState.subtaskDirty=true;pe('iw-subtask-start').hidden=true;});
  pe('iw-subtask-workers').onchange=()=>{platformState.subtaskDirty=true;pe('iw-subtask-start').hidden=true;pe('iw-subtask-editor').dispatchEvent(new Event('input',{bubbles:true}));};
  pe('iw-subtask-prepare').onclick=()=>{const max_workers=Number(pe('iw-subtask-workers').value);if(![2,3,4].includes(max_workers)){pe('iw-runtime-status').textContent='请选择 2、3 或 4 个并行 worker。';return;}return runtimeAction('subtasks/prepare',{subtasks:subtaskPayload(),max_workers});};
  pe('iw-subtask-start').onclick=()=>{if(!platformState.subtaskDirty)runtimeAction('subtasks/start',{plan_id:platformState.runtime?.subtask_plan_id});};
  pe('project-plan-edit').onclick=openProjectPlan;pe('project-plan-close').onclick=()=>pe('project-plan-dialog').close();pe('plan-add').onclick=()=>{addMilestoneRow();pe('plan-rows').dispatchEvent(new Event('input',{bubbles:true}));};pe('plan-save').onclick=saveProjectPlan;
  pe('preview-plan-close').onclick=()=>{++candidatePreviewSerial;platformState.preview=null;pe('preview-plan-dialog').close();};pe('preview-plan-start').onclick=startPlatformPreview;
  pe('iw-deployment-prepare').onclick=()=>deploymentAction('prepare',{profile_id:pe('iw-deployment-profile').value});
  pe('iw-deployment-profile').onchange=()=>{platformState.deployment=null;pe('iw-deployment-start').hidden=true;};
  pe('iw-deployment-select').onchange=()=>{if(typeof WorkbenchDrafts!=='undefined')WorkbenchDrafts.flush();platformState.rollback=null;pe('iw-rollback-plan').hidden=true;pe('iw-deployment-business').value='';if(platformState.deploymentReadable)renderDeployments(platformState.deployments);};
  pe('iw-deployment-start').onclick=()=>{if(platformState.deployment)deploymentAction('start',{plan_id:platformState.deployment.plan_id,confirmed:true});};
  pe('iw-deployment-verify').onclick=()=>{const d=latestDeployment();if(d)deploymentAction('verify',{deployment_id:d.deployment_id || d.id,business_evidence:pe('iw-deployment-business').value.trim(),conclusion:pe('iw-deployment-conclusion').value});};
  pe('iw-deployment-rollback').onclick=()=>{const d=latestDeployment();if(!d || !platformState.deploymentReadable)return;platformState.rollback={deployment_id:d.deployment_id || d.id,rollback_command:d.rollback_command || d.plan?.rollback_command,environment:d.environment,workspace:d.workspace};pe('iw-rollback-plan').hidden=false;pe('iw-rollback-command').textContent=JSON.stringify(platformState.rollback,null,2);};
  pe('iw-rollback-confirm').onclick=()=>{if(platformState.rollback)deploymentAction('rollback',{deployment_id:platformState.rollback.deployment_id,confirmed:true});};
  pe('open-migration').onclick=openMigration;pe('migration-close').onclick=()=>pe('migration-dialog').close();pe('migration-prepare').onclick=prepareMigration;pe('migration-target').oninput=renderMigrationCommand;
  pe('open-learning-metrics').onclick=openLearningMetrics;pe('learning-metrics-close').onclick=()=>pe('learning-metrics-dialog').close();
}
