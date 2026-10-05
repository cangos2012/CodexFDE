const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {dom,storage}=require('./web_dom.cjs');
function setup() {
  const ui=dom(),store=storage(),calls=[];
  const create=ui.document.createElement;
  ui.document.createElement=tag=>{const el=create(tag);el.addEventListener=(event,fn)=>el['on'+event]=fn;el.remove=()=>{if(el.parent)el.parent.children=el.parent.children.filter(c=>c!==el);};
    el.insertBefore=(child,before)=>{child.remove?.();const index=el.children.indexOf(before);if(index<0)el.children.push(child);else el.children.splice(index,0,child);child.parent=el;return child;};
    const query=el.querySelector;el.querySelector=selector=>selector==='h4' ? el.children.find(child=>child.tag==='h4') || null : query.call(el,selector);
    const append=el.append;el.append=(...children)=>{children.forEach(c=>c.parent=el);append.call(el,...children);};return el;};
  const get=ui.document.getElementById;
  ui.document.getElementById=id=>{const el=get(id);el.addEventListener=(event,fn)=>el['on'+event]=fn;return el;};
  for(const match of fs.readFileSync('workbench_web/index.html','utf8').matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const el=ui.document.createElement(match[1]);el.hidden=/\bhidden\b/.test(match[2]);ui.nodes.set(match[3],el);
  }
  ui.document.querySelector=selector=>ui.node(selector);
  const context=vm.createContext({document:ui.document,localStorage:store,Date,URLSearchParams,Event:class{},
    crypto:require('node:crypto').webcrypto,AbortController,Headers,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},
    actorName:()=> 'operator',show:(id,value)=>ui.node(id).textContent=value,workspaceView(){},openProjectInitiative(){},refreshProjectHome:async()=>{},
    api:async(url,options)=>{calls.push({url,body:options?.body?JSON.parse(options.body):null});throw Error('offline');}});
  for(const filename of ['mutation-journal.js','workspace-dashboard.js','initiative_workflow.js','learning.js','platform.js'])vm.runInContext(fs.readFileSync('workbench_web/'+filename,'utf8'),context);
  function state(work=workflow()) {context.work=work;vm.runInContext('initiativeWork=work;initiativeWorkId=work.id;initiativeWorkReadable=true;',context);context.resetPlatformInitiative({id:work.id});vm.runInContext('initiativeWorkReadable=true;',context);return work;}
  ui.node('initiative-work').append(ui.node('iw-accept'),ui.node('iw-execute'),ui.node('iw-integrate'));
  ui.node('iw-runtime-panel').append(ui.node('iw-runtime-resume'),ui.node('iw-runtime-profile-save'),ui.node('iw-runtime-refresh'));
  ui.node('iw-deployment-panel').append(ui.node('iw-deployment-start'));
  ui.node('iw-learning-schema').value='1';ui.node('iw-learning-kind').value='memory';
  return {context,...ui,store,calls,state};
}
function workflow(id='I1') {return {id,revision:4,stage:'review',enabled:true,messages:[],iterations:[],documents:[],progress:[],project:{id:'P1',deployment_profiles:[]},task:{id:'TASK-A',status:'review',events:[]},eval_harness:{available:true,freshness:'current',summary:{decision:'pass',passed:1,total:1},results:[]},learning:{assets:[],bindings:[],metrics:{}},learning_sources:{tasks:[],feedback:[]}};}
function runtime(id='I1'){return {initiative_id:id,run_id:'RUN-A',revision:3,state:'confirmed',task_id:'TASK-A',profile_id:'PROFILE-A',profiles:[{id:'PROFILE-A',name:'默认'}],candidate_sha256:'sha-A',subtasks:[],approvals:[],budget:{token_budget:100,max_workers:2},can_pause:false,can_resume:true,can_cancel:true};}
function withDrafts(a) {
  vm.runInContext(fs.readFileSync('workbench_web/drafts.js','utf8'),a.context);
  a.context.WorkbenchDrafts.init('runtime-A',a.store);
  a.node('iw-result').append(a.node('iw-note'));
  a.node('project-plan-dialog').append(a.node('plan-objective'),a.node('plan-architecture'),a.node('plan-rows'),a.node('plan-save'));
  return a;
}
function edit(a,id,value) {a.node(id).value=value;a.listeners.get('input')({target:a.node(id)});}
function reviewedWorkflow(task='TASK-A',report='REPORT-A',sha='sha-A') {
  return {...workflow(),active_task_id:task,task:{id:task,status:'review',events:[]},
    eval_harness:{...workflow().eval_harness,runner:{candidate_sha256:sha,report_path:report},generated_at:1}};
}

test('background plan revision changes preserve the editor draft and block stale saves',async()=>{
  const a=withDrafts(setup());a.node('home-project').value='P1';
  let plan={project_id:'P1',revision:1,objective:'first plan',architecture_refs:[],milestones:[]};
  a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});return plan;};
  await a.context.refreshPlatformProjectPlan(true);a.context.openProjectPlan();edit(a,'plan-objective','my version-one draft');
  plan={...plan,revision:2,objective:'another human updated this plan'};
  await a.context.refreshPlatformProjectPlan(true);await a.context.saveProjectPlan();
  assert.equal(a.calls.filter(call=>call.body).length,0);
  assert.equal(a.node('plan-objective').value,'my version-one draft');assert.equal(a.node('plan-objective').disabled,false);
  assert.equal(a.node('plan-save').disabled,true);assert.match(a.node('plan-error').textContent,/版本|变化/);
  assert.equal(JSON.parse(a.context.WorkbenchDrafts.capture('project-plan').base),1);
  a.context.initPlatform();a.node('project-plan-close').onclick();a.context.openProjectPlan();
  assert.equal(a.node('plan-objective').value,plan.objective);assert.equal(a.node('plan-save').disabled,false);
  assert.match(a.node('draft-project-plan').querySelector('pre').textContent,/my version-one draft/);
  assert.equal(a.node('draft-project-plan').querySelectorAll('button').some(b=>b.textContent==='恢复草稿'),false);
});

