const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function setup(api, actor='tester') {
  const nodes=new Map();
  function element(tag){return {tag,textContent:'',children:[],disabled:false,hidden:false,
    append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},setAttribute(){},
    querySelectorAll(tag){return this.children.flatMap(c=>[...(c.tag===tag?[c]:[]),...c.querySelectorAll(tag)]);}};}
  const document={createElement:element,getElementById(id){if(!nodes.has(id))nodes.set(id,element('div'));return nodes.get(id);}};
  const context=vm.createContext({document,api,actorName:()=>typeof actor==='function'?actor():actor,console});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../workbench_web/backups.js'),'utf8'),context);
  return {context,nodes};
}
test('backup failure preserves controls and explains uncertain result without submitting drafts',async()=>{
  let calls=0;
  const {context,nodes}=setup(async()=>{calls++;throw new Error('still executing');});
  await context.createWorkbenchBackup();
  assert.equal(calls,1);assert.equal(nodes.get('backup-create').disabled,false);
  assert.match(nodes.get('backup-status').textContent,/草稿未提交或清理/);
});
test('backup requires fresh operator identity',async()=>{
  let calls=0;const {context,nodes}=setup(async()=>calls++,'');
  await context.createWorkbenchBackup();assert.equal(calls,0);
  assert.match(nodes.get('backup-status').textContent,/署名/);
});
test('invalid operator identity is shown without an unhandled rejection',async()=>{
  let calls=0;const {context,nodes}=setup(async()=>calls++,()=>{throw new Error('署名不能为空');});
  await context.createWorkbenchBackup();assert.equal(calls,0);
  assert.match(nodes.get('backup-status').textContent,/填写操作署名/);
});
test('restore commands quote Windows paths and stay at recorded original path',()=>{
  const {context}=setup(async()=>{});
  const commands=context.backupCommands({archive_path:"D:\\work\\O'Brien\\saved.zip",runtime_root:'D:\\work\\数据\\runtime'});
  assert.match(commands,/O''Brien/);assert.match(commands,/--runtime-dir 'D:\\work\\数据\\runtime'/);
  assert.match(commands,/verify-workbench-backup/);assert.match(commands,/restore-workbench-backup/);
});
test('verified archive still reports missing external dependencies',async()=>{
  const {context,nodes}=setup(async()=>({files_verified:5,missing_external_dependencies:['missing project'],warnings:[]}));
  await context.verifyWorkbenchBackup('WB-fixture');
  assert.match(nodes.get('backup-status').textContent,/缺少 1 项外部依赖/);
  assert.match(nodes.get('backup-detail').textContent,/missing project/);
});
test('restored banner separates evidence recovery from external environment and authorization',()=>{
  const {context,nodes}=setup(async()=>{});
  context.renderWorkbenchBackups({items:[],boundary:'recorded recovery boundary',runtime:'D:/runtime',restored:true});
  const banner=nodes.get('backup-restored');
  assert.equal(banner.hidden,false);
  assert.match(banner.textContent,/证据已恢复/);
  assert.match(banner.textContent,/旧任务不会自动重放/);
  assert.match(banner.textContent,/外部环境仍须核对/);
  assert.match(banner.textContent,/新任务需明确授权/);
  context.renderWorkbenchBackups({items:[],boundary:'recorded recovery boundary',runtime:'D:/runtime',restored:false});
  assert.equal(banner.hidden,true);assert.equal(banner.textContent,'');
});
