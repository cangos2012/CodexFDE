const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {dom,storage}=require('./web_dom.cjs');

function setup(failPath='/api/health') {
  const ui=dom(),store=storage(),calls=[],listeners=new Map(),initializers={initiatives:0,home:0};
  for(const match of fs.readFileSync('workbench_web/index.html','utf8').matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const el=ui.element(match[1]);el.hidden=/\bhidden\b/.test(match[2]);el.disabled=/\bdisabled\b/.test(match[2]);ui.nodes.set(match[3],el);
  }
  const get=ui.document.getElementById;
  ui.document.getElementById=id=>{const el=get(id);el.focus=()=>{};el.addEventListener=(type,fn)=>{
    const key=id+':'+type;if(!listeners.has(key))listeners.set(key,[]);listeners.get(key).push(fn);
  };return el;};
  ui.document.querySelector=selector=>ui.node(selector);
  ui.node('initiative-form').append(ui.node('init-title'));
  let failed=false,service='service-A',runtime='runtime-A',holdHealth=null;
  const context=vm.createContext({document:ui.document,localStorage:store,Date,Headers,AbortController,
    crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,Event:class{},window:{addEventListener(){}},currentInitiative:null,
    fetch:async(url,options)=>{
      calls.push({url,method:options.method || 'GET'});
      if(url===failPath && !failed){failed=true;throw Error('fixture initial read offline');}
      if(url==='/api/health' && holdHealth)await holdHealth;
      const bodies={
        '/api/health':{surface:'workbench',runtime_instance:runtime},
        '/api/v1/delivery/capabilities':{web_code_execution:true,code_readiness:{ready:true,message:'fixture capability; no execution'}},
        '/api/course/current':{},'/api/cockpit/upgrade':{},'/api/v1/delivery/views?limit=20':{items:[]},
      };
      if(!Object.hasOwn(bodies,url))throw Error('unexpected fixture request '+url);
      return {ok:true,headers:new Headers({'X-Workbench-Service-Instance':service,'X-Workbench-Runtime-Instance':runtime}),json:async()=>bodies[url]};
    }});
  vm.runInContext(fs.readFileSync('workbench_web/drafts.js','utf8'),context);
  vm.runInContext(fs.readFileSync('workbench_web/app.js','utf8').replace(/boot\(\);\s*$/,''),context);
  context.initInitiatives=()=>{++initializers.initiatives;};context.initProjectHome=()=>{++initializers.home;};
  context.renderContract=()=>{};context.renderUpgrade=()=>{};
  context.refreshTasks=()=>context.api('/api/v1/delivery/views?limit=20');
  context.refreshProjectHome=async()=>{};context.refreshInitiatives=async()=>{};context.refreshInitiativeWork=async()=>{};
  context.trackInitiativeDraft=()=>context.WorkbenchDrafts.track('initiative',{project:'P1',item:'new',base:null},
    ()=>({title:ui.node('init-title').value}),fields=>ui.node('init-title').value=fields.title,ui.node('initiative-form'));
  const type=(id,value)=>{ui.node(id).value=value;ui.listeners.get('input')({target:ui.node(id)});};
  return {...ui,context,store,calls,listeners,initializers,type,
    identity:(s,r=runtime)=>{service=s;runtime=r;},
    hold:promise=>holdHealth=promise};
}

test('refresh repairs a failed first health read and shares concurrent startup reads',async()=>{
  const a=setup();await a.context.boot();a.type('task-actor','fixture human');a.type('iw-note','unsubmitted human draft');
  await Promise.all([a.node('refresh-tasks').onclick(),a.node('refresh-tasks').onclick()]);
  assert.equal(a.calls.filter(c=>c.url==='/api/health').length,2);
  assert.equal(a.calls.filter(c=>c.url==='/api/v1/delivery/capabilities').length,1);
  assert.equal(a.calls.filter(c=>c.url==='/api/v1/delivery/views?limit=20').length,1);
  assert.equal(vm.runInContext('webCodeAvailable',a.context),true);assert.equal(a.node('mode-codex').disabled,false);
  assert.ok(a.context.WorkbenchDrafts.capture('initiative'));assert.ok(a.context.WorkbenchDrafts.submissionKey('initiative'));
  assert.equal(a.node('task-actor').value,'fixture human');assert.equal(a.node('iw-note').value,'unsubmitted human draft');
  assert.equal(a.initializers.initiatives,1);assert.equal(a.initializers.home,1);
  assert.equal(a.listeners.get('task-lesson:change').length,1);
  assert.equal(a.calls.filter(c=>c.method!=='GET').length,0);
  assert.equal([...a.store.data.values()].some(value=>value.includes('fixture human')),false);
});