test('switching projects cannot retarget an already open plan editor',async()=>{
  const a=withDrafts(setup());a.node('home-project').value='P1';
  a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});return {project_id:a.node('home-project').value,revision:1,objective:'plan',milestones:[]};};
  await a.context.refreshPlatformProjectPlan(true);a.context.openProjectPlan();edit(a,'plan-objective','P1 only');
  a.node('home-project').value='P2';await a.context.refreshPlatformProjectPlan(true);await a.context.saveProjectPlan();
  assert.equal(a.calls.filter(call=>call.body).length,0);assert.equal(a.node('plan-objective').value,'P1 only');
  assert.equal(a.node('plan-save').disabled,true);assert.match(a.node('plan-error').textContent,/项目|变化/);
});

for(const [label,next] of [
  ['task',reviewedWorkflow('TASK-B','REPORT-B','sha-B')],
  ['candidate',reviewedWorkflow('TASK-A','REPORT-A','sha-B')],
  ['Eval',reviewedWorkflow('TASK-A','REPORT-B','sha-A')],
]) test('a new '+label+' clears live acceptance text while preserving only the old review draft',async()=>{
  const a=withDrafts(setup()),first=reviewedWorkflow();a.state(first);a.context.renderInitiativeWork(first);
  edit(a,'iw-note','review evidence belonging to the first candidate');
  a.context.renderInitiativeWork({...next,revision:9});
  assert.equal(a.node('iw-note').value,'');assert.match(a.node('draft-review').querySelector('pre').textContent,/first candidate/);
  assert.equal(a.node('draft-review').querySelectorAll('button').some(b=>b.textContent==='恢复草稿'),false);
  a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});return {...next,revision:10};};
  await a.context.initiativeWorkAction('accept',{note:a.node('iw-note').value});
  assert.equal(a.calls.filter(call=>call.body).length,0);assert.match(a.node('iw-error').textContent,/验收意见/);
});

test('unchanged candidate and Eval preserve current review input across polling',()=>{
  const a=withDrafts(setup()),work=reviewedWorkflow();a.state(work);a.context.renderInitiativeWork(work);
  edit(a,'iw-note','still reviewing this candidate');a.context.renderInitiativeWork({...work,revision:9});
  assert.equal(a.node('iw-note').value,'still reviewing this candidate');
});

test('another approval changing or arriving preserves the same pending approval reason',async()=>{
  const a=setup();a.state();const approval={id:'AP-A',tool_id:'file.write',status:'pending',args:{path:'a.txt'},args_sha256:'ARGS-A',candidate_sha256:'sha-A'};
  let data={...runtime(),approvals:[approval,{...approval,id:'AP-B',args_sha256:'ARGS-B'}]};a.context.api=async()=>data;
  await a.context.refreshPlatformRuntime();const card=a.node('iw-runtime-approvals').children[0];card.querySelector('textarea').value='reviewed AP-A scope';
  data={...data,revision:4,approvals:[approval,{...data.approvals[1],status:'allowed'},{...approval,id:'AP-C'}]};
  await a.context.refreshPlatformRuntime();assert.equal(a.node('iw-runtime-approvals').children[0],card);
  assert.equal(card.querySelector('textarea').value,'reviewed AP-A scope');
});

for(const [label,change] of [
  ['args SHA',{args_sha256:'ARGS-NEW'}],['parameters',{args:{path:'b.txt'}}],['candidate',{candidate_sha256:'sha-B'}],
]) test('a changed approval '+label+' cannot inherit its old human reason',async()=>{
  const a=setup();a.state();const approval={id:'AP-A',tool_id:'file.write',status:'pending',args:{path:'a.txt'},args_sha256:'ARGS-A',candidate_sha256:'sha-A'};
  let data={...runtime(),approvals:[approval]};a.context.api=async()=>data;await a.context.refreshPlatformRuntime();
  const card=a.node('iw-runtime-approvals').children[0];card.querySelector('textarea').value='only for the original request';
  data={...data,revision:4,approvals:[{...approval,...change}]};await a.context.refreshPlatformRuntime();
  assert.notEqual(a.node('iw-runtime-approvals').children[0],card);assert.equal(a.node('iw-runtime-approvals').querySelector('textarea').value,'');
});

