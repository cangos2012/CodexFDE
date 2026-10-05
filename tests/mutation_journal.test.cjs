const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {dom,storage}=require('./web_dom.cjs');
const operation='/api/v1/initiatives/I1/runtime/subtasks/start',key='SUBMISSION-A';
function setup(store=storage(),runtime='DB-A') {
  const ui=dom(),calls=[];
  const context=vm.createContext({document:ui.document,localStorage:store,Date,URLSearchParams,crypto:require('node:crypto').webcrypto,
    api:async(path,options)=>{calls.push({path,method:options?.method || 'GET'});throw Error('connection lost');}});
  for(const name of ['mutation-journal.js','platform.js'])vm.runInContext(fs.readFileSync('workbench_web/'+name,'utf8'),context);
  context.WorkbenchMutationJournal.init(runtime,store);
  const rows=()=>ui.node('mutation-journal-items').children;
  return {context,...ui,store,calls,rows};
}
function saved(a){return JSON.parse(a.store.getItem('workbench-mutation-journal-v1:DB-A') || '[]');}
test('identity-only journal is durable before a write and never contains signature, authority, body or arguments',async()=>{
  const a=setup();let persistedAtSend;
  a.context.api=async()=>{persistedAtSend=saved(a);throw Error('unknown result');};
  await assert.rejects(a.context.platformPost(operation,{actor:'REAL HUMAN',confirmed:true,submission_key:key,plan_id:'SECRET-PLAN',args:{token:'SECRET TOKEN'}}),/unknown result/);
  assert.equal(persistedAtSend.length,1);assert.deepEqual(Object.keys(persistedAtSend[0]).sort(),['label','operation','runtime_instance','started_at','submission_key']);
  assert.equal(persistedAtSend[0].operation,operation);assert.equal(persistedAtSend[0].submission_key,key);assert.equal(persistedAtSend[0].runtime_instance,'DB-A');
  const raw=[...a.store.data.values()].join('');assert.doesNotMatch(raw,/REAL HUMAN|SECRET|actor|confirmed|plan_id|args|body/);
});
test('reload restores the original key, does not replay, and blocks a replacement write until deliberate reconciliation',async()=>{
  const a=setup();await assert.rejects(a.context.platformPost(operation,{submission_key:key}),/connection lost/);
  const reopened=setup(a.store);assert.equal(reopened.rows().length,1);assert.equal(reopened.calls.length,0);assert.match(reopened.rows()[0].children.find(e=>e.tag==='pre').textContent,/SUBMISSION-A/);
  await assert.rejects(reopened.context.platformPost(operation,{submission_key:'NEW-KEY'}),/本次没有发送新请求/);assert.equal(reopened.calls.length,0);assert.equal(saved(reopened)[0].submission_key,key);
});
test('manual receipt checks are GET only and only confirmed completed/failed can explicitly end a hint',async()=>{
  for(const status of ['pending','completed','failed','not_found']){
    const a=setup();const entry=a.context.WorkbenchMutationJournal.begin(operation,key);a.context.api=async(path,options)=>{a.calls.push({path,method:options?.method || 'GET'});return {operation,key,status,automatic_replay:false};};
    a.context.WorkbenchMutationJournal.finish(entry);assert.equal(saved(a).length,1);
    await a.context.WorkbenchMutationJournal.check(entry);assert.equal(saved(a).length,1);assert.equal(a.calls.length,1);assert.equal(a.calls[0].method,'GET');assert.match(a.calls[0].path,/operation=%2Fapi%2Fv1%2F/);assert.match(a.calls[0].path,/key=SUBMISSION-A/);
    const terminal=['completed','failed'].includes(status);assert.equal(a.rows()[0].children.filter(e=>e.tag==='button')[1].disabled,!terminal);
    a.context.WorkbenchMutationJournal.finish(entry);assert.equal(saved(a).length,terminal ? 0 : 1);assert.equal(a.calls.length,1);assert.match(a.node('mutation-journal-status').textContent,terminal ? /后端请求、授权和验收记录保持原状/ : /结果尚未确认.*原提交键已保留/);
  }
});
test('completed receipt says only that the request was accepted and never declares delivery accepted or complete',async()=>{
  const a=setup();const entry=a.context.WorkbenchMutationJournal.begin(operation,key);a.context.api=async()=>({operation,key,status:'completed',automatic_replay:false});
  await a.context.WorkbenchMutationJournal.check(entry);const rowText=a.rows()[0].children.map(el=>el.textContent).join(' ');assert.match(rowText,/请求已受理/);assert.match(rowText,/这不代表交付完成/);assert.equal(saved(a).length,1);
});
test('mismatched or unreadable receipts cannot unlock ending a hint or silently discard its identity',async()=>{
  const a=setup();const entry=a.context.WorkbenchMutationJournal.begin(operation,key);a.context.api=async()=>({operation,key:'ANOTHER-KEY',status:'completed',automatic_replay:false});
  await a.context.WorkbenchMutationJournal.check(entry);a.context.WorkbenchMutationJournal.finish(entry);assert.equal(saved(a).length,1);assert.equal(a.rows()[0].children.filter(e=>e.tag==='button')[1].disabled,true);assert.match(a.node('mutation-journal-status').textContent,/暂时不可读/);
});
test('runtime isolation and local cleanup change no server request or authorization',()=>{
  const a=setup();a.context.WorkbenchMutationJournal.begin(operation,key);const other=setup(a.store,'DB-B');assert.equal(other.rows().length,0);assert.equal(other.calls.length,0);
  other.context.WorkbenchMutationJournal.clear();assert.equal(saved(a).length,1);const original=setup(a.store);original.context.WorkbenchMutationJournal.clear();assert.equal(saved(original).length,0);assert.equal(original.calls.length,0);
});
test('an intact successful response acknowledges only its own request identity',async()=>{
  const a=setup();a.context.WorkbenchMutationJournal.begin('/api/v1/migration/prepare','OTHER-KEY');a.context.api=async()=>({initiative_id:'I1',status:'queued'});
  await a.context.platformPost(operation,{submission_key:key});assert.deepEqual(saved(a).map(e=>e.submission_key),['OTHER-KEY']);
});
test('storage failure rejects a write before any side effect or automatic fallback',async()=>{
  const broken={getItem:()=>null,setItem(){throw Error('quota');},removeItem(){}};const a=setup(broken);
  await assert.rejects(a.context.platformPost(operation,{submission_key:key}),/本次请求没有发送/);assert.equal(a.calls.length,0);
});

