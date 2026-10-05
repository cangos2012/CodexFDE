const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function setup({journal=false}={}){
  const nodes=new Map();
  const element=tag=>({tag,value:'',textContent:'',checked:false,disabled:false,hidden:false,children:[],
    append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},
    querySelectorAll(tag){return this.children.flatMap(el=>el.tag===tag?[el]:el.querySelectorAll(tag));},
    scrollIntoView(){},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;}});
  const document={createElement:element,getElementById(id){if(!nodes.has(id))nodes.set(id,element('div'));return nodes.get(id);}};
  const calls=[];
  const store=require('./web_dom.cjs').storage();
  const context=vm.createContext({document,console,encodeURIComponent,Date,URLSearchParams,crypto:require('node:crypto').webcrypto,localStorage:store,actorName:()=> 'fixture-user',
    show:(id,text)=>document.getElementById(id).textContent=text,workspaceView:()=>{},api:async(url,options)=>{
      calls.push({url,body:JSON.parse(options.body)});
      return {id:'PROJECT-NEW',name:'项目',root_path:'D:/projects/new',eval_command:[]};
    }});
  if(journal){
    for(const name of ['mutation-journal.js','platform.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../workbench_web/'+name),'utf8'),context);
    context.WorkbenchMutationJournal.init('REGISTRATION-FIXTURE',store);
  }
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../workbench_web/initiatives.js'),'utf8'),context);
  context.loadInitiativeProjects=async()=>{};
  context.editRegisteredProject();
  return {context,document,calls,nodes,store};
}

test('local folder is submitted without requiring an Eval command',async()=>{
  const {context,document,calls}=setup();
  document.getElementById('project-name').value='客户系统';
  document.getElementById('project-root').value='D:/projects/new';
  document.getElementById('project-init').checked=true;
  document.getElementById('project-default').checked=true;
  await document.getElementById('project-register').onclick();
  assert.equal(calls[0].url,'/api/v1/projects');
  assert.deepEqual(calls[0].body.eval_command,[]);
  assert.equal(calls[0].body.initialize_git,true);
  assert.equal(calls[0].body.make_default,true);
  assert.equal(document.getElementById('init-project').value,'PROJECT-NEW');
  assert.match(document.getElementById('project-status').textContent,/可以开始调研/);
});

test('home opens an add dialog after editing a project and closes without changing the item',()=>{
  const {context,document}=setup();
  context.editRegisteredProject({id:'EXISTING',name:'ERP',root_path:'D:/erp',eval_command:[]});
  document.getElementById('open-project-registration').onclick();
  assert.equal(document.getElementById('project-dialog').open,true);
  assert.equal(document.getElementById('project-name').value,'');
  assert.equal(document.getElementById('project-root').disabled,false);
  assert.equal(document.getElementById('project-name').focused,true);
  document.getElementById('close-project-registration').onclick();
  assert.equal(document.getElementById('project-dialog').open,false);
});

test('Git source switches fields, sends URL and target, and invalid config sends no request',async()=>{
  const {context,document,calls}=setup();
  document.getElementById('project-source').value='git';context.projectSourceView();
  assert.equal(document.getElementById('project-url-field').hidden,false);
  assert.equal(document.getElementById('project-init-field').hidden,true);
  document.getElementById('project-url').value='https://example.org/repo.git';
  document.getElementById('project-root').value='D:/projects/new';
  document.getElementById('project-eval').value='not JSON';
  await document.getElementById('project-register').onclick();assert.equal(calls.length,0);
  document.getElementById('project-eval').value='';
  await document.getElementById('project-register').onclick();
  assert.equal(calls[0].body.git_url,'https://example.org/repo.git');
  assert.equal(calls[0].body.source_type,'git');
  assert.equal(calls[0].body.root_path,'D:/projects/new');
});