test('failed initiative polling freezes acceptance and authorization while preserving text',async()=>{
  const a=setup();a.state();a.node('iw-note').value='unsent evidence';a.node('iw-accept').disabled=false;
  await a.context.refreshInitiativeWork();
  assert.equal(a.node('iw-accept').disabled,true);assert.equal(a.node('iw-execute').disabled,true);assert.equal(a.node('iw-integrate').disabled,true);
  assert.equal(a.node('iw-stage').textContent,'状态不可读');assert.equal(a.node('iw-note').value,'unsent evidence');
  const before=a.calls.length;await a.context.initiativeWorkAction('accept',{note:'old evidence'});assert.equal(a.calls.length,before);
});
test('a successful reread restores tabs and current acceptance after a failure',async()=>{
  const a=setup();a.state();const tab=a.document.createElement('button');a.node('initiative-work').append(tab);await a.context.refreshInitiativeWork();assert.equal(tab.disabled,true);
  a.context.api=async url=>url.endsWith('/workflow')?workflow():url.endsWith('/plan')?{project_id:'P1',revision:0,milestones:[]}:runtime();await a.context.refreshInitiativeWork();
  assert.equal(tab.disabled,false);assert.equal(a.node('iw-accept').disabled,false);
});
test('opening another initiative removes the previous candidate evidence before a failed read',async()=>{
  const a=setup();a.state();a.node('iw-diff').textContent='old diff';a.node('iw-checks').textContent='old green';a.node('iw-preview-link').hidden=false;a.node('iw-learning-check-implement').value='old.txt';a.node('iw-learning-schema').value='2';a.node('iw-learning-generation-evidence').textContent='old generation';
  a.context.showInitiativeWork({id:'I2'});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(a.node('iw-diff').textContent,'');assert.equal(a.node('iw-checks').textContent,'');assert.equal(a.node('iw-result').hidden,true);assert.equal(a.node('iw-preview-link').hidden,true);
  assert.equal(a.node('iw-learning-check-implement').value,'');assert.equal(a.node('iw-learning-schema').value,'1');assert.equal(a.node('iw-learning-generation-evidence').textContent,'');
});
test('runtime identity mismatch cannot render another initiative or enable controls',async()=>{
  const a=setup();a.state();a.context.api=async()=>runtime('I2');await a.context.refreshPlatformRuntime();
  assert.match(a.node('iw-runtime-status').textContent,/状态不可读/);assert.equal(a.node('iw-runtime-resume').disabled,true);
});
test('a delayed runtime response cannot replace the latest selected initiative',async()=>{
  const a=setup();a.state();let resolve;a.context.api=()=>new Promise(done=>resolve=done);const pending=a.context.refreshPlatformRuntime();
  a.context.resetPlatformInitiative({id:'I2'});resolve(runtime());await pending;assert.equal(a.node('iw-runtime-identity').textContent,'');
});
test('resume and one-time authorization send frozen identity, human reason and revision',async()=>{
  const a=setup();a.state();a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});if(url.endsWith('/workflow'))return workflow();return runtime();};
  await a.context.refreshPlatformRuntime();await a.context.runtimeAction('control',{action:'resume',candidate_sha256:'sha-A'});
  const call=a.calls.find(c=>c.url.endsWith('/runtime/control'));assert.equal(call.body.actor,'operator');assert.equal(call.body.expected_revision,3);assert.equal(call.body.candidate_sha256,'sha-A');assert.ok(call.body.submission_key);
  await a.context.runtimeAction('approvals/AP-A',{decision:'allow',note:'verified scope'});
  assert.equal(a.calls.find(c=>c.url.endsWith('/approvals/AP-A')).body.note,'verified scope');
});
async function controlFixture(a,data) {
  a.state({...workflow(),stage:'executing'});a.context.controlView=data;
  a.context.api=async(url,options)=>{
    a.calls.push({url,body:options?.body?JSON.parse(options.body):null});
    if(options?.method==='POST' || url.endsWith('/runtime'))return a.context.controlView;
    if(url.endsWith('/workflow'))return {...workflow(),stage:'executing'};
    if(url.endsWith('/plan'))return {project_id:'P1',revision:1,milestones:[]};
    if(url.endsWith('/deployments'))return {items:[],plans:[]};
    throw Error('unexpected control fixture read '+url);
  };
  a.context.initPlatform();await a.context.refreshPlatformRuntime();
}
function boundControlRuntime() {return {...runtime(),state:'running',session_id:'SESSION-A',control_revision:7,can_pause:true};}
for(const action of ['pause','cancel'])test(action+' binds the control attempt even when background progress has advanced the payload revision',async()=>{
  const a=setup();await controlFixture(a,boundControlRuntime());
  const original=a.context.api;
  a.context.api=async(url,options)=>{
    if(options?.method==='POST')a.context.controlView={...a.context.controlView,revision:40};
    return original(url,options);
  };
  await a.node('iw-runtime-'+action).onclick();
  const body=a.calls.find(call=>call.url.endsWith('/runtime/control')).body;
  assert.equal(body.action,action);assert.equal(body.expected_revision,3);assert.equal(body.control_revision,7);
  assert.equal(body.run_id,'RUN-A');assert.equal(body.session_id,'SESSION-A');assert.equal(body.actor,'operator');assert.ok(body.submission_key);
  assert.equal(a.calls.filter(call=>call.url.endsWith('/runtime/control')).length,1);
});
test('an existing control button uses the latest attempt tuple rather than the previous render snapshot',async()=>{
  const a=setup();await controlFixture(a,boundControlRuntime());const pause=a.node('iw-runtime-pause').onclick;
  a.context.controlView={...boundControlRuntime(),run_id:'RUN-B',session_id:'SESSION-B',revision:9,control_revision:8,candidate_sha256:'sha-B'};
  await a.context.refreshPlatformRuntime();await pause();
  const body=a.calls.find(call=>call.url.endsWith('/runtime/control')).body;
  assert.equal(body.run_id,'RUN-B');assert.equal(body.session_id,'SESSION-B');assert.equal(body.control_revision,8);
  assert.equal(body.expected_revision,9);assert.equal(body.candidate_sha256,'sha-B');
});
for(const missing of ['run_id','session_id','control_revision'])test('legacy control view missing '+missing+' sends none of the new CAS tuple',async()=>{
  const a=setup(),data=boundControlRuntime();delete data[missing];await controlFixture(a,data);
  await a.node('iw-runtime-cancel').onclick();const body=a.calls.find(call=>call.url.endsWith('/runtime/control')).body;
  for(const field of ['run_id','session_id','control_revision'])assert.equal(Object.hasOwn(body,field),false,field);
  assert.equal(body.expected_revision,3);assert.equal(body.action,'cancel');assert.ok(body.submission_key);
});
test('resume remains bound to the strict payload revision and candidate without stop-control CAS fields',async()=>{
  const a=setup();await controlFixture(a,{...boundControlRuntime(),state:'paused',revision:9,can_resume:true});
  await a.node('iw-runtime-resume').onclick();const body=a.calls.find(call=>call.url.endsWith('/runtime/control')).body;
  assert.equal(body.action,'resume');assert.equal(body.expected_revision,9);assert.equal(body.candidate_sha256,'sha-A');
  for(const field of ['run_id','session_id','control_revision'])assert.equal(Object.hasOwn(body,field),false,field);
});
test('a rejected stop-control CAS freezes its current view without replaying the request',async()=>{
  const a=setup();await controlFixture(a,boundControlRuntime());const original=a.context.api;
  a.context.api=async(url,options)=>{if(options?.method==='POST'){a.calls.push({url,body:JSON.parse(options.body)});throw Error('fixture control changed');}return original(url,options);};
  await a.node('iw-runtime-pause').onclick();
  assert.equal(a.calls.filter(call=>call.url.endsWith('/runtime/control')).length,1);
  assert.equal(vm.runInContext('platformState.runtimeReadable',a.context),false);assert.match(a.node('iw-runtime-status').textContent,/待核对/);
});
test('subtask editor sends explicit read/write/resource sets and invalidates prepared starts on edits',()=>{
  const a=setup();a.state();a.context.initPlatform();a.context.addSubtaskRow({name:'review',prompt:'check behavior',read_set:['src/a.py'],write_set:[],resource_set:['report']});
  assert.deepEqual(JSON.parse(JSON.stringify(a.context.subtaskPayload())),[{name:'review',prompt:'check behavior',read_set:['src/a.py'],write_set:[],resource_set:['report']}]);
  a.node('iw-subtask-start').hidden=false;a.node('iw-subtask-editor').oninput();assert.equal(a.node('iw-subtask-start').hidden,true);
});
test('polling cannot re-enable a prepared subtask start after its draft changed',async()=>{
  const a=setup(),work=workflow();work.stage='confirmed';a.state(work);a.context.initPlatform();
  const prepared={...runtime(),state:'prepared',subtask_plan_id:'SUB-PLAN'};a.context.api=async()=>prepared;
  await a.context.refreshPlatformRuntime();assert.equal(a.node('iw-subtask-start').hidden,false);assert.equal(a.node('iw-subtask-start').disabled,false);
  a.node('iw-subtask-editor').oninput();await a.context.refreshPlatformRuntime();assert.equal(a.node('iw-subtask-start').hidden,true);assert.match(a.node('iw-subtask-plan').textContent,/草稿已变化/);
});
test('runtime polling preserves a human reason typed for the same pending approval',async()=>{
  const a=setup();a.state();const data={...runtime(),approvals:[{id:'AP-A',tool_id:'file.write',status:'pending',args:{path:'a.txt'},candidate_sha256:'sha'}]};a.context.api=async()=>data;
  await a.context.refreshPlatformRuntime();const card=a.node('iw-runtime-approvals').children[0],note=card.querySelector('textarea');note.value='checked business scope';
  await a.context.refreshPlatformRuntime();assert.equal(a.node('iw-runtime-approvals').children[0],card);assert.equal(note.value,'checked business scope');
});
test('preview has a read-only plan and requires a separate human start without restoring permission',async()=>{
  const a=setup();a.state();a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});return options ? {plan_id:'PREVIEW-PLAN',task_id:'TASK-A',configuration_revision:2,expected_candidate_sha256:'sha-A',url:'http://127.0.0.1:12345/'} : {plan_id:'PREVIEW-PLAN',task_id:'TASK-A',available:true,configuration_revision:2,expected_candidate_sha256:'sha-A',command:['C:/Python/python.exe','serve.py']};};
  await a.context.openPlatformPreview();assert.equal(a.calls.length,1);assert.equal(a.calls[0].body,null);assert.equal(a.node('iw-preview-link').hidden,true);
  await a.context.startPlatformPreview();assert.equal(a.calls[1].body.confirmed,true);assert.equal(a.calls[1].body.plan_id,'PREVIEW-PLAN');assert.equal(a.calls[1].body.configuration_revision,2);assert.equal(a.calls[1].body.expected_candidate_sha256,'sha-A');assert.equal(a.node('iw-preview-link').hidden,false);
  a.context.resetPlatformInitiative({id:'I2'});await a.context.startPlatformPreview();assert.equal(a.calls.length,2);
});
test('preview rejects a link returned for a different task',async()=>{
  const a=setup();a.state();a.context.api=async(url,options)=>options?{task_id:'TASK-B',url:'http://127.0.0.1:12345/'}:{plan_id:'PLAN',task_id:'TASK-A',configuration_revision:1,expected_candidate_sha256:'sha'};
  await a.context.openPlatformPreview();await a.context.startPlatformPreview();assert.equal(a.node('iw-preview-link').hidden,true);assert.match(a.node('preview-plan-status').textContent,/身份无法核对/);
});
test('generated evidence draft fills fields only after explicit selection and keeps v2 checks',()=>{
  const a=setup(),work=workflow();work.learning.generations=[{id:'G-A',status:'succeeded',candidate:{kind:'workflow',task_id:'TASK-A',title:'proposed',content:'reason',boundary:'local scope',applies:['case'],excludes:[],generation_id:'G-A',evidence_refs:[{claim:'reason',evidence_id:'E-A'}],recipe:{schema_version:2,parameters:[],preconditions:[{kind:'file_exists',path:'before.txt'}],steps:[{phase:'implement',instruction:'actual implementation'}],stage_checks:{precheck:[],implement:[{kind:'file_contains',path:'after.txt',text:'done'}],eval:[]},required_files:[{phase:'eval',path:'report.json'}]}}}];
  a.state(work);a.context.initLearning();a.node('iw-learning-title').value='my text';a.context.renderLearningGeneration(work,false);assert.equal(a.node('iw-learning-title').value,'my text');
  a.context.useLearningGeneration();assert.equal(a.node('iw-learning-title').value,'proposed');assert.equal(a.node('iw-learning-generation-id').value,'G-A');assert.equal(a.node('iw-learning-evidence-refs').value,'reason | E-A');assert.equal(a.node('iw-learning-check-implement').value,'after.txt | done');assert.equal(a.node('iw-learning-required-eval').value,'report.json');assert.equal(a.node('iw-learning-v2').hidden,false);
});
test('v2 candidate saves phase checks and claim provenance without arbitrary commands',()=>{
  const a=setup();a.state();a.context.initLearning();let fields;a.context.learningAction=body=>fields=body;
  for(const [key,value] of Object.entries({kind:'workflow',task:'TASK-A',title:'reviewed',schema:'2','check-precheck':'input.txt','check-implement':'output.txt | valid','required-eval':'report.json','generation-id':'G-A','evidence-refs':'claim | E-A'}))a.node('iw-learning-'+key).value=value;
  a.node('iw-learning-create').onclick();assert.equal(fields.candidate.recipe.schema_version,2);assert.equal(fields.candidate.recipe.stage_checks.implement[0].text,'valid');assert.equal(fields.candidate.evidence_refs[0].evidence_id,'E-A');assert.equal(fields.candidate.generation_id,'G-A');assert.equal(fields.candidate.recipe.recovery,'retain_candidate_new_plan');
});
test('plan save binds revision and milestone dependencies while unreadable plans cannot save',async()=>{
  const a=setup();a.node('home-project').value='P1';a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});return {project_id:'P1',revision:1,objective:'goal',architecture_refs:[],milestones:[]};};
  await a.context.refreshPlatformProjectPlan(true);a.context.openProjectPlan();a.context.addMilestoneRow({id:'M2',title:'release',acceptance:['observed'],depends_on:['M1'],initiative_ids:['I1']});await a.context.saveProjectPlan();
  const body=a.calls.find(c=>c.body)?.body;assert.equal(body.expected_revision,1);assert.deepEqual(body.milestones[0].depends_on,['M1']);assert.deepEqual(body.milestones[0].initiative_ids,['I1']);
});
test('migration prepares an archive and displays an offline restore command, never executes recovery',async()=>{
  const a=setup();a.context.api=async(url,options)=>{a.calls.push({url,body:options?.body?JSON.parse(options.body):null});return options?{archive_path:'D:/archive.zip',sha256:'digest'}:{runtime_root:'D:/runtime',projects:[{root_path:'D:/p'}],boundary:'external projects need mapping'};};
  await a.context.openMigration();a.node('migration-target').value='E:/new runtime';await a.context.prepareMigration();
  assert.equal(a.calls[1].url,'/api/v1/migration/prepare');assert.equal(a.calls[1].body.confirmed,true);assert.match(a.node('migration-command').textContent,/restore-workbench-migration/);assert.match(a.node('migration-command').textContent,/E:\/new runtime/);assert.equal(a.calls.some(c=>c.url.includes('/restore')),false);
});
test('failed metrics reads show unknown and do not manufacture zero success',async()=>{
  const a=setup();await a.context.openLearningMetrics();assert.match(a.node('learning-metrics-status').textContent,/不可读/);assert.equal(a.node('learning-metrics-values').children.length,0);
});
test('unavailable or unbound preview plans never enable process authorization',async()=>{
  const a=setup();a.state();a.context.api=async()=>({task_id:'TASK-A',available:false,legacy:true,notice:'no preview configuration'});
  await a.context.openPlatformPreview();assert.equal(a.node('preview-plan-start').disabled,true);assert.match(a.node('preview-plan-status').textContent,/no preview configuration/);
  a.context.api=async()=>({task_id:'TASK-A',available:true,configuration_revision:1,expected_candidate_sha256:'sha'});await a.context.openPlatformPreview();assert.equal(a.node('preview-plan-start').disabled,true);
});
test('advanced disabled runtime leaves controls readable while freezing profile and subtask writes',async()=>{
  const a=setup(),work=workflow();work.stage='confirmed';a.state(work);a.context.api=async()=>({...runtime(),advanced_enabled:false});await a.context.refreshPlatformRuntime();
  assert.match(a.node('iw-runtime-status').textContent,/尚未启用/);assert.equal(a.node('iw-runtime-profile-save').disabled,true);assert.equal(a.node('iw-subtask-prepare').disabled,true);assert.equal(a.node('iw-runtime-refresh').disabled,false);
});
test('deployment prepare does not start and business evidence survives polling',async()=>{
  const a=setup(),work=workflow();work.stage='integrated';work.project.deployment_profiles=[{id:'LOCAL',name:'local'}];a.state(work);a.context.initPlatform();a.context.refreshInitiativeWork=async()=>{};
  let deployed=false;a.context.api=async(url,options)=>{
    a.calls.push({url,body:options?.body?JSON.parse(options.body):null});
    if(url.endsWith('/prepare'))return {plan_id:'DEP-PLAN',status:'prepared',command:['D:/python.exe','release.py'],rollback_command:['D:/python.exe','rollback.py']};
    if(url.endsWith('/start')){deployed=true;return {deployment_id:'DEP-A',status:'running'};}
    if(url.endsWith('/deployments'))return {plans:[],items:deployed?[{initiative_id:'I1',deployment_id:'DEP-A',status:'awaiting_business_review',rollback_command:['D:/python.exe','rollback.py']}]:[]};
    if(url.endsWith('/plan'))return {project_id:'P1',revision:0,milestones:[]};return runtime();
  };
  await a.context.refreshDeployments();await a.context.deploymentAction('prepare',{profile_id:'LOCAL'});assert.equal(a.calls.some(c=>c.url.endsWith('/start')),false);assert.equal(a.node('iw-deployment-start').hidden,false);
  await a.context.deploymentAction('start',{plan_id:'DEP-PLAN',confirmed:true});const start=a.calls.find(c=>c.url.endsWith('/start'));assert.equal(start.body.expected_revision,4);assert.equal(start.body.confirmed,true);
  a.node('iw-deployment-business').value='actual observed business evidence';await a.context.refreshDeployments();assert.equal(a.node('iw-deployment-business').value,'actual observed business evidence');assert.equal(a.node('iw-deployment-verify').hidden,false);assert.equal(a.node('iw-deployment-rollback').hidden,false);
  a.node('iw-deployment-rollback').onclick();assert.match(a.node('iw-rollback-command').textContent,/rollback.py/);assert.equal(a.calls.some(c=>c.url.endsWith('/rollback')),false);
  a.context.api=async()=>{throw Error('offline');};await a.context.refreshDeployments();assert.equal(a.node('iw-deployment-start').disabled,true);const count=a.calls.length;await a.context.deploymentAction('start',{plan_id:'DEP-PLAN',confirmed:true});assert.equal(a.calls.length,count);
});
test('learning generation retries use the same key for the same reviewed inputs',async()=>{
  const a=setup();a.state();a.context.api=async(url,options)=>{if(options)a.calls.push({url,body:JSON.parse(options.body)});throw Error('uncertain');};
  const fields={action:'generate',kind:'memory',task_id:'TASK-A',guidance:'retain source'};
  await a.context.initiativeWorkAction('learning',{fields});vm.runInContext('initiativeWorkReadable=true;',a.context);await a.context.initiativeWorkAction('learning',{fields});
  assert.equal(a.calls.length,2);assert.ok(a.calls[0].body.submission_key);assert.equal(a.calls[0].body.submission_key,a.calls[1].body.submission_key);
});
test('project configuration save sends a stable key and advances the acknowledged revision',async()=>{
  const a=setup();vm.runInContext(fs.readFileSync('workbench_web/initiatives.js','utf8'),a.context);a.context.loadInitiativeProjects=async()=>{};
  a.context.editRegisteredProject({id:'P1',name:'project',root_path:'D:/p',eval_command:[],configuration_revision:2});
  a.node('project-preview-command').value='["D:/Python/python.exe", "preview.py", "{port}"]';a.context.api=async(url,options)=>{a.calls.push({url,body:JSON.parse(options.body)});return {id:'P1',name:'project',root_path:'D:/p',eval_command:[],configuration_revision:3};};
  await a.node('project-register').onclick();assert.equal(a.calls[0].body.expected_configuration_revision,2);assert.ok(a.calls[0].body.submission_key);await a.node('project-register').onclick();assert.equal(a.calls[1].body.expected_configuration_revision,3);assert.notEqual(a.calls[1].body.submission_key,a.calls[0].body.submission_key);
});
test('release history selection binds a rollback confirmation to the displayed release',async()=>{
  const a=setup(),work=workflow();work.stage='integrated';a.state(work);a.context.initPlatform();
  const newer={initiative_id:'I1',deployment_id:'DEP-NEW',started_at:2,status:'failed',rollback_command:['D:/python.exe','new.py']},older={initiative_id:'I1',deployment_id:'DEP-OLD',started_at:1,status:'released',rollback_command:['D:/python.exe','old.py']};
  a.context.api=async()=>({items:[newer,older],plans:[]});await a.context.refreshDeployments();assert.equal(a.node('iw-deployment-select').value,'DEP-NEW');
  a.node('iw-deployment-select').value='DEP-OLD';a.node('iw-deployment-select').onchange();a.node('iw-deployment-rollback').onclick();assert.match(a.node('iw-rollback-command').textContent,/old.py/);
  let fields;a.context.deploymentAction=(action,body)=>fields={action,...body};a.node('iw-rollback-confirm').onclick();assert.equal(fields.deployment_id,'DEP-OLD');
  a.node('iw-deployment-select').value='DEP-NEW';a.node('iw-deployment-select').onchange();fields=null;a.node('iw-rollback-confirm').onclick();assert.equal(fields,null);assert.equal(a.node('iw-rollback-plan').hidden,true);
});

