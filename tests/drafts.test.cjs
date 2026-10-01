const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const {dom,storage}=require('./web_dom.cjs');
function setup(store=storage()) {
  const ui=dom(), events=new Map();
  const context=vm.createContext({document:ui.document,localStorage:store,Date,JSON,Map,crypto:require('node:crypto').webcrypto,
    setTimeout,clearTimeout,Event:class{},window:{addEventListener:(k,v)=>events.set(k,v)}});
  vm.runInContext(fs.readFileSync('workbench_web/drafts.js','utf8'),context);
  const drafts=context.WorkbenchDrafts;drafts.init('runtime-A');
  let fields={message:''};const host=ui.node('host'), input=ui.element('textarea');host.append(input);
  function track(base=1,item='I1',project='P1'){drafts.track('discussion',{project,item,base},()=>fields,v=>fields=v,host);}
  function type(text){fields={message:text};ui.listeners.get('input')({target:input});drafts.flush();}
  return {context,drafts,ui,events,store,track,type,fields:()=>fields,setFields:value=>{fields=value;}};
}
test('refresh offers recovery without submitting and scope prevents mixed drafts',()=>{
  const a=setup();a.track();a.type('未提交回答');
  const b=setup(a.store);b.track();assert.equal(b.fields().message,'');
  b.ui.node('draft-discussion').querySelectorAll('button').find(e=>e.textContent==='恢复草稿').onclick();
  assert.equal(b.fields().message,'未提交回答');
  b.drafts.detach(['discussion']);b.track(1,'I2');assert.equal(b.ui.node('draft-discussion').children.length,0);
  b.drafts.init('runtime-B');b.track();assert.equal(b.ui.node('draft-discussion').children.length,0);
});
test('changed version exposes old content without overwriting current contract',()=>{
  const a=setup();a.track();a.type('旧回答');const b=setup(a.store);b.track(2);
  assert.equal(b.fields().message,'');assert.equal(b.ui.node('draft-discussion').querySelectorAll('button').some(e=>e.textContent==='恢复草稿'),false);
  assert.match(b.ui.node('draft-discussion').querySelectorAll('p')[0].textContent,/旧版本/);
});
test('uncertain submission keeps stable key across reload and success clears it',()=>{
  const a=setup();a.track();a.type('new item');const key=a.drafts.submissionKey('discussion');
  const b=setup(a.store);b.track();assert.equal(b.drafts.submissionKey('discussion'),key);
  b.drafts.clear('discussion');b.events.get('pagehide')();assert.equal(b.store.length,0);
});
test('quota failure keeps input and reports unsaved draft',()=>{
  const a=setup();a.track();a.store.setItem=()=>{throw Error('quota');};a.type('keep this');
  assert.equal(a.fields().message,'keep this');assert.match(a.ui.node('draft-status').textContent,/未保存.*quota/);
});
test('expired drafts are removed; corrupt drafts remain available for explicit cleanup',()=>{
  const a=setup();a.track();a.type('old');const k=a.store.key(0), saved=JSON.parse(a.store.getItem(k));saved.saved_at=0;
  a.store.setItem(k,JSON.stringify(saved));a.drafts.init('runtime-A');assert.equal(a.store.length,0);
  a.store.setItem('workbench-draft-v1:broken','{');a.drafts.init('runtime-A');assert.equal(a.store.length,1);
  a.drafts.clearAll();assert.equal(a.store.length,0);
});
test('switching flushes the old input before binding another form',()=>{
  const a=setup();a.track();a.type('A text');a.drafts.detach(['discussion']);a.track(1,'I2');a.type('B text');
  const b=setup(a.store);b.track();b.ui.node('draft-discussion').querySelectorAll('button').find(e=>e.textContent==='恢复草稿').onclick();
  assert.equal(b.fields().message,'A text');
});
test('restore leaves disabled fields and signer untouched',()=>{
  const a=setup();a.ui.node('init-goal').disabled=true;a.ui.node('init-goal').value='confirmed';
  a.context.restoreDraftFields({'init-goal':'old'});assert.equal(a.ui.node('init-goal').value,'confirmed');
  assert.ok(!fs.readFileSync('workbench_web/drafts.js','utf8').includes("'task-actor'"));
});

