/* Evidence and human decisions inside the existing initiative workspace. */
function learningText(tag, text) {
  const el=document.createElement(tag);el.textContent=text;return el;
}
function learningAction(fields) {return initiativeWorkAction('learning',{fields});}
function renderLearning(data) {
  const panel=iw('learning');if(!panel)return;
  const busy=['researching','queued','executing','checking','cancelling','integrating'].includes(data.stage) || initiativeWorkPending;
  const recall=data.learning_recall, learning=data.learning || {assets:[],bindings:[],metrics:{}};
  const decisions=data.learning_decision;
  iw('learning-summary').textContent=recall ?
    `本轮召回 ${recall.matches.length} 项；${decisions ? '已记录逐项决定' : '请在确认方案前核对采用理由'}。`+
    (recall.conflicts.length ? ' 同主题存在多个结论，请分别判断。' : '') : '尚未召回；开始调研时会自动检索本项目已发布经验。';
  const box=iw('learning-matches');
  const signature=JSON.stringify([data.id,recall?.id,decisions]);
  if(box.dataset.signature!==signature) {
    box.replaceChildren();box.dataset.signature=signature;
    for(const m of recall?.matches || []) {
      const card=document.createElement('article');card.dataset.assetId=m.id;
      card.append(learningText('h4',`${m.title} · v${m.version} · ${m.state==='candidate' ? '待独立试用' : '已发布'}`),
        learningText('p',m.content),learningText('p','适用边界：'+m.boundary),learningText('p',m.reason),
        learningText('p',`来源事项 ${m.source.initiative_id} / 任务 ${m.source.task_id} / ${m.id}`));
      const saved=decisions?.choices.find(c=>c.id===m.id);
      const label=learningText('label','采用决定');const select=document.createElement('select');select.dataset.choice='adopt';
      for(const [value,text] of [['','请选择'],['yes','采用'],['no','不采用']]){const option=learningText('option',text);option.value=value;select.append(option);}
      select.value=saved ? saved.adopt ? 'yes' : 'no' : '';label.append(select);card.append(label);
      const reasonLabel=learningText('label','判断理由');const reason=document.createElement('textarea');reason.rows=2;reason.dataset.choice='reason';reason.value=saved?.reason || '';reasonLabel.append(reason);card.append(reasonLabel);
      const asset=learning.assets.find(a=>a.id===m.id);
      for(const name of asset?.recipe?.parameters || []) {
        const l=learningText('label','流程参数：'+name), input=document.createElement('input');input.dataset.parameter=name;input.value=saved?.parameters?.[name] || '';l.append(input);card.append(l);
      }
      box.append(card);
    }
    if(recall?.excluded.length) {
      const details=document.createElement('details');details.append(learningText('summary','未召回的原因'));
      for(const e of recall.excluded)details.append(learningText('p',e.id+'：'+e.reason));box.append(details);
    }
  }
  box.querySelectorAll('input,select,textarea').forEach(e=>e.disabled=busy || !['ready','clarifying'].includes(data.stage));
  iw('learning-decide').disabled=busy || !recall || !['ready','clarifying'].includes(data.stage);
  ['recall','trial'].forEach(k=>iw('learning-'+k).disabled=busy || !['idle','clarifying','ready','rework','failed'].includes(data.stage));
  iw('learning-create').disabled=busy;
  renderLearningSources(data,busy);
  const assets=iw('learning-assets'), assetSignature=JSON.stringify([data.id,learning.assets.map(a=>[a.id,a.state,a.trial_approved,a.history.length])]);
  if(assets.dataset.signature!==assetSignature) {
    assets.dataset.signature=assetSignature;assets.replaceChildren();
    for(const a of learning.assets) {
      const card=document.createElement('article');card.append(learningText('h4',`${a.title} · v${a.version} · ${a.state}${a.trial_approved ? ' · 已准许试用' : ''}`),learningText('p',a.id),learningText('p',a.boundary));
      const evidence=document.createElement('details');evidence.append(learningText('summary','查看提炼结论、原始轨迹与审核历史'),learningText('pre',JSON.stringify(a,null,2)));card.append(evidence);
      const label=learningText('label','审核或停用理由'), note=document.createElement('textarea');note.rows=2;label.append(note);card.append(label);
      const options=a.state==='candidate' ? [['approve',a.kind==='workflow' ? '独立审核：准许试用' : '独立审核：发布记忆'],...(a.kind==='workflow' && a.trial_approved ? [['publish','试用验收后发布流程']] : []),['revoke','停用候选']] : a.state==='active' ? [['revoke','撤回此版本']] : [];
      for(const [action,title] of options){const b=learningText('button',title);b.type='button';b.onclick=()=>learningAction({action,asset_id:a.id,note:note.value.trim()});card.append(b);}
      const revise=learningText('button','以此版本为依据提炼新候选');revise.type='button';revise.onclick=()=>{iw('learning-supersedes').value=a.id;iw('learning-kind').value=a.kind;iw('learning-kind').onchange();iw('learning-title').value=a.title;iw('learning-conflict').value=a.conflict_key;};card.append(revise);assets.append(card);
    }
  }
  assets.querySelectorAll('button,textarea').forEach(b=>b.disabled=busy);
  iw('learning-evidence').textContent=JSON.stringify({metrics:learning.metrics,bindings:learning.bindings},null,2);
}
function renderLearningSources(data,busy) {
  const sources=data.learning_sources || {tasks:[],feedback:[]}, task=iw('learning-task');
  const signature=JSON.stringify([data.id,sources]);
  if(task.dataset.sources!==signature) {
    const previous=task.dataset.initiative===data.id ? task.value : data.active_task_id;
    task.replaceChildren();const empty=learningText('option','选择本事项真实来源任务');empty.value='';task.append(empty);
    for(const source of sources.tasks){const option=learningText('option',source.label || source.id);option.value=source.id;task.append(option);}
    task.dataset.initiative=data.id;task.dataset.sources=signature;
    task.value=sources.tasks.some(t=>t.id===previous) ? previous : '';
  }
  task.disabled=busy;renderLearningFeedback(sources,busy);
  task.onchange=()=>renderLearningFeedback(sources,busy);
}
function renderLearningFeedback(sources,busy) {
  const box=iw('learning-feedback'), rows=sources.feedback.filter(f=>f.task_id===iw('learning-task').value);
  const signature=JSON.stringify(rows);
  if(box.dataset.sources!==signature){
    const previous=box.value;box.replaceChildren();const empty=learningText('option','成功任务可留空；失败任务须选择已接受反馈');empty.value='';box.append(empty);
    for(const row of rows){const option=learningText('option',row.label || row.id);option.value=row.id;box.append(option);}
    box.value=rows.some(r=>r.id===previous) ? previous : rows.length===1 ? rows[0].id : '';
    box.dataset.sources=signature;
  }
  box.disabled=busy;
}
function initLearning() {
  if(!iw('learning'))return;
  iw('learning-kind').onchange=()=>{
    iw('learning-recipe').hidden=iw('learning-kind').value!=='workflow';
    if(iw('learning-kind').value==='workflow') {
      const defaults={precheck:'检查本次输入及授权文件，前置条件不满足时停止。',implement:'按照本事项已确认的方案，在授权写集内实现并保留实际 Diff。',eval:'运行本项目阻断级 Eval，保留报告、退出码与失败证据。',review:'由本事项确认的验收负责人对照实际结果与验收标准作出决定。'};
      for(const [key,text] of Object.entries(defaults))if(!iw('learning-'+key).value.trim())iw('learning-'+key).value=text;
    }
  };
  iw('learning-recall').onclick=()=>learningAction({action:'recall'});
  iw('learning-trial').onclick=()=>learningAction({action:'recall',trials:true});
  iw('learning-decide').onclick=()=>{
    const choices=[...iw('learning-matches').querySelectorAll('article[data-asset-id]')].map(card=>{
      const value=card.querySelector('[data-choice="adopt"]').value;
      return {id:card.dataset.assetId,adopt:value==='yes' ? true : value==='no' ? false : null,
        reason:card.querySelector('[data-choice="reason"]').value.trim(),
        parameters:Object.fromEntries([...card.querySelectorAll('[data-parameter]')].map(e=>[e.dataset.parameter,e.value.trim()]))};
    });learningAction({action:'decide',recall_id:initiativeWork.learning_recall.id,choices});
  };
  iw('learning-create').onclick=()=>{
    const value=k=>iw('learning-'+k).value.trim(), lines=k=>value(k).split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    const candidate={kind:value('kind'),task_id:value('task'),feedback_id:value('feedback'),supersedes:value('supersedes'),title:value('title'),content:value('content'),applies:lines('applies'),excludes:lines('excludes'),boundary:value('boundary'),conflict_key:value('conflict') || value('title')};
    if(candidate.kind==='workflow')candidate.recipe={parameters:lines('parameters'),
      preconditions:lines('paths').map(path=>value('contains') ? {kind:'file_contains',path,text:value('contains')} : {kind:'file_exists',path}),
      steps:['precheck','implement','eval','review'].map((phase,i,all)=>({phase,role:['harness','codex','harness','human'][i],depends_on:i ? [all[i-1]] : [],instruction:value(phase)})),
      authorization:'confirmed_plan',eval_entry:'project_blocking',outputs:lines('outputs'),stop:value('stop'),rollback:value('rollback')};
    learningAction({action:'create',candidate});
  };
}
