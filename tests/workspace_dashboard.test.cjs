const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
  const nodes = new Map();
  function element(tag) {
    return {tag, hidden:false, disabled:false, value:'', textContent:'', dataset:{}, children:[],
      classList:{toggle() {}}, setAttribute() {}, removeAttribute() {},
      append(...children) {this.children.push(...children);},
      appendChild(child) {this.children.push(child);}, replaceChildren(...children) {this.children=children;}};
  }
  const document = {createElement:element, getElementById(id) {
    if(!nodes.has(id)) nodes.set(id,element('div'));return nodes.get(id);
  }, querySelectorAll() {return [];}, querySelector(selector) {return this.getElementById(selector);}};
  const context=vm.createContext({document,Date});
  for(const name of ['workspace-dashboard.js','initiative_workflow.js'])
    vm.runInContext(fs.readFileSync(path.join(__dirname,'../workbench_web',name),'utf8'),context);
  return {context,node:id=>document.getElementById(id)};
}
function workflow(stage) {
  return {id:'I1',stage,enabled:true,messages:[],iterations:[],documents:[],progress:[],
    proposal:{goal:'goal',acceptance:[],non_goals:[],sources:[],write_scope:[],steps:[],questions:['Which scope?']}};
}

test('Eval panel distinguishes warning, stale evidence, running and failed attempts',()=>{
  const {context,node}=setup();
  const work=workflow('review');
  work.task={id:'T1',status:'review',events:[]};
  work.eval_harness={available:true,can_run:true,freshness:'current',
    summary:{decision:'pass',passed:1,total:2,blocking_failed:0,observing_failed:1},
    results:[{name:'help',level:'observing',passed:false,duration_ms:3,evidence:'<script>not executable</script>'}]};
  context.renderInitiativeWork(work);
  assert.match(node('iw-eval-summary').textContent,/观察告警 1/);
  assert.match(node('iw-eval-results').children[0].children[0].textContent,/观察.*3 ms/);
  assert.equal(node('iw-eval-results').children[0].children[1].textContent,'<script>not executable</script>');
  work.eval_harness.freshness='stale';
  context.renderInitiativeWork(work);
  assert.equal(node('iw-accept').disabled,true);
  assert.match(node('iw-eval-source').textContent,/旧结论不可用于验收/);
  work.stage='checking';
  context.renderInitiativeWork(work);
  assert.equal(node('iw-eval-run').disabled,true);
  assert.equal(node('iw-accept').hidden,true);
  assert.equal(node('iw-pane-result').hidden,false);
  work.stage='failed';work.eval_harness={available:false,error:'invalid report'};
  context.renderInitiativeWork(work);
  assert.match(node('iw-eval-summary').textContent,/未形成可信报告/);
  assert.equal(node('iw-eval-results').children.length,0);
});
test('failed, interrupted and unreadable work never appears as an outcome',()=>{
  const {context}=setup();
  for(const stage of ['failed','interrupted','cancelled','rework','unavailable'])
    assert.notEqual(context.deliveryStageView(stage).group,'outcome');
  assert.equal(context.deliveryStageView('unavailable').step,-1);
  assert.equal(context.deliveryStageView('review').pane,'result');
  assert.equal(context.deliveryStageView('confirmed').pane,'plan');
});
test('research allows a draft while preventing another submission and hiding stale plans',()=>{
  const {context,node}=setup();
  node('iw-message').value='unsent feedback';
  context.renderInitiativeWork(workflow('researching'));
  assert.equal(node('iw-discuss').disabled,true);
  assert.equal(node('iw-message').disabled,false);
  assert.equal(node('iw-message').value,'unsent feedback');
  assert.equal(node('iw-cancel').hidden,false);
  assert.equal(node('iw-proposal').hidden,true);
  assert.match(node('iw-discuss').textContent,/调研/);
});
test('polling preserves a chosen pane and stage changes lead to the new decision',()=>{
  const {context,node}=setup();
  context.renderInitiativeWork(workflow('clarifying'));
  context.selectIwPane('result');
  context.renderInitiativeWork(workflow('clarifying'));
  assert.equal(node('iw-pane-result').hidden,false);
  context.renderInitiativeWork(workflow('ready'));
  assert.equal(node('iw-pane-plan').hidden,false);
});
test('home excludes course simulations until explicitly included',()=>{
  const {context,node}=setup();
  context.show=(id,value)=>{node(id).textContent=value;};
  node('home-project').value='all';
  vm.runInContext(`homeRows=[
    {item:{id:'real',title:'真实需求'},work:{},view:deliveryStageView('clarifying')},
    {item:{id:'mock',title:'[Mock课程演示] 已完成'},work:{},view:deliveryStageView('observed')}
  ];`,context);
  context.renderProjectHome();
  assert.equal(node('home-attention').textContent,1);
  assert.equal(node('home-outcome').textContent,0);
  node('home-include-mock').checked=true;
  context.renderProjectHome();
  assert.equal(node('home-outcome').textContent,1);
  assert.match(node('home-status').textContent,/含演示/);
});

test('cleared cards stay hidden until requested and running cards cannot be cleared',()=>{
  const {context,node}=setup();
  context.show=(id,value)=>{node(id).textContent=value;};
  node('home-project').value='all';
  vm.runInContext(`homeRows=[
    {item:{id:'old',title:'old',home_hidden:1},work:{},view:deliveryStageView('failed')},
    {item:{id:'active',title:'active'},work:{},view:deliveryStageView('executing')}
  ];homeFilter='all';`,context);
  context.renderProjectHome();
  assert.equal(node('home-items').children.length,1);
  assert.equal(node('home-items').children[0].children[3].children[2].disabled,true);
  node('home-include-cleared').checked=true;
  context.renderProjectHome();
  assert.equal(node('home-items').children.length,2);
  assert.equal(node('home-items').children[0].children[3].children[2].textContent,'恢复到首页');
});

test('old service and request failures explain the problem beside the clicked card',async()=>{
  const {context}=setup();
  let calls=0;
  context.api=async()=>{calls++;throw new Error('network unavailable');};
  context.actorName=()=> 'tester';
  const notice={textContent:''},button={disabled:false};
  await context.setHomeCleared({item:{id:'old'}},button,notice);
  assert.equal(calls,0);
  assert.match(notice.textContent,/重启 8001/);
  await context.setHomeCleared({item:{id:'new',home_hidden:0,version:1}},button,notice);
  assert.equal(calls,1);
  assert.match(notice.textContent,/network unavailable/);
  assert.equal(button.disabled,false);
  assert.match(vm.runInContext("homeClearNotices.get('new')",context),/network unavailable/);
});

test('candidate inspection uses a top-level link without a blocked cross-origin frame',async()=>{
  const {context,node}=setup();
  context.actorName=()=> 'automated test';
  context.api=async()=>({url:'http://127.0.0.1:51053/',notice:'独立测试数据'});
  const work=workflow('review');
  work.task={id:'TASK-TEST',status:'review',events:[]};
  context.renderInitiativeWork(work);
  context.initInitiativeWork();
  await node('iw-preview').onclick();
  assert.equal(node('iw-preview-frame').hidden,true);
  assert.equal(node('iw-preview-link').hidden,false);
  assert.equal(node('iw-preview-link').href,'http://127.0.0.1:51053/');
  assert.match(node('iw-preview-status').textContent,/独立窗口/);
});
