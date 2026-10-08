const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {dom}=require('./web_dom.cjs');
function setup(){
  const ui=dom(),calls=[];
  const context=vm.createContext({document:ui.document,URL,Date,AbortController,setTimeout,clearTimeout,
    fetch:async(url,options)=>{calls.push({url,options});let value;
      if(url==='/api/v1/health')value={status:'ok',compatibility_view:true,workbench_url:'http://127.0.0.1:8101'};
      else if(url==='/api/v1/profiles')value={items:[{id:'P1',name:'只读组合'}]};
      else if(url.includes('/sessions?'))value={items:[{id:'S1',title:'已有事项运行'}]};
      else if(url.includes('/dump-config?'))value={profile:{id:'P1'},plugins:[]};
      else if(url==='/api/v1/sessions/S1')value={id:'S1',task_id:'T1',events:[{kind:'task/eval',evidence:{report_sha256:'actual'}}]};
      else if(url==='/api/v1/legacy')value={read_only:true,automatic_replay:false,projects:[],sessions:[{id:'OLD'}],tasks:[]};
      else throw Error('unexpected '+url);return {ok:true,json:async()=>value};}});
  vm.runInContext(fs.readFileSync('harness_web/app.js','utf8').replace(/initCompatibility\(\);\s*$/,''),context);
  return {...ui,context,calls};
}
test('8010 has one workbench entry, a legacy history reader, and no second write workspace',()=>{
  const html=fs.readFileSync('harness_web/index.html','utf8');
  assert.match(html,/id="workbench-link"/);assert.match(html,/id="compat-history-load"/);assert.match(html,/id="compat-profile"/);assert.match(html,/id="compat-session"/);
  assert.doesNotMatch(html,/id="(?:register-project|review-confirm|send|actor)"/);
});
test('the compatibility client can query history and sessions but cannot submit writes or restore signatures',()=>{
  const source=fs.readFileSync('harness_web/app.js','utf8');
  assert.match(source,/\/api\/v1\/legacy/);assert.match(source,/\/api\/v1\/sessions/);assert.match(source,/\/api\/v1\/profiles/);
  assert.doesNotMatch(source,/method\s*:\s*["']POST["']|localStorage|X-Workbench-Actor|Idempotency-Key/);
});
test('the entry uses the actual loopback upstream and all startup requests are reads',async()=>{
  const a=setup();await a.context.initCompatibility();assert.equal(a.node('workbench-link').href,'http://127.0.0.1:8101/');assert.equal(a.node('workbench-link').hidden,false);
  assert.equal(a.calls.length,3);assert.ok(a.calls.every(call=>call.options.method==='GET' && !call.options.body));
  assert.equal(a.calls.some(call=>call.url==='/api/v1/legacy'),false);
});
test('Profile and Session queries show real returned identity and history remains independently readable',async()=>{
  const a=setup();await a.context.initCompatibility();a.node('compat-profile').value='P1';await a.node('compat-profile-load').onclick();
  assert.equal(JSON.parse(a.node('compat-profile-evidence').textContent).profile.id,'P1');
  a.node('compat-session').value='S1';await a.node('compat-session-load').onclick();
  assert.equal(JSON.parse(a.node('compat-session-evidence').textContent).events[0].evidence.report_sha256,'actual');
  await a.node('compat-history-load').onclick();assert.equal(JSON.parse(a.node('compat-history-evidence').textContent).sessions[0].id,'OLD');
  assert.ok(a.calls.every(call=>call.options.method==='GET' && !call.options.body));
});
test('unsafe or missing upstream identity cannot manufacture a link to 8001',async()=>{
  for(const health of [{compatibility_view:true,workbench_url:'https://outside.example/'},{status:'ok'},{compatibility_view:true,workbench_url:'http://127.0.0.1:8101/other'}]){
    const a=setup(),fetch=a.context.fetch;a.context.fetch=(url,options)=>url==='/api/v1/health'?Promise.resolve({ok:true,json:async()=>health}):fetch(url,options);
    await a.context.initCompatibility();assert.equal(a.node('workbench-link').hidden,true);assert.match(a.node('compat-status').textContent,/不可读/);
  }
});
test('unavailable advanced runtime does not hide the separate legacy history query',async()=>{
  const a=setup(),fetch=a.context.fetch;a.context.fetch=(url,options)=>url==='/api/v1/legacy'?fetch(url,options):Promise.resolve({ok:false,json:async()=>({error:'advanced_disabled'})});
  await a.context.initCompatibility();assert.equal(a.node('workbench-link').hidden,true);assert.match(a.node('compat-profile-status').textContent,/不可读/);
  await a.node('compat-history-load').onclick();assert.match(a.node('compat-history-status').textContent,/旧历史已读取/);
});
test('late Session evidence cannot overwrite a new selection and wrong Profile identity is rejected',async()=>{
  const a=setup();await a.context.initCompatibility();let resolve;a.context.fetch=()=>new Promise(done=>{resolve=done;});
  a.node('compat-session').value='S1';const old=a.context.readCompatibilitySession();a.node('compat-session').value='S2';
  resolve({ok:true,json:async()=>({id:'S1',events:[{kind:'old'}]})});await old;assert.equal(a.node('compat-session-evidence').textContent,'');
  a.node('compat-profile').value='P1';a.context.fetch=async()=>({ok:true,json:async()=>({profile:{id:'OTHER'}})});
  await a.context.readCompatibilityProfile();assert.match(a.node('compat-profile-status').textContent,/身份无法核对/);assert.equal(a.node('compat-profile-evidence').textContent,'');
});
test('a hanging compatibility query times out, retains unknown state, and is never replayed as a write',async()=>{
  const a=setup();await a.context.initCompatibility();let deadline,count=0;a.context.setTimeout=fn=>{deadline=fn;return 1;};a.context.clearTimeout=()=>{};
  a.context.fetch=(url,options)=>{++count;assert.equal(options.method,'GET');return new Promise(()=>{});};a.node('compat-session').value='S1';
  const read=a.context.readCompatibilitySession();deadline();await read;assert.equal(count,1);assert.match(a.node('compat-session-status').textContent,/超时/);assert.equal(a.node('compat-session-evidence').textContent,'');
});