test('new version writes retain previous drafts and success clears only the submitted version',()=>{
  const a=setup();a.track(1);a.type('旧判断');
  const oldKey=a.store.key(0);
  a.track(2);a.type('新判断');
  assert.equal(a.store.length,2);
  assert.equal(JSON.parse(a.store.getItem(oldKey)).fields.message,'旧判断');
  const b=setup(a.store);b.track(2);
  const restore=b.ui.node('draft-discussion').querySelectorAll('button').filter(e=>e.textContent==='恢复草稿');
  assert.equal(restore.length,1);restore[0].onclick();assert.equal(b.fields().message,'新判断');
  assert.match(b.ui.node('draft-discussion').querySelectorAll('pre')[0].textContent,/旧判断/);
  b.drafts.clear('discussion');
  assert.equal(b.store.length,1);
  assert.equal(JSON.parse(b.store.getItem(oldKey)).fields.message,'旧判断');
  assert.equal(b.ui.node('draft-discussion').querySelectorAll('button').some(e=>e.textContent==='恢复草稿'),false);
  assert.match(b.ui.node('draft-discussion').querySelectorAll('pre')[0].textContent,/旧判断/);
});

test('storage disabled still retains an in-memory submission key for an uncertain retry',()=>{
  const blocked={get length(){throw Error('storage disabled');}};
  const a=setup(blocked);a.track();a.type('待提交需求');
  const key=a.drafts.submissionKey('discussion');
  assert.equal(typeof key,'string');assert.ok(key.length>0);
  assert.equal(a.drafts.submissionKey('discussion'),key);
  a.track();assert.equal(a.drafts.submissionKey('discussion'),key);
  assert.equal(a.fields().message,'待提交需求');
  assert.match(a.ui.node('draft-status').textContent,/仅留在当前页面/);
  a.drafts.clear('discussion');assert.notEqual(a.drafts.submissionKey('discussion'),key);
});

test('maximum keeps 100 valid drafts and always retains the latest write',()=>{
  const a=setup();
  for(let version=1;version<=105;version++) {a.track(version);a.type('v'+version);}
  assert.equal(a.store.length,100);
  assert.ok([...a.store.data.values()].some(raw=>JSON.parse(raw).fields.message==='v105'));
  const other=setup(a.store);other.track(105);
  other.ui.node('draft-discussion').querySelectorAll('button').find(e=>e.textContent==='恢复草稿').onclick();
  assert.equal(other.fields().message,'v105');
});

test('successful submission leaves text written while awaiting its response as a draft',()=>{
  const a=setup();a.track();a.type('submitted A');
  const submitted=a.drafts.capture('discussion');
  a.type('new unsent B');let resets=0;
  assert.equal(a.drafts.clearSubmitted(submitted,()=>{resets++;}),false);
  assert.equal(resets,0);assert.equal(a.fields().message,'new unsent B');
  assert.equal(JSON.parse(a.store.getItem(a.store.key(0))).fields.message,'new unsent B');
});

test('successful unchanged submission resets editable input and deletes its exact draft version',()=>{
  const a=setup();a.track(1);a.type('old unsent version');
  a.track(2);a.type('submitted version');const submitted=a.drafts.capture('discussion');
  assert.equal(a.drafts.clearSubmitted(submitted,()=>a.setFields({message:''})),true);
  assert.equal(a.fields().message,'');assert.equal(a.store.length,1);
  assert.equal(JSON.parse(a.store.getItem(a.store.key(0))).fields.message,'old unsent version');
  a.events.get('pagehide')();assert.equal(a.store.length,1);
  a.type('submitted version');assert.equal(a.store.length,2);
});

test('response after binding a newer version deletes only the submitted older record',()=>{
  const a=setup();a.track(1);a.type('submitted A');const submitted=a.drafts.capture('discussion');
  a.track(2);a.type('new version B');let reset=false;
  assert.equal(a.drafts.clearSubmitted(submitted,()=>{reset=true;}),false);
  assert.equal(reset,false);assert.equal(a.store.length,1);
  assert.equal(JSON.parse(a.store.getItem(a.store.key(0))).base,'2');
  assert.equal(a.fields().message,'new version B');
});
