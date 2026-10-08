/* Recovery hints contain request identity only, never authority or replay data. */
var WorkbenchMutationJournal = (() => {
  const prefix='workbench-mutation-journal-v1:';
  const fields=['runtime_instance','operation','submission_key','started_at','label'];
  let runtime='',storage=null,entries=[],loadError='';
  const checked=new Map(),reading=new Set();
  const el=id=>document.getElementById(id);
  const text=(tag,value)=>{const node=document.createElement(tag);node.textContent=value;return node;};
  const id=e=>e.operation+'\n'+e.submission_key;
  const same=e=>entries.some(current=>id(current)===id(e));
  function label(path) {
    if(path.includes('/workflow/learning'))return '经验草稿生成或停止请求';
    if(path.includes('/deployments/'))return '发布、业务核对或回退请求';
    if(path.includes('/runtime/subtasks/'))return '分工准备或启动请求';
    if(path.includes('/runtime/approvals/'))return '一次工具授权决定请求';
    if(path.endsWith('/runtime/control'))return '运行控制请求';
    if(path.endsWith('/runtime/profile'))return '运行 Profile 选择请求';
    if(path.endsWith('/preview'))return '候选预览启动请求';
    if(path.endsWith('/plan'))return '项目计划保存请求';
    if(path==='/api/v1/migration/prepare')return '迁移包准备请求';
    if(path.startsWith('/api/v1/projects'))return '项目登记或配置请求';
    return '工作台提交请求';
  }
  function persist(next) {
    if(!storage || loadError)throw new Error('本机待核对记录无法保存；本次提交尚未发送。请先恢复浏览器存储或核对并清理提示。');
    storage.setItem(prefix+encodeURIComponent(runtime),JSON.stringify(next.map(e=>Object.fromEntries(fields.map(k=>[k,e[k]])))));
    entries=next;
  }
  function render(notice='') {
    const panel=el('mutation-journal');if(!panel)return;
    panel.hidden=!entries.length && !notice;
    el('mutation-journal-status').textContent=notice || loadError || '有 '+entries.length+' 笔请求结果待核对。先读取回执和当前事项，再明确结束提示；不会自动重放。';
    const list=el('mutation-journal-items');list.replaceChildren();
    for(const entry of entries) {
      const row=document.createElement('article');row.append(text('h3',entry.label),text('p','开始于 '+new Date(entry.started_at).toLocaleString()),text('pre',entry.operation+'\n提交键：'+entry.submission_key));
      const receipt=checked.get(id(entry));
      const state=receipt ? ({pending:'原请求尚未确认结果；提示与提交键保留。请稍后只读核对回执和当前事项，确认前不要重新提交。',completed:'请求已受理，请核对当前事项；这不代表交付完成。',failed:'原请求记录为失败，请核对当前事项与证据。',not_found:'尚未找到回执，不能据此认定未执行；提示与提交键保留。请稍后只读核对回执和当前事项，确认前不要重新提交。'})[receipt] : '尚未核对原请求回执；提示与提交键保留，请先只读核对。';
      row.append(text('p',state));
      const read=text('button','只读核对原回执');read.type='button';read.disabled=reading.has(id(entry));read.onclick=()=>check(entry);
      const end=text('button','我已核对，结束此提示');end.type='button';end.disabled=!['completed','failed'].includes(receipt) || reading.has(id(entry));end.onclick=()=>finish(entry);
      row.append(read,end);list.append(row);
    }
  }
  function init(instance,customStorage) {
    if(!instance)return;
    if(runtime===instance && storage){render();return;}
    runtime=instance;entries=[];checked.clear();reading.clear();loadError='';
    try {
      storage=customStorage || localStorage;
      const raw=storage.getItem(prefix+encodeURIComponent(runtime));
      const saved=raw?JSON.parse(raw):[];
      if(!Array.isArray(saved) || saved.length>100 || saved.some(e=>!e || Object.keys(e).some(k=>!fields.includes(k)) || e.runtime_instance!==runtime || typeof e.operation!=='string' || !e.operation.startsWith('/api/v1/') || typeof e.submission_key!=='string' || !e.submission_key || typeof e.started_at!=='number' || typeof e.label!=='string'))throw new Error('待核对记录格式无效');
      entries=saved;
    }catch(_){loadError='本机待核对记录不可读，原数据保留；请核对工作台记录后再明确清理。';}
    render(loadError);
  }
  function begin(operation,key) {
    if(!runtime)return null; // Minimal fixtures without a service identity remain usable.
    if(entries.some(e=>e.operation===operation))throw new Error('本操作有一笔结果待核对的请求。请先只读核对原回执，再明确结束提示；本次没有发送新请求。');
    if(entries.length>=100)throw new Error('待核对请求达到100笔，请先核对并结束已有提示；本次没有发送。');
    if(typeof key!=='string' || !key || key.length>160)throw new Error('缺少稳定提交键；本次没有发送。');
    const entry={runtime_instance:runtime,operation,submission_key:key,started_at:Date.now(),label:label(operation)};
    try{persist([...entries,entry]);}catch(_){render('本机待核对记录未保存，本次请求没有发送。');throw new Error('本机待核对记录未保存，本次请求没有发送。');}
    render();return entry;
  }
  function acknowledge(entry) {
    if(!entry || entry.runtime_instance!==runtime || !same(entry))return;
    try{persist(entries.filter(e=>id(e)!==id(entry)));checked.delete(id(entry));render();}
    catch(_){render('请求已受理，但本机提示未清理；请只读核对回执后结束提示。');}
  }
  async function check(entry) {
    if(!same(entry) || reading.has(id(entry)))return;
    let notice='';
    reading.add(id(entry));render('正在只读核对原请求回执…');
    try {
      const value=await api('/api/v1/mutations/receipt?operation='+encodeURIComponent(entry.operation)+'&key='+encodeURIComponent(entry.submission_key));
      if(!same(entry))return;
      if(value.operation!==entry.operation || value.key!==entry.submission_key || !['pending','completed','failed','not_found'].includes(value.status) || value.automatic_replay!==false)throw new Error('回执身份无法核对');
      checked.set(id(entry),value.status);
    }catch(_){if(same(entry)){checked.delete(id(entry));notice='原回执暂时不可读，提示保留；本次未重放任何请求。';}}
    finally{reading.delete(id(entry));render(notice);}
  }
  function finish(entry) {
    if(!same(entry) || !checked.has(id(entry)) || reading.has(id(entry)))return;
    if(!['completed','failed'].includes(checked.get(id(entry)))){render('原请求结果尚未确认；待核对提示和原提交键已保留。请稍后只读核对回执和当前事项，确认前不要重新提交。');return;}
    const failed=checked.get(id(entry))==='failed';
    try{
      persist(entries.filter(e=>id(e)!==id(entry)));
      if(failed && typeof releaseFailedPlatformKey==='function')releaseFailedPlatformKey(entry.submission_key);
      checked.delete(id(entry));
      render('已结束本机提示；后端请求、授权和验收记录保持原状。'+(failed ? '原失败回执保留；核对当前状态后，再次点击提交会使用新的提交键，本次未发送请求。' : ''));
    }
    catch(_){render('本机提示未能结束，原提交键保留。');}
  }
  function clear() {
    if(!runtime)return;
    try{storage?.removeItem(prefix+encodeURIComponent(runtime));entries=[];checked.clear();reading.clear();loadError='';render('本机提示已清理；不会取消、重放或改变工作台里的请求。');}
    catch(_){render('本机提示未清理，原记录保留。');}
  }
  return {init,begin,acknowledge,check,finish,clear,render};
})();
