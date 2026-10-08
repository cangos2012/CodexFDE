const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {dom,storage}=require('./web_dom.cjs');
function setup(withApp=false){
  const ui=dom(),calls=[],store=storage();
  for(const match of fs.readFileSync('workbench_web/index.html','utf8').matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
    const node=ui.element(match[1]);node.hidden=/\bhidden\b/.test(match[2]);node.addEventListener=(event,fn)=>node['on'+event]=fn;ui.nodes.set(match[3],node);
  }
  ui.document.querySelector=selector=>ui.node(selector);
  const context=vm.createContext({document:ui.document,localStorage:store,Date,Event:class{},TextEncoder,URLSearchParams,
    crypto:require('node:crypto').webcrypto,AbortController,Headers,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){},
    actorName:()=> 'fixture',show:(id,value)=>ui.node(id).textContent=value,workspaceView(){},refreshProjectHome:async()=>{},
    api:async(url,options)=>{calls.push({url,method:options?.method || 'GET',body:options?.body?JSON.parse(options.body):null});
      if(url.endsWith('/workflow'))return work();if(url.endsWith('/runtime'))return runtime();if(url.endsWith('/deployments'))return {items:[],plans:[]};
      if(url.endsWith('/plan'))return {project_id:'P1',revision:1,milestones:[]};throw Error('unexpected read '+url);}});
  for(const file of ['workspace-dashboard.js','initiative_workflow.js','learning.js','platform.js'])vm.runInContext(fs.readFileSync('workbench_web/'+file,'utf8'),context);
  if(withApp){const api=context.api;vm.runInContext(fs.readFileSync('workbench_web/app.js','utf8').replace(/boot\(\);\s*$/,''),context);context.api=api;}
  ui.node('task-actor').value='fixture';ui.node('iw-learning-kind').value='memory';ui.node('iw-learning-schema').value='1';
  context.fixtureWork=work();vm.runInContext('initiativeWork=fixtureWork;initiativeWorkId=fixtureWork.id;initiativeWorkReadable=true;',context);context.resetPlatformInitiative({id:'I1'});
  vm.runInContext('initiativeWorkReadable=true;',context);
  return {...ui,context,calls,store};
}
function work(id='I1',revision=4){return {id,revision,stage:'integrated',enabled:true,messages:[],iterations:[],documents:[],progress:[],project:{id:'P1',deployment_profiles:[]},task:{id:'TASK-A',status:'review',events:[]},learning:{assets:[],bindings:[],metrics:{}},learning_sources:{tasks:[],feedback:[]}};}
function runtime(id='I1'){return {initiative_id:id,revision:3,state:'idle',profiles:[],approvals:[],subtasks:[],budget:{}};}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('rendering cached workflow never starts network reads',async()=>{
  const a=setup();a.context.renderPlatformWorkflow(work());await tick();assert.equal(a.calls.length,0);
});
test('slow runtime and deployment reads are shared and the first valid response applies',async()=>{
  const a=setup(),pending=[];a.context.api=url=>new Promise(resolve=>{a.calls.push({url});pending.push({url,resolve});});
  const runtime1=a.context.refreshPlatformRuntime(),runtime2=a.context.refreshPlatformRuntime();
  const deploy1=a.context.refreshDeployments(),deploy2=a.context.refreshDeployments();
  await tick();assert.equal(a.calls.filter(c=>c.url.endsWith('/runtime')).length,1);assert.equal(a.calls.filter(c=>c.url.endsWith('/deployments')).length,1);
  pending.find(p=>p.url.endsWith('/runtime')).resolve(runtime());pending.find(p=>p.url.endsWith('/deployments')).resolve({items:[],plans:[]});
  await Promise.all([runtime1,runtime2,deploy1,deploy2]);assert.equal(vm.runInContext('platformState.runtimeReadable',a.context),true);
});
test('a failed shared read is cleared and a deliberate reread can recover without retrying writes',async()=>{
  const a=setup();let count=0;a.context.api=async()=>{++count;throw Error('offline');};
  await Promise.all([a.context.refreshPlatformRuntime(),a.context.refreshPlatformRuntime()]);assert.equal(count,1);assert.equal(vm.runInContext('platformState.runtimeReadable',a.context),false);
  a.context.api=async()=>{++count;return runtime();};await a.context.refreshPlatformRuntime();assert.equal(count,2);assert.equal(vm.runInContext('platformState.runtimeReadable',a.context),true);
});
test('manual and poll refresh share each endpoint while a slow workflow is pending',async()=>{
  const a=setup(),original=a.context.api;let resolve;a.context.api=(url,options)=>url.endsWith('/workflow')?new Promise(done=>{a.calls.push({url});resolve=done;}):original(url,options);
  a.context.initPlatform();const poll=a.context.refreshInitiativeWork(),manual=a.node('iw-runtime-refresh').onclick();await tick();
  assert.equal(a.calls.filter(c=>c.url.endsWith('/workflow')).length,1);resolve(work());await Promise.all([poll,manual]);
  for(const path of ['/workflow','/runtime','/deployments','/plan'])assert.equal(a.calls.filter(c=>c.url.endsWith(path)).length,1,path);
});
test('a pre-mutation read cannot overwrite the confirmed mutation response',async()=>{
  const a=setup(),original=a.context.api;let resolve;a.context.api=(url,options)=>{
    if(options?.method==='POST')return Promise.resolve(work('I1',8));
    if(url.endsWith('/workflow'))return new Promise(done=>{resolve=done;});return original(url,options);
  };
  const old=a.context.refreshInitiativeWork();await tick();await a.context.initiativeWorkAction('integrate');resolve(work('I1',4));await old;
  assert.equal(vm.runInContext('initiativeWork.revision',a.context),8);
});
test('switching away and back starts a new scoped read and discards the old response',async()=>{
  const a=setup(),pending=[];a.context.api=url=>new Promise(resolve=>pending.push({url,resolve}));
  const old=a.context.refreshPlatformRuntime();await tick();
  a.context.resetPlatformInitiative({id:'I2'});a.context.resetPlatformInitiative({id:'I1'});const current=a.context.refreshPlatformRuntime();await tick();
  assert.equal(pending.length,2);pending[0].resolve({...runtime(),revision:1});await old;assert.equal(vm.runInContext('platformState.runtimeReadable',a.context),false);
  pending[1].resolve({...runtime(),revision:9});await current;assert.equal(vm.runInContext('platformState.runtime.revision',a.context),9);
});
test('the task panel reads a frozen preview plan and starts only after explicit confirmation',async()=>{
  const a=setup(true),plan={task_id:'TASK-A',plan_id:'PLAN-A',configuration_revision:2,expected_candidate_sha256:'sha',url:'http://127.0.0.1:9999',legacy:false};
  vm.runInContext("selectedTask='TASK-A';",a.context);a.context.api=async(url,options)=>{a.calls.push({url,method:options?.method || 'GET',body:options?.body?JSON.parse(options.body):null});return {...plan};};
  await a.context.preparePreview('TASK-A');assert.equal(a.calls.length,1);assert.equal(a.calls[0].method,'GET');assert.ok(a.calls[0].url.endsWith('/preview-plan'));
  assert.equal(a.node('preview-link').hidden,true);await a.context.startPlatformPreview();assert.equal(a.calls.length,2);
  assert.equal(a.calls[1].body.plan_id,'PLAN-A');assert.equal(a.calls[1].body.expected_candidate_sha256,'sha');assert.equal(a.calls[1].body.configuration_revision,2);assert.equal(a.calls[1].body.confirmed,true);
  assert.equal(a.node('preview-link').href,plan.url);assert.equal(a.node('preview-link').hidden,false);assert.equal(a.node('iw-preview-link').hidden,true);
});
test('the task preview discards a plan that returns after an A-B-A view change',async()=>{
  const a=setup(true);let resolve;vm.runInContext("selectedTask='TASK-A';detailVersion=1;",a.context);a.context.api=()=>new Promise(done=>{resolve=done;});
  const old=a.context.preparePreview('TASK-A');vm.runInContext("selectedTask='TASK-B';detailVersion=2;selectedTask='TASK-A';detailVersion=3;",a.context);
  resolve({task_id:'TASK-A',plan_id:'old',configuration_revision:2,expected_candidate_sha256:'sha',legacy:false});await old;
  assert.equal(a.node('preview-plan-start').disabled,true);assert.equal(a.node('preview-link').hidden,true);
});
