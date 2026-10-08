const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const {dom,storage}=require('./web_dom.cjs');

function setup() {
  const ui=dom(),store=storage();
  const context=vm.createContext({document:ui.document,localStorage:store,Date,JSON,Map,
    crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,Event:class{},window:{addEventListener(){}}});
  for(const field of ['title','raw','metric','source','problem','goal','nongoals','acceptance','evidence','area','reviewer','project']) {
    const node=ui.element(field==='project' || field==='area' ? 'select' : 'input');
    ui.nodes.set('init-'+field,node);ui.node('initiative-form').append(node);
  }
  ui.node('init-project').value='P1';
  for(const filename of ['drafts.js','initiatives.js'])vm.runInContext(fs.readFileSync('workbench_web/'+filename,'utf8'),context);
  context.WorkbenchDrafts.init('runtime');
  context.showInitiativeWork=()=>{};context.loadInitiativeProjects=async()=>{};
  context.refreshInitiatives=async()=>true;context.actorName=()=> 'human';
  context.show=(id,value)=>{ui.node(id).textContent=value;};
  const pending=[];
  context.api=(url,options)=>new Promise((resolve,reject)=>pending.push({url,body:JSON.parse(options.body),resolve,reject}));
  context.showInitiative(null);
  function type(field,value) {ui.node('init-'+field).value=value;ui.listeners.get('input')({target:ui.node('init-'+field)});}
  function item(id,title,version=1) {
    return {id,title,version,project_id:'P1',status:'investigating',decision:null,raw_signal:'原始输入',source:'test',
      goal:'目标',non_goals:[],acceptance:[],evidence:[],affected_areas:[],reviewer:'',
      readiness:{decision_missing:[],delivery_missing:[]}};
  }
  return {context,ui,store,pending,type,item,save:()=>context.saveInitiative({preventDefault(){}})};
}

test('contract save freezes editable fields, clears confirmed draft and keeps saved identity locks',async()=>{
  const a=setup();a.type('title','需求 A');a.type('raw','原始输入');
  const pending=a.save();
  assert.equal(a.pending.length,1);
  assert.ok(a.ui.node('initiative-form').querySelectorAll('input,select,textarea').every(node=>node.disabled));
  a.pending[0].resolve(a.item('I1','需求 A'));await pending;
  assert.equal(a.ui.node('init-title').disabled,true);assert.equal(a.ui.node('init-raw').disabled,true);
  assert.equal(a.ui.node('init-project').disabled,true);assert.equal(a.ui.node('init-source').disabled,false);
  assert.equal(a.ui.node('save-initiative').disabled,false);assert.equal(a.store.length,0);
});

test('uncertain failure restores previous control states and reuses the same submission key',async()=>{
  const a=setup();a.type('title','需求 A');a.type('raw','原始输入');a.ui.node('init-area').disabled=true;
  const first=a.save();const key=a.pending[0].body.submission_key;
  a.pending[0].reject(new Error('response lost'));await first;
  assert.equal(a.ui.node('init-title').disabled,false);assert.equal(a.ui.node('init-area').disabled,true);
  assert.equal(a.ui.node('init-title').value,'需求 A');assert.match(a.ui.node('initiative-status').textContent,/response lost/);
  assert.ok(a.store.length>0);
  const retry=a.save();assert.equal(a.pending[1].body.submission_key,key);
  a.pending[1].resolve(a.item('I1','需求 A'));await retry;
  assert.equal(a.store.length,0);
});

test('an older save cannot replace another editor or unlock its in-flight controls',async()=>{
  const a=setup();a.context.showInitiative(a.item('I1','事项 A'));
  a.type('goal','A 的修订');const old=a.save();
  a.context.showInitiative(a.item('I2','事项 B'));a.type('goal','B 的修订');const current=a.save();
  a.pending[0].resolve(a.item('I1','事项 A',2));await old;
  assert.equal(vm.runInContext('currentInitiative.id',a.context),'I2');
  assert.equal(a.ui.node('init-goal').value,'B 的修订');assert.equal(a.ui.node('save-initiative').disabled,true);
  assert.equal(a.ui.node('init-source').disabled,true);
  assert.ok([...a.store.data.keys()].every(key=>!key.includes('"I1"')));
  a.pending[1].resolve(a.item('I2','事项 B',2));await current;
  assert.equal(vm.runInContext('currentInitiative.id',a.context),'I2');
  assert.equal(a.ui.node('save-initiative').disabled,false);assert.equal(a.ui.node('init-source').disabled,false);
});