function loadRealApi(a) {
  vm.runInContext(fs.readFileSync('workbench_web/app.js','utf8').replace(/boot\(\);\s*$/, ''),a.context);
  a.node('task-actor').value='operator';
}
function serviceResponse(service='SERVICE-A',runtimeId='RUNTIME-A',body={ok:true}) {
  return {ok:true,headers:new Headers({'X-Workbench-Service-Instance':service,'X-Workbench-Runtime-Instance':runtimeId}),json:async()=>body};
}
test('service restart freezes all decisions and retains drafts without adopting the replacement identity',async()=>{
  const a=setup();a.state();loadRealApi(a);a.node('iw-note').value='unsent business evidence';
  let flushes=0;a.context.WorkbenchDrafts={flush(){flushes++;}};const requests=[];
  a.context.fetch=async(path,options)=>{requests.push({path,options});return serviceResponse();};
  await a.context.api('/api/health');await a.context.api('/api/v1/initiatives/I1/runtime');
  assert.equal(requests[1].options.headers.get('X-Workbench-Expected-Service-Instance'),'SERVICE-A');
  assert.equal(requests[1].options.headers.get('X-Workbench-Expected-Runtime-Instance'),'RUNTIME-A');
  a.context.fetch=async()=>{requests.push({path:'changed'});return serviceResponse('SERVICE-B');};
  await assert.rejects(a.context.api('/api/v1/initiatives/I1/workflow'),/服务身份变化/);
  assert.equal(a.context.workbenchWritesFrozen(),true);assert.equal(flushes,1);assert.equal(a.node('iw-note').value,'unsent business evidence');
  for(const id of ['iw-execute','iw-accept','iw-runtime-resume','iw-subtask-start','iw-learning-create','iw-deployment-start','iw-deployment-verify','iw-rollback-confirm','project-register','plan-save','migration-prepare'])assert.equal(a.node(id).disabled,true,id);
  assert.equal(a.node('service-identity-status').hidden,false);assert.match(a.node('service-identity-status').textContent,/重新载入/);
  const before=requests.length;await assert.rejects(a.context.api('/api/v1/initiatives/I1/runtime/control',{method:'POST'}),/保持冻结/);assert.equal(requests.length,before);
  assert.equal(vm.runInContext('workbenchServiceIdentity.service',a.context),'SERVICE-A');
});
test('changing the runtime database or losing bound identity headers freezes further operations',async()=>{
  for(const replacement of [serviceResponse('SERVICE-A','RUNTIME-B'),{ok:true,headers:new Headers(),json:async()=>({ok:true})}]){
    const a=setup();loadRealApi(a);a.context.fetch=async()=>serviceResponse();await a.context.api('/api/health');
    a.context.fetch=async()=>replacement;await assert.rejects(a.context.api('/api/v1/projects'),/服务身份变化/);assert.equal(a.context.workbenchWritesFrozen(),true);
  }
});
test('minimal response fixtures without headers remain compatible',async()=>{
  const a=setup();loadRealApi(a);a.context.fetch=async()=>({ok:true,json:async()=>({surface:'workbench'})});
  assert.equal((await a.context.api('/api/health')).surface,'workbench');assert.equal(a.context.workbenchWritesFrozen(),false);
});
test('a real headers interface without initial service identity cannot authorize an unknown service',async()=>{
  const a=setup();loadRealApi(a);a.context.fetch=async()=>({ok:true,headers:new Headers(),json:async()=>({surface:'workbench'})});
  await assert.rejects(a.context.api('/api/health'),/身份变化或缺失/);assert.equal(a.context.workbenchWritesFrozen(),true);
});
test('a matching response already in flight cannot thaw state after another request detects a restart',async()=>{
  const a=setup();loadRealApi(a);a.context.fetch=async()=>serviceResponse();await a.context.api('/api/health');
  let finishBody,bodyStarted;const started=new Promise(done=>bodyStarted=done);
  a.context.fetch=async path=>path==='/slow'?{...serviceResponse(),json:()=>{bodyStarted();return new Promise(done=>finishBody=done);}}:serviceResponse('SERVICE-B');
  const slow=a.context.api('/slow');await started;await assert.rejects(a.context.api('/changed'),/服务身份变化/);
  finishBody({ok:true});await assert.rejects(slow,/保持冻结/);assert.equal(a.context.workbenchWritesFrozen(),true);
});
test('server instance rejection freezes the UI even if response headers still match',async()=>{
  const a=setup();loadRealApi(a);a.context.fetch=async()=>serviceResponse();await a.context.api('/api/health');
  a.context.fetch=async()=>({...serviceResponse('SERVICE-A','RUNTIME-A',{error:'instance_changed',message:'service must be rechecked'}),ok:false});
  await assert.rejects(a.context.api('/api/v1/initiatives/I1/runtime/control',{method:'POST'}),/service must be rechecked/);
  assert.equal(a.context.workbenchWritesFrozen(),true);assert.equal(a.node('iw-runtime-resume').disabled,true);
});
test('preview links are rejected when the returned plan, configuration or candidate drifted',async()=>{
  const plan={plan_id:'PLAN-A',task_id:'TASK-A',available:true,configuration_revision:2,expected_candidate_sha256:'sha-A'};
  for(const drift of [{plan_id:'PLAN-B'},{configuration_revision:3},{expected_candidate_sha256:'sha-B'}]){
    const a=setup();a.state();a.context.api=async(url,options)=>options?{...plan,url:'http://127.0.0.1:12345/',...drift}:plan;
    await a.context.openPlatformPreview();await a.context.startPlatformPreview();assert.equal(a.node('iw-preview-link').hidden,true);assert.match(a.node('preview-plan-status').textContent,/候选或配置不一致/);
  }
});
test('subtask preparation defaults to two workers and sends each supported frozen budget without starting',async()=>{
  for(const workers of [2,3,4]){
    const a=setup(),work=workflow();work.stage='confirmed';a.state(work);a.context.initPlatform();assert.equal(a.node('iw-subtask-workers').value,'2');
    a.context.api=async(url,options)=>{if(options)a.calls.push({url,body:JSON.parse(options.body)});if(url.endsWith('/workflow'))return work;if(url.endsWith('/plan'))return {project_id:'P1',revision:0,milestones:[]};return {...runtime(),state:'prepared',subtask_plan_id:'SUB-PLAN',budget:{max_workers:workers}};};
    await a.context.refreshPlatformRuntime();a.node('iw-subtask-workers').value=String(workers);a.node('iw-subtask-workers').onchange();await a.node('iw-subtask-prepare').onclick();
    const prepared=a.calls.find(c=>c.url.endsWith('/subtasks/prepare'));assert.equal(prepared.body.max_workers,workers);assert.equal(typeof prepared.body.max_workers,'number');assert.equal(prepared.body.expected_revision,3);assert.ok(prepared.body.submission_key);
    assert.equal(a.calls.some(c=>c.url.endsWith('/start')),false);assert.equal(JSON.parse(a.node('iw-subtask-plan').textContent.split('\n').slice(1).join('\n')).max_workers,workers);
  }
});
test('changing the worker budget invalidates an old prepared plan and polling preserves the new preference',async()=>{
  const a=setup(),work=workflow();work.stage='confirmed';a.state(work);a.context.initPlatform();a.context.api=async()=>({...runtime(),state:'prepared',subtask_plan_id:'SUB-PLAN',budget:{max_workers:4}});
  await a.context.refreshPlatformRuntime();assert.equal(a.node('iw-subtask-workers').value,'4');assert.equal(a.node('iw-subtask-start').hidden,false);
  a.node('iw-subtask-workers').value='3';a.node('iw-subtask-workers').onchange();await a.context.refreshPlatformRuntime();assert.equal(a.node('iw-subtask-workers').value,'3');assert.equal(a.node('iw-subtask-start').hidden,true);assert.match(a.node('iw-subtask-plan').textContent,/草稿已变化/);assert.match(a.node('iw-subtask-plan').textContent,/"max_workers": 4/);
  a.node('iw-subtask-workers').value='5';const before=a.calls.length;await a.node('iw-subtask-prepare').onclick();assert.equal(a.calls.length,before);assert.match(a.node('iw-runtime-status').textContent,/2、3 或 4/);
});
test('subtask drafts save only the worker preference and content while restoration requires a new plan',()=>{
  const a=setup();a.state();a.context.initPlatform();a.node('task-actor').value='operator';a.node('iw-subtask-workers').value='4';let capture,restore;
  a.context.WorkbenchDrafts={track(group,scope,read,apply){capture=read;restore=apply;}};a.context.trackRuntimeDraft(runtime());
  assert.deepEqual(JSON.parse(JSON.stringify(capture())),{rows:[],max_workers:4});
  a.node('iw-subtask-start').hidden=false;restore({rows:[],max_workers:3,actor:'forged',confirmed:true});assert.equal(a.node('iw-subtask-workers').value,'3');assert.equal(a.node('task-actor').value,'operator');assert.equal(a.node('iw-subtask-start').hidden,true);
  restore({rows:[],max_workers:9});assert.equal(a.node('iw-subtask-workers').value,'2');
});
test('a stalled write has a bounded deadline and reports an unknown result without replaying',async()=>{
  const a=setup();loadRealApi(a);const timers=[];let requests=0,signal;
  a.context.setTimeout=(callback,ms)=>{const timer={callback,ms};timers.push(timer);return timer;};a.context.clearTimeout=timer=>timer.cleared=true;
  a.context.fetch=async(path,options)=>{requests++;signal=options.signal;return new Promise(()=>{});};
  const pending=a.context.api('/api/v1/initiatives/I1/runtime/control',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"action":"pause"}'});
  assert.equal(timers.length,1,'a write must have a deadline');assert.equal(timers[0].ms,30000);timers[0].callback();
  await assert.rejects(pending,error=>error.code==='request_timeout' && error.uncertain===true && /结果尚未确认/.test(error.message));assert.equal(signal.aborted,true);assert.equal(requests,1);assert.equal(timers[0].cleared,true);
});
function isolateActionRenderer(a) {
  a.context.renderInitiativeWork=next=>{a.context.renderedWork=next;vm.runInContext('initiativeWork=renderedWork;',a.context);};
}
test('a pending action in one initiative does not lock another and its response cannot unlock another submission',async()=>{
  const a=setup();a.state();isolateActionRenderer(a);const pending=new Map();
  a.context.api=(url,options)=>{if(options)return new Promise(resolve=>pending.set(url.match(/initiatives\/([^/]+)/)[1],resolve));return Promise.resolve(workflow(url.includes('/I2/')?'I2':'I1'));};
  const old=a.context.initiativeWorkAction('discuss',{text:'old A'});a.context.showInitiativeWork({id:'I2'});await new Promise(done=>setImmediate(done));
  assert.equal(vm.runInContext('initiativeWorkPending',a.context),false,'I1 pending state must not lock I2');
  const current=a.context.initiativeWorkAction('discuss',{text:'new B'});assert.equal(pending.has('I2'),true);
  pending.get('I1')({...workflow(),revision:5});await old;assert.equal(vm.runInContext('initiativeWorkPending',a.context),true,'old I1 response must not unlock I2');assert.equal(vm.runInContext('initiativeWork.id',a.context),'I2');
  pending.get('I2')({...workflow('I2'),revision:5});await current;assert.equal(vm.runInContext('initiativeWorkPending',a.context),false);
});
test('returning to an initiative rejects its old action response and preserves the latest evidence and draft',async()=>{
  const a=setup();a.state();isolateActionRenderer(a);let resolve,posts=0;
  const latest={...workflow(),revision:9};a.context.api=(url,options)=>{if(options){posts++;return new Promise(done=>resolve=done);}return Promise.resolve(url.includes('/I2/')?workflow('I2'):latest);};
  const old=a.context.initiativeWorkAction('discuss',{text:'sent before navigation'});
  a.context.showInitiativeWork({id:'I2'});await new Promise(done=>setImmediate(done));a.context.showInitiativeWork({id:'I1'});await new Promise(done=>setImmediate(done));
  assert.equal(vm.runInContext('initiativeWorkPending',a.context),true);a.node('iw-message').value='new unsent draft';await a.context.initiativeWorkAction('discuss',{text:'do not send twice'});assert.equal(posts,1);
  resolve({...workflow(),revision:5,stage:'researching'});await old;await new Promise(done=>setImmediate(done));
  assert.equal(vm.runInContext('initiativeWork.revision',a.context),9);assert.equal(vm.runInContext('initiativeWorkPending',a.context),false);assert.equal(a.node('iw-message').value,'new unsent draft');assert.equal(posts,1);
});
test('the request deadline also covers a stalled JSON body and discards its late result',async()=>{
  const a=setup();loadRealApi(a);const timers=[];let finishBody,reads=0;
  a.context.setTimeout=(callback,ms)=>{const timer={callback,ms};timers.push(timer);return timer;};a.context.clearTimeout=timer=>timer.cleared=true;
  a.context.fetch=async()=>({...serviceResponse(),json:()=>{reads++;return new Promise(done=>finishBody=done);}});
  const pending=a.context.api('/api/v1/initiatives/I1/workflow');await new Promise(done=>setImmediate(done));assert.equal(reads,1);assert.equal(timers[0].ms,10000);
  timers[0].callback();await assert.rejects(pending,error=>error.code==='request_timeout' && error.uncertain===false && /读取超时/.test(error.message));
  finishBody({id:'I1',revision:99});await new Promise(done=>setImmediate(done));assert.equal(a.context.workbenchWritesFrozen(),false);assert.equal(timers[0].cleared,true);
});
test('successful requests clear their deadline and deliberate project registration has a longer bound',async()=>{
  const a=setup();loadRealApi(a);const timers=[];let requests=0;
  a.context.setTimeout=(callback,ms)=>{const timer={callback,ms};timers.push(timer);return timer;};a.context.clearTimeout=timer=>timer.cleared=true;a.context.fetch=async()=>{requests++;return serviceResponse();};
  await a.context.api('/api/v1/projects',{method:'POST',body:'{}'});assert.equal(timers[0].ms,120000);assert.equal(timers[0].cleared,true);assert.equal(requests,1);
});
test('an actual write timeout retains its identity-only journal across reload without resending',async()=>{
  const a=setup();loadRealApi(a);const timers=[];let writes=0;
  a.context.setTimeout=(callback,ms)=>{const timer={callback,ms};timers.push(timer);return timer;};a.context.clearTimeout=()=>{};
  a.context.fetch=async(path,options)=>{if(options.method==='POST'){writes++;return new Promise(()=>{});}return serviceResponse();};
  await a.context.api('/api/health');const path='/api/v1/initiatives/I1/runtime/control';
  const pending=a.context.platformPost(path,{actor:'operator',action:'pause',submission_key:'PAUSE-A'});timers[1].callback();await assert.rejects(pending,/提交超时/);assert.equal(writes,1);
  const raw=a.store.getItem('workbench-mutation-journal-v1:RUNTIME-A');assert.match(raw,/PAUSE-A/);assert.doesNotMatch(raw,/operator|action|pause|confirmed|actor/);
  const restored=setup();restored.context.WorkbenchMutationJournal.init('RUNTIME-A',a.store);assert.equal(restored.node('mutation-journal-items').children.length,1);assert.equal(restored.calls.length,0);
  await assert.rejects(restored.context.platformPost(path,{submission_key:'PAUSE-B'}),/本次没有发送新请求/);assert.equal(restored.calls.length,0);
});
