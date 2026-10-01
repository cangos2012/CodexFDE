/* Local workbench data recovery. Restoration remains an offline CLI action. */
let workbenchBackupPending = false;
const backupElement = id => document.getElementById('backup-' + id);
function backupShellQuote(value) { return "'" + String(value).replace(/'/g, "''") + "'"; }
function backupCommands(item) {
  const prefix = '.venv/Scripts/python.exe -X utf8 -m workbench.cli ';
  return prefix + 'verify-workbench-backup ' + backupShellQuote(item.archive_path) + '\n' +
    prefix + 'restore-workbench-backup ' + backupShellQuote(item.archive_path) +
    ' --runtime-dir ' + backupShellQuote(item.runtime_root);
}
function backupText(tag, value) { const node=document.createElement(tag);node.textContent=value;return node; }
function renderWorkbenchBackups(data) {
  backupElement('list').replaceChildren();
  backupElement('boundary').textContent=data.boundary;
  backupElement('runtime').textContent='当前工作台数据目录：'+data.runtime;
  backupElement('restored').hidden=!data.restored;
  backupElement('restored').textContent=data.restored ? '证据已恢复，旧任务不会自动重放；外部环境仍须核对；新任务需明确授权。' : '';
  if(!data.items.length)backupElement('list').append(backupText('p','尚无工作台备份。结束正在运行的事项和候选预览后，可在这里创建。'));
  for(const item of data.items) {
    const row=backupText('article','');
    row.append(backupText('h3',item.id));
    if(item.error){row.append(backupText('p',item.error));backupElement('list').append(row);continue;}
    row.append(backupText('p',item.created_at+' · '+item.actor+' · '+item.file_count+' 个文件 · '+Math.ceil(item.archive_bytes/1024)+' KiB'));
    row.append(backupText('p',item.boundary));
    if(item.warnings.length)row.append(backupText('p','备份时发现 '+item.warnings.length+' 项缺失或未打包引用。校验时请核对明细。'));
    const link=backupText('a','下载备份');link.href=item.download_url;link.setAttribute('download','');row.append(link);
    const button=backupText('button','校验此备份');button.type='button';button.disabled=workbenchBackupPending;
    button.onclick=()=>verifyWorkbenchBackup(item.id);row.append(button);
    const details=backupText('details','');details.append(backupText('summary','本机停服恢复命令'),
      backupText('p','先下载并校验备份，把备份包保存到待恢复目录之外。停服后保留现有运行目录，确保原路径为空，再执行恢复命令；需要按包的实际保存位置调整路径。'),
      backupText('pre',backupCommands(item)));row.append(details);backupElement('list').append(row);
  }
}
async function refreshWorkbenchBackups() {
  try {const data=await api('/api/v1/backups');renderWorkbenchBackups(data);return true;}
  catch(error){backupElement('status').textContent='备份列表读取失败：'+error.message;return false;}
}
async function createWorkbenchBackup() {
  if(workbenchBackupPending)return;
  let actor;
  try { actor=actorName(); }
  catch(error) { backupElement('status').textContent='请关闭此窗口，填写操作署名后再备份：'+error.message;return; }
  if(!actor){backupElement('status').textContent='请先填写上方的操作署名。';return;}
  workbenchBackupPending=true;backupElement('create').disabled=true;
  backupElement('status').textContent='正在冻结写入并备份数据库与文件证据，请等待。当前草稿仍保留在浏览器。';
  try {
    const item=await api('/api/v1/backups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor})});
    await refreshWorkbenchBackups();
    backupElement('status').textContent='备份已保存：'+item.id+'。请下载到运行目录之外，并核对外部项目与 Git 依赖。';
  }catch(error){backupElement('status').textContent='备份未确认：'+error.message+'。请刷新列表核对；草稿未提交或清理。';}
  finally{workbenchBackupPending=false;backupElement('create').disabled=false;backupElement('list').querySelectorAll('button').forEach(button=>button.disabled=false);}
}
async function verifyWorkbenchBackup(identifier) {
  if(workbenchBackupPending)return;
  workbenchBackupPending=true;backupElement('create').disabled=true;
  backupElement('status').textContent='正在校验包内数据库与文件哈希；不会执行旧任务。';
  backupElement('list').querySelectorAll('button').forEach(button=>button.disabled=true);
  try {
    const result=await api('/api/v1/backups/'+encodeURIComponent(identifier)+'/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:actorName()})});
    backupElement('status').textContent='包内校验通过：'+result.files_verified+' 个文件。'+
      (result.missing_external_dependencies.length ? '当前缺少 '+result.missing_external_dependencies.length+' 项外部依赖。' : '当前列出的外部依赖路径可访问，仍需核对运行环境。');
    backupElement('detail').textContent=JSON.stringify(result,null,2);
  }catch(error){backupElement('status').textContent='备份校验失败：'+error.message;}
  finally{workbenchBackupPending=false;backupElement('create').disabled=false;backupElement('list').querySelectorAll('button').forEach(button=>button.disabled=false);}
}
function initWorkbenchBackups() {
  const open=document.getElementById('open-backups');if(!open)return;
  open.onclick=()=>{backupElement('dialog').showModal();refreshWorkbenchBackups();};
  backupElement('close').onclick=()=>backupElement('dialog').close();
  backupElement('create').onclick=createWorkbenchBackup;
  backupElement('refresh').onclick=refreshWorkbenchBackups;
}