test('a capability retry preserves already bound draft input and initializes events once',async()=>{
  const a=setup('/api/v1/delivery/capabilities');await a.context.boot();a.type('init-title','my unfinished requirement');a.context.WorkbenchDrafts.flush();
  a.type('task-actor','fixture reviewer');await a.node('refresh-tasks').onclick();
  assert.equal(vm.runInContext('webCodeAvailable',a.context),true);assert.equal(a.node('init-title').value,'my unfinished requirement');
  assert.equal(a.context.WorkbenchDrafts.capture('initiative').encoded,JSON.stringify({title:'my unfinished requirement'}));
  assert.equal(a.node('task-actor').value,'fixture reviewer');assert.equal(a.listeners.get('task-lesson:change').length,1);
  assert.equal(a.calls.filter(c=>c.method!=='GET').length,0);
});

test('an incomplete startup blocks writes until a deliberate readonly recovery succeeds',async()=>{
  const a=setup();await a.context.boot();
  await assert.rejects(a.context.api('/api/v1/initiatives/I1/workflow/execute',{method:'POST'}),/初始化|冻结/);
  assert.equal(a.calls.filter(c=>c.method!=='GET').length,0);
  await a.node('refresh-tasks').onclick();assert.equal(a.context.workbenchWritesFrozen(),false);
});

test('service changes during initialization recovery keep writes frozen and preserve input',async()=>{
  const a=setup('/api/v1/delivery/capabilities');await a.context.boot();a.type('init-title','kept draft');a.context.WorkbenchDrafts.flush();
  a.type('task-actor','fixture reviewer');a.identity('service-B');await a.node('refresh-tasks').onclick();
  assert.equal(a.context.workbenchWritesFrozen(),true);assert.equal(a.node('iw-execute').disabled,true);
  assert.match(a.node('service-identity-status').textContent,/重新载入/);assert.equal(a.node('init-title').value,'kept draft');
  assert.equal(a.node('task-actor').value,'fixture reviewer');assert.equal(a.calls.filter(c=>c.method!=='GET').length,0);
  assert.equal(vm.runInContext('workbenchServiceIdentity.service',a.context),'service-A');
});

test('a manual refresh during a pending initial boot shares its startup promise',async()=>{
  const a=setup('never-fail');let release;a.hold(new Promise(resolve=>release=resolve));
  let refreshed=false;
  const boot=a.context.boot(),refresh1=Promise.resolve(a.node('refresh-tasks').onclick()).then(()=>refreshed=true),refresh2=a.node('refresh-tasks').onclick();
  await new Promise(resolve=>setImmediate(resolve));assert.equal(refreshed,false);
  assert.equal(a.calls.filter(c=>c.url==='/api/health').length,1);release();await Promise.all([boot,refresh1,refresh2]);
  assert.equal(a.calls.filter(c=>c.url==='/api/health').length,1);assert.equal(a.calls.filter(c=>c.url==='/api/v1/delivery/capabilities').length,1);
  assert.equal(a.calls.filter(c=>c.url==='/api/v1/delivery/views?limit=20').length,1);
  assert.equal(a.initializers.initiatives,1);assert.equal(a.listeners.get('task-lesson:change').length,1);
});

for(const mode of ['verify','codex'])test('startup releases current '+mode+' task controls while preserving its approval gate',async()=>{
  const a=setup('never-fail');
  a.context.fixtureDetail={task_id:'TASK-FIXTURE',allowed_actions:['approve','reject'],policy:{execution_mode:mode},events:[]};
  a.context.refreshTasks=async()=>{
    await a.context.api('/api/v1/delivery/views?limit=20');
    vm.runInContext('selectedTask=fixtureDetail.task_id;taskCache=[fixtureDetail];',a.context);
    a.context.renderActions(a.context.fixtureDetail);
    a.node('task-detail').hidden=false;
    assert.equal(a.node('action-approve').disabled,true);
  };
  await a.context.boot();
  assert.equal(a.node('action-approve').disabled,false);assert.equal(a.node('action-reject').disabled,false);
  assert.equal(a.node('action-approve').hidden,mode==='codex');
  assert.equal(a.calls.filter(c=>c.method!=='GET').length,0);
});

test('successful startup cannot enable review from a list row whose detail failed to load',async()=>{
  const a=setup('never-fail');
  a.context.fixtureDetail={task_id:'TASK-FIXTURE',allowed_actions:['approve'],events:[]};
  a.context.refreshTasks=async()=>{
    await a.context.api('/api/v1/delivery/views?limit=20');
    vm.runInContext('selectedTask=fixtureDetail.task_id;taskCache=[fixtureDetail];',a.context);
    a.context.clearEvidence('fixture failed detail read');
  };
  await a.context.boot();
  assert.equal(a.context.workbenchWritesFrozen(),false);
  assert.equal(a.node('task-detail').hidden,true);assert.equal(a.node('action-approve').disabled,true);
  assert.equal(a.calls.filter(c=>c.method!=='GET').length,0);
});
