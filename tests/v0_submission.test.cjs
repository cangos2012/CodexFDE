const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {dom}=require('./web_dom.cjs');
function setup(){const ui=dom(),calls=[],context=vm.createContext({document:ui.document,TextEncoder,encodeURIComponent,
  setInterval:()=>1,clearInterval(){},actorName:()=> 'fixture',api:async(url,options)=>{calls.push({url,options});return {id:'I1',stage:'queued',revision:2};}});
  vm.runInContext(fs.readFileSync('workbench_web/initiative_workflow.js','utf8'),context);
  context.renderInitiativeWork=()=>{};context.refreshInitiativeWork=()=>{};
  vm.runInContext("initiativeWork={id:'I1',stage:'idle',revision:0};initiativeWorkId='I1';",context);
  context.initInitiativeWork();ui.node('task-actor').value='fixture';ui.node('v0-confirmed').checked=true;
  ui.node('v0-mode').value='verify';ui.node('v0-timeout').value=900;
  return {context,calls,...ui};}
test('Unicode character count accepts supplementary characters and clears only successful confirmation',async()=>{
  const {node,calls}=setup();node('v0-spec').value='😀'.repeat(24000);
  await node('v0-submit').onclick();assert.equal(calls.length,1);assert.equal(node('v0-confirmed').checked,false);
  assert.equal([...JSON.parse(calls[0].options.body).spec_text].length,24000);
});
test('oversized text or UTF8 request retains input without sending',async()=>{
  const {node,calls}=setup();node('v0-spec').value='中'.repeat(24001);await node('v0-submit').onclick();
  assert.equal(calls.length,0);assert.match(node('v0-status').textContent,/24,000/);assert.equal(node('v0-spec').value.length,24001);
  node('v0-spec').value='ok';node('v0-files').value='中'.repeat(180000);await node('v0-submit').onclick();
  assert.equal(calls.length,0);assert.match(node('v0-status').textContent,/512 KiB/);
});
test('failed submission preserves text and requires manual confirmation on another item',async()=>{
  const {context,node}=setup();context.api=async()=>{throw Error('offline');};node('v0-spec').value='keep contract';
  await node('v0-submit').onclick();assert.equal(node('v0-spec').value,'keep contract');assert.equal(node('v0-confirmed').checked,true);
  context.showInitiativeWork({id:'I2',reviewer:''});assert.equal(node('v0-confirmed').checked,false);assert.equal(node('v0-spec').value,'');
  assert.equal(node('iw-learning-content').value,'');
});
