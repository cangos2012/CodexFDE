const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {dom}=require('./web_dom.cjs');
function setup(){const ui=dom(), context=vm.createContext({document:ui.document,initiativeWorkPending:false,iw:id=>ui.node('iw-'+id)});
  vm.runInContext(fs.readFileSync('workbench_web/learning.js','utf8'),context);return {context,...ui};}
function data(id='R1',stage='ready') {return {id:'I1',stage,learning:{assets:[{id:'M1',state:'active',kind:'workflow',version:1,title:'flow',boundary:'scope',history:[],recipe:{parameters:['target']}}],bindings:[],metrics:{}},
  learning_recall:{id,matches:[{id:'M1',title:'flow',version:1,state:'active',content:'instruction',boundary:'scope',reason:'keyword',source:{initiative_id:'A',task_id:'T'}}],conflicts:[],excluded:[]},
  learning_sources:{tasks:[{id:'T1',label:'已验收任务'}],feedback:[{id:'F1',task_id:'T1',label:'已接受反馈'}]}};}
test('polling preserves adoption choices, human reason and recipe parameters',()=>{
  const {context,node}=setup();context.renderLearning(data());const card=node('iw-learning-matches').children[0];
  card.querySelector('[data-choice="adopt"]').value='yes';card.querySelector('[data-choice="reason"]').value='same boundary';card.querySelector('[data-parameter]').value='value.txt';
  context.renderLearning(data());assert.equal(node('iw-learning-matches').children[0],card);
  assert.equal(card.querySelector('[data-choice="reason"]').value,'same boundary');assert.equal(card.querySelector('[data-parameter]').value,'value.txt');
  context.renderLearning(data('R2'));assert.notEqual(node('iw-learning-matches').children[0],card);
  assert.equal(node('iw-learning-matches').children[0].querySelector('[data-choice="adopt"]').value,'');
});
test('checking freezes candidate creation and all adoption controls',()=>{
  const {context,node}=setup();context.renderLearning(data('R1','checking'));
  assert.equal(node('iw-learning-create').disabled,true);assert.equal(node('iw-learning-decide').disabled,true);
  assert.equal(node('iw-learning-matches').children[0].querySelector('[data-choice="reason"]').disabled,true);
});
test('source selects contain only server-provided real sources and matching accepted feedback',()=>{
  const {context,node}=setup();const d=data();d.active_task_id='T1';context.renderLearning(d);
  assert.deepEqual(node('iw-learning-task').children.map(e=>e.value),['','T1']);
  assert.deepEqual(node('iw-learning-feedback').children.map(e=>e.value),['','F1']);
  node('iw-learning-task').value='';node('iw-learning-task').onchange();
  assert.equal(node('iw-learning-feedback').children.length,1);
});
test('recipe defaults fill only empty instructions and leave human edits intact',()=>{
  const {context,node}=setup();context.initLearning();node('iw-learning-kind').value='workflow';node('iw-learning-implement').value='my actual steps';node('iw-learning-kind').onchange();
  assert.match(node('iw-learning-precheck').value,/前置条件/);assert.equal(node('iw-learning-implement').value,'my actual steps');
});
