const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const {dom,storage}=require('./web_dom.cjs');

function setup() {
  const ui=dom(),store=storage();
  const context=vm.createContext({document:ui.document,localStorage:store,Date,JSON,Map,
    crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,Event:class{},
    window:{addEventListener(){}}});
  for(const filename of ['drafts.js','initiative_workflow.js'])
    vm.runInContext(fs.readFileSync('workbench_web/'+filename,'utf8'),context);
  context.WorkbenchDrafts.init('runtime-A');
  const message=ui.element('textarea');ui.nodes.set('iw-message',message);
  const answer=ui.element('textarea');answer.dataset.question='需要什么结果？';
  ui.node('iw-answers').append(answer);ui.node('iw-pane-action').append(message,ui.node('iw-answers'));
  for(const [field,host] of [['iw-note','iw-result'],['v0-spec','v0-entry'],['iw-learning-content','iw-learning-candidate']]) {
    const input=ui.element('textarea');ui.nodes.set(field,input);ui.node(host).append(input);
  }
  const data={id:'I1',revision:1,initiative_version:1,project:{id:'P1'},stage:'clarifying',
    document_version:1,active_task_id:'T1',proposal:{questions:['需要什么结果？']}};
  context.initialData=data;
  vm.runInContext("initiativeWorkId='I1';initiativeWork=initialData;",context);
  context.trackWorkflowDrafts(data);
  // Use the real action and draft bindings. Isolate the response renderer so
  // these tests focus on the async request/edit race rather than UI styling.
  context.renderInitiativeWork=next=>{
    context.WorkbenchDrafts.flush();context.rendered=next;
    vm.runInContext('initiativeWork=rendered;',context);
    context.trackWorkflowDrafts(next);
  };
  context.actorName=()=> 'human';
  let resolve,reject,request;
  context.api=(url,options)=>{request={url,body:JSON.parse(options.body)};return new Promise((yes,no)=>{resolve=yes;reject=no;});};
  function type(id,value) {ui.node(id).value=value;ui.listeners.get('input')({target:ui.node(id)});}
  return {context,ui,store,data,answer,type,resolve:value=>resolve(value),reject:error=>reject(error),request:()=>request};
}

test('successful discussion preserves a new message and answer typed while the request is pending',async()=>{
  const a=setup();a.type('iw-message','发送的说明 A');a.answer.value='发送的回答 A';
  const pending=a.context.initiativeWorkAction('discuss',{text:'发送的说明 A / 发送的回答 A'});
  a.type('iw-message','下一次说明 B');a.answer.value='下一次回答 B';
  a.resolve({...a.data,revision:2,document_version:2,stage:'researching'});
  assert.equal(await pending,true);
  assert.equal(a.ui.node('iw-message').value,'下一次说明 B');assert.equal(a.answer.value,'下一次回答 B');
  assert.equal(a.request().body.text,'发送的说明 A / 发送的回答 A');
  const saved=[...a.store.data.values()].map(raw=>JSON.parse(raw));
  assert.ok(saved.some(item=>item.fields.message==='下一次说明 B' && item.fields.answers['需要什么结果？']==='下一次回答 B'));
});

test('unchanged discussion clears the exact submitted draft before the response changes its version',async()=>{
  const a=setup();a.type('iw-message','发送的说明');a.answer.value='发送的回答';
  const pending=a.context.initiativeWorkAction('discuss',{text:'发送的说明 / 发送的回答'});
  a.resolve({...a.data,revision:2,document_version:2,stage:'researching'});
  assert.equal(await pending,true);
  assert.equal(a.ui.node('iw-message').value,'');assert.equal(a.answer.value,'');
  assert.equal(a.store.length,0);
});

test('failed discussion retains new unsent input and its saved draft',async()=>{
  const a=setup();a.type('iw-message','发送的说明');
  const pending=a.context.initiativeWorkAction('discuss',{text:'发送的说明'});
  a.type('iw-message','失败前的新补充');a.reject(new Error('connection lost'));
  assert.equal(await pending,undefined);assert.equal(a.ui.node('iw-message').value,'失败前的新补充');
  assert.match(a.ui.node('iw-error').textContent,/connection lost/);
  assert.ok([...a.store.data.values()].some(raw=>JSON.parse(raw).fields.message==='失败前的新补充'));
});

for(const [action,field,extra] of [
  ['accept','iw-note',{note:'submitted A'}],
  ['v0','v0-spec',{spec_text:'submitted A',confirmed:true}],
  ['learning','iw-learning-content',{fields:{action:'create',candidate:{content:'submitted A'}}}],
]) {
  test(action+' success keeps input changed after submission',async()=>{
    const a=setup();a.type(field,'submitted A');
    const pending=a.context.initiativeWorkAction(action,extra);
    a.type(field,'unsent B');a.resolve({...a.data,revision:2});
    assert.equal(await pending,true);assert.equal(a.ui.node(field).value,'unsent B');
    assert.ok([...a.store.data.values()].some(raw=>JSON.parse(raw).fields[field]==='unsent B'));
  });
}

test('a discussion response after navigation clears only its old submitted record',async()=>{
  const a=setup();a.type('iw-message','旧事项 A');
  const pending=a.context.initiativeWorkAction('discuss',{text:'旧事项 A'});
  a.context.WorkbenchDrafts.detach(['discussion']);
  const next={...a.data,id:'I2',project:{id:'P2'}};a.context.next=next;
  vm.runInContext("initiativeWorkId='I2';initiativeWork=next;",a.context);
  a.ui.node('iw-message').value='';a.context.trackWorkflowDrafts(next);a.type('iw-message','新事项 B');
  a.resolve({...a.data,revision:2,stage:'researching'});await pending;
  assert.equal(vm.runInContext('initiativeWork.id',a.context),'I2');
  assert.equal(a.ui.node('iw-message').value,'新事项 B');
  assert.ok([...a.store.data.keys()].every(key=>!key.includes('"I1","discussion"')));
  assert.ok([...a.store.data.values()].some(raw=>JSON.parse(raw).fields.message==='新事项 B'));
});

test('a failed old request cannot put its failure message into another item',async()=>{
  const a=setup();a.type('iw-message','旧事项 A');
  const pending=a.context.initiativeWorkAction('discuss',{text:'旧事项 A'});
  a.context.next={...a.data,id:'I2'};vm.runInContext("initiativeWorkId='I2';initiativeWork=next;",a.context);
  a.ui.node('iw-error').textContent='当前事项提示';a.reject(new Error('old failed'));await pending;
  assert.doesNotMatch(a.ui.node('iw-error').textContent,/old failed/);
});