test('only explicitly finishing a checked failed receipt releases its cached key for a new human attempt',async()=>{
  const a=setup(),fields={actor:'fixture-reviewer',root_path:'D:/fixture'},projectOperation='/api/v1/projects';
  const original=a.context.platformKey('project-settings/new',fields),other=a.context.platformKey('project-settings/new',{...fields,root_path:'D:/other'});
  await assert.rejects(a.context.platformPost(projectOperation,{...fields,submission_key:original}),/connection lost/);
  const entry=saved(a)[0];
  a.context.WorkbenchMutationJournal.finish(entry);assert.equal(a.context.platformKey('project-settings/new',fields),original);
  a.context.api=async(path,options)=>{a.calls.push({path,method:options?.method || 'GET'});return {operation:projectOperation,key:original,status:'failed',automatic_replay:false};};
  await a.context.WorkbenchMutationJournal.check(entry);
  assert.equal(a.context.platformKey('project-settings/new',fields),original);assert.equal(saved(a).length,1);
  a.context.WorkbenchMutationJournal.finish(entry);
  assert.equal(saved(a).length,0);assert.notEqual(a.context.platformKey('project-settings/new',fields),original);
  assert.equal(a.context.platformKey('project-settings/new',{...fields,root_path:'D:/other'}),other);
  assert.equal(a.calls.length,2);assert.equal(a.calls[1].method,'GET');
  assert.match(a.node('mutation-journal-status').textContent,/再次点击提交.*新的提交键/);
  assert.doesNotMatch([...a.store.data.values()].join(''),/fixture-reviewer|root_path|D:\/fixture/);
});

