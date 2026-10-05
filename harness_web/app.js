/* 8010 is a read-only compatibility view; all human decisions use the workbench. */
const compatNode=id=>document.getElementById(id);
const compatState={pending:new Map(),profileRead:0,sessionRead:0,shellRead:0};
async function compatApi(path) {
  const controller=new AbortController();let timer;
  const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(new Error('读取超时，请重新核对原记录。'));},10000);});
  try {
    return await Promise.race([timeout,(async()=>{
      const response=await fetch(path,{method:'GET',cache:'no-store',signal:controller.signal});
      const value=await response.json();if(!response.ok)throw new Error(value.message || value.error || '查询失败');return value;
    })()]);
  }finally{clearTimeout(timer);}
}
function compatRead(path) {
  if(compatState.pending.has(path))return compatState.pending.get(path);
  const pending=compatApi(path).finally(()=>{if(compatState.pending.get(path)===pending)compatState.pending.delete(path);});
  compatState.pending.set(path,pending);return pending;
}
function compatOptions(id,rows,label) {
  const select=compatNode(id),previous=select.value;select.replaceChildren();
  const empty=document.createElement('option');empty.value='';empty.textContent=label;select.append(empty);
  for(const row of rows){const option=document.createElement('option');option.value=row.id;option.textContent=(row.name || row.title || row.id)+' · '+row.id;select.append(option);}
  select.value=rows.some(row=>row.id===previous)?previous:'';
}
function compatWorkbenchUrl(value) {
  const url=new URL(value);
  if(url.protocol!=='http:' || !['127.0.0.1','localhost','[::1]'].includes(url.hostname) || url.username || url.password || url.pathname!=='/' || url.search || url.hash)throw new Error('服务返回的工作台地址不是本机根入口，请核对兼容服务的 --workbench-url。');
  return url.href;
}
async function refreshCompatibility() {
  const read=++compatState.shellRead;
  ++compatState.profileRead;++compatState.sessionRead;
  compatNode('compat-profile-evidence').textContent='';compatNode('compat-session-evidence').textContent='';
  compatNode('compat-status').textContent='正在只读核对兼容服务与上游工作台…';
  const results=await Promise.allSettled(['/api/v1/health','/api/v1/profiles','/api/v1/sessions?limit=100'].map(compatRead));
  if(read!==compatState.shellRead)return;
  const [health,profiles,sessions]=results;
  const link=compatNode('workbench-link');link.hidden=true;
  try {
    if(health.status==='rejected')throw health.reason;
    if(health.value.compatibility_view!==true || !health.value.workbench_url)throw new Error('上游入口尚未核对；请检查兼容服务的 --workbench-url。');
    link.href=compatWorkbenchUrl(health.value.workbench_url);link.hidden=false;
    compatNode('compat-workbench-address').textContent='日常工作台：'+link.href;
    compatNode('compat-status').textContent='读取于 '+new Date().toLocaleTimeString()+'。此页只提供查询，项目配置、运行授权、执行与验收请打开日常工作台。';
  }catch(error){compatNode('compat-status').textContent='上游状态不可读：'+error.message;compatNode('compat-workbench-address').textContent='尚未核对日常工作台地址。';}
  for(const [result,kind,label] of [[profiles,'profile','选择要核对的 Profile'],[sessions,'session','选择要核对的 Session']]) {
    if(result.status==='fulfilled' && Array.isArray(result.value.items)) {
      compatOptions('compat-'+kind,result.value.items,label);compatNode('compat-'+kind+'-status').textContent='已读取 '+result.value.items.length+' 项；选择后只读查看。';
    }else {
      compatOptions('compat-'+kind,[],label);compatNode('compat-'+kind+'-evidence').textContent='';
      compatNode('compat-'+kind+'-status').textContent='列表不可读：'+(result.reason?.message || '返回格式无法核对');
    }
  }
}
async function readCompatibilityProfile() {
  const id=compatNode('compat-profile').value,read=++compatState.profileRead;compatNode('compat-profile-evidence').textContent='';
  if(!id)return;
  compatNode('compat-profile-status').textContent='正在读取 Profile 配置…';
  try {
    const value=await compatRead('/api/v1/dump-config?profile_id='+encodeURIComponent(id));
    if(read!==compatState.profileRead || id!==compatNode('compat-profile').value)return;
    if(value.profile?.id!==id)throw new Error('Profile 身份无法核对');
    compatNode('compat-profile-evidence').textContent=JSON.stringify(value,null,2);compatNode('compat-profile-status').textContent='配置已读取；此处不改变运行 Profile 或插件。';
  }catch(error){if(read===compatState.profileRead)compatNode('compat-profile-status').textContent='配置不可读：'+error.message;}
}
async function readCompatibilitySession() {
  const id=compatNode('compat-session').value,read=++compatState.sessionRead;compatNode('compat-session-evidence').textContent='';
  if(!id)return;
  compatNode('compat-session-status').textContent='正在读取 Session 与原始事件…';
  try {
    const value=await compatRead('/api/v1/sessions/'+encodeURIComponent(id));
    if(read!==compatState.sessionRead || id!==compatNode('compat-session').value)return;
    if(value.id!==id)throw new Error('Session 身份无法核对');
    compatNode('compat-session-evidence').textContent=JSON.stringify(value,null,2);compatNode('compat-session-status').textContent='运行记录已读取；需要暂停、恢复、分工或审核时，请打开日常工作台对应事项。';
  }catch(error){if(read===compatState.sessionRead)compatNode('compat-session-status').textContent='运行记录不可读：'+error.message;}
}
async function readCompatibilityHistory() {
  const button=compatNode('compat-history-load');if(button.disabled)return;button.disabled=true;
  compatNode('compat-history-status').textContent='正在只读读取旧库历史…';compatNode('compat-history-evidence').textContent='';
  try {
    const value=await compatRead('/api/v1/legacy');
    if(value.read_only!==true || value.automatic_replay!==false)throw new Error('旧库只读边界无法核对');
    compatNode('compat-history-evidence').textContent=JSON.stringify(value,null,2);compatNode('compat-history-status').textContent='旧历史已读取。旧库仅供追溯；此页不会迁移、恢复或重放旧任务。';
  }catch(error){compatNode('compat-history-status').textContent='旧历史不可读：'+error.message;}
  finally{button.disabled=false;}
}
function initCompatibility() {
  compatNode('compat-refresh').onclick=refreshCompatibility;
  compatNode('compat-profile').onchange=readCompatibilityProfile;compatNode('compat-profile-load').onclick=readCompatibilityProfile;
  compatNode('compat-session').onchange=readCompatibilitySession;compatNode('compat-session-load').onclick=readCompatibilitySession;
  compatNode('compat-history-load').onclick=readCompatibilityHistory;
  return refreshCompatibility();
}
initCompatibility();
