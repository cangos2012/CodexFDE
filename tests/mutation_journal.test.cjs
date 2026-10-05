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
test('manual receipt checks are GET only and pending, failed and not_found hints require a separate explicit end',async()=>{
  for(const status of ['pending','failed','not_found']){
    const a=setup();const entry=a.context.WorkbenchMutationJournal.begin(operation,key);a.context.api=async(path,options)=>{a.calls.push({path,method:options?.method || 'GET'});return {operation,key,status,automatic_replay:false};};
    a.context.WorkbenchMutationJournal.finish(entry);assert.equal(saved(a).length,1);
    await a.context.WorkbenchMutationJournal.check(entry);assert.equal(saved(a).length,1);assert.equal(a.calls.length,1);assert.equal(a.calls[0].method,'GET');assert.match(a.calls[0].path,/operation=%2Fapi%2Fv1%2F/);assert.match(a.calls[0].path,/key=SUBMISSION-A/);
    a.context.WorkbenchMutationJournal.finish(entry);assert.equal(saved(a).length,0);assert.equal(a.calls.length,1);assert.match(a.node('mutation-journal-status').textContent,/后端请求、授权和验收记录保持原状/);
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