test('pending and not_found keep their durable hints and keys while completed ends only its local hint',async()=>{
  for(const status of ['pending','not_found','completed']){
    const a=setup(),fields={actor:'fixture-reviewer',root_path:'D:/fixture'},original=a.context.platformKey('project-settings/new',fields);
    const entry=a.context.WorkbenchMutationJournal.begin('/api/v1/projects',original);
    a.context.api=async(path,options)=>{a.calls.push({path,method:options?.method || 'GET'});return {operation:entry.operation,key:original,status,automatic_replay:false};};
    await a.context.WorkbenchMutationJournal.check(entry);a.context.WorkbenchMutationJournal.finish(entry);
    assert.equal(a.context.platformKey('project-settings/new',fields),original);assert.equal(a.calls.length,1);assert.equal(a.calls[0].method,'GET');
    assert.equal(saved(a).length,status==='completed' ? 0 : 1);
  }
});

test('a failed local end preserves both the hint and cached key even after reading a failed receipt',async()=>{
  const store=storage(),a=setup(store),fields={root_path:'D:/fixture'},original=a.context.platformKey('project-settings/new',fields);
  const entry=a.context.WorkbenchMutationJournal.begin('/api/v1/projects',original);
  a.context.api=async()=>({operation:entry.operation,key:original,status:'failed',automatic_replay:false});
  await a.context.WorkbenchMutationJournal.check(entry);
  store.setItem=()=>{throw Error('quota');};a.context.WorkbenchMutationJournal.finish(entry);
  assert.equal(saved(a).length,1);assert.equal(a.context.platformKey('project-settings/new',fields),original);
  assert.match(a.node('mutation-journal-status').textContent,/原提交键保留/);
});

test('unknown outcomes survive end attempts and page reloads and reject every replacement write before POST',async()=>{
  for(const status of ['pending','not_found','unreadable']){
    const a=setup(),projectOperation='/api/v1/projects',fields={root_path:'D:/fixture/project'};
    const original=a.context.platformKey('project-settings/new',fields),entry=a.context.WorkbenchMutationJournal.begin(projectOperation,original);
    a.context.api=async(path,options)=>{
      a.calls.push({path,method:options?.method || 'GET'});
      if(status==='unreadable')throw Error('receipt unavailable');
      return {operation:projectOperation,key:original,status,automatic_replay:false};
    };
    await a.context.WorkbenchMutationJournal.check(entry);a.context.WorkbenchMutationJournal.finish(entry);
    assert.equal(saved(a).length,1);assert.equal(saved(a)[0].submission_key,original);
    assert.equal(a.rows()[0].children.filter(e=>e.tag==='button')[1].disabled,true);
    for(let reload=0;reload<2;reload++){
      const reopened=setup(a.store),replacement=reopened.context.platformKey('project-settings/new',fields);
      assert.notEqual(replacement,original);assert.equal(reopened.calls.length,0);assert.equal(reopened.rows().length,1);
      await assert.rejects(reopened.context.platformPost(projectOperation,{...fields,submission_key:replacement}),/本次没有发送新请求/);
      reopened.context.WorkbenchMutationJournal.finish(saved(reopened)[0]);
      assert.equal(saved(reopened).length,1);assert.equal(saved(reopened)[0].submission_key,original);assert.equal(reopened.calls.length,0);
    }
    assert.deepEqual(a.calls.map(call=>call.method),['GET']);
    assert.doesNotMatch([...a.store.data.values()].join(''),/root_path|actor|D:\/fixture/);
  }
});