test('configuring existing project uses settings endpoint and locks its repository',async()=>{
  const {context,document,calls}=setup();
  context.editRegisteredProject({id:'PROJECT-EXISTING',name:'ERP',root_path:'D:/erp',eval_command:[]});
  assert.equal(document.getElementById('project-root').disabled,true);
  document.getElementById('project-eval').value='["D:/erp/.venv/Scripts/python.exe","check.py"]';
  await document.getElementById('project-register').onclick();
  assert.equal(calls[0].url,'/api/v1/projects/PROJECT-EXISTING/settings');
  assert.equal(document.getElementById('project-root').disabled,true);
  assert.equal(document.getElementById('project-eval').disabled,false);
});

test('an older running backend cannot receive unsupported registration requests',async()=>{
  const {context,document,calls}=setup();
  context.renderRegisteredProjects({items:[],default_project:'old'});
  assert.equal(document.getElementById('project-register').disabled,true);
  await document.getElementById('project-register').onclick();
  assert.equal(calls.length,0);
  assert.match(document.getElementById('project-status').textContent,/重启工作台/);
  context.renderRegisteredProjects({items:[],registration:{sources:['local','git']}});
  assert.equal(document.getElementById('project-register').disabled,false);
});

test('the same registration form can explicitly try again after a checked failure without replaying or removing the old receipt',async()=>{
  const {context,document,calls,store}=setup({journal:true}),receipts=new Map();let directoryValid=false,attempts=0;
  context.api=async(url,options)=>{
    const method=options?.method || 'GET';calls.push({url,method});
    if(method==='GET'){
      const query=new URLSearchParams(url.split('?')[1]),operation=query.get('operation'),key=query.get('key');
      return {operation,key,status:receipts.get(key)?.status || 'not_found',automatic_replay:false};
    }
    const body=JSON.parse(options.body),old=receipts.get(body.submission_key);
    if(old?.status==='failed')throw Error('目录属于另一个仓库');
    attempts++;
    if(!directoryValid){receipts.set(body.submission_key,{status:'failed',body});throw Error('目录属于另一个仓库');}
    receipts.set(body.submission_key,{status:'completed',body});
    return {id:'PROJECT-FIXTURE',name:body.name,root_path:body.root_path,eval_command:[]};
  };
  const reopen=()=>{
    document.getElementById('open-project-registration').onclick();
    document.getElementById('project-name').value='隔离项目登记夹具';document.getElementById('project-root').value='D:/fixture/project';
  };
  const submit=()=>document.getElementById('project-register').onclick();
  reopen();await submit();assert.equal(attempts,1);
  assert.match(document.getElementById('project-status').textContent,/属于另一个仓库/);
  const storageKey='workbench-mutation-journal-v1:REGISTRATION-FIXTURE',entry=JSON.parse(store.getItem(storageKey))[0],oldKey=entry.submission_key;
  directoryValid=true;reopen();await submit();assert.equal(attempts,1);assert.equal(calls.filter(c=>c.method==='POST').length,1);
  await context.WorkbenchMutationJournal.check(entry);context.WorkbenchMutationJournal.finish(entry);
  assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(receipts.get(oldKey).status,'failed');
  reopen();await submit();assert.equal(attempts,2);assert.equal(calls.filter(c=>c.method==='POST').length,2);
  const newKey=[...receipts.keys()].find(key=>key!==oldKey);assert.ok(newKey);assert.equal(receipts.get(newKey).status,'completed');
  const withoutKey=body=>{const {submission_key,...fields}=body;return fields;};assert.deepEqual(withoutKey(receipts.get(newKey).body),withoutKey(receipts.get(oldKey).body));
  assert.equal(receipts.get(oldKey).status,'failed');assert.equal(JSON.parse(store.getItem(storageKey)).length,0);
  assert.doesNotMatch([...store.data.values()].join(''),/fixture-user|root_path|preview_config|actor/);
  assert.match(document.getElementById('project-status').textContent,/已保存项目/);
});
