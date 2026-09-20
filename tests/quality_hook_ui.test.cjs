const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('Hook panel distinguishes prepared, installed, skipped and stale evidence', () => {
  const nodes = new Map();
  const element = () => ({textContent:'', disabled:false, children:[],
    replaceChildren(){this.children=[];}, append(child){this.children.push(child);}});
  const document = {getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},createElement:element};
  const context=vm.createContext({document, Date});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../workbench_web/initiative_workflow.js'),'utf8'),context);
  context.renderQualityHook({quality_hook:{status:'not_prepared',can_prepare:false}});
  assert.equal(nodes.get('iw-hook-prepare').disabled,true);
  context.renderQualityHook({workspace:'candidate', active_task_id:'TASK-1',
    plan:{project:{eval_command:['product-python','check.py']}},
    quality_hook:{status:'prepared',can_prepare:true,path:'review-package',runs:[]}});
  assert.equal(nodes.get('iw-hook-prepare').disabled,false);
  assert.match(nodes.get('iw-hook-status').textContent,/尚未安装/);
  assert.match(nodes.get('iw-hook-files').textContent,/product-python/);
  context.renderQualityHook({quality_hook:{status:'installed',can_prepare:true,
    runs:[{at:1,outcome:'skipped'},{at:2,outcome:'pass',freshness:'stale'}]}});
  assert.match(nodes.get('iw-hook-status').textContent,/信任与真实触发待核对/);
  assert.match(nodes.get('iw-hook-runs').children[0].textContent,/重入跳过，未验证/);
  assert.match(nodes.get('iw-hook-runs').children[1].textContent,/报告已过期/);
});
