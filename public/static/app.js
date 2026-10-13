'use strict';
const teamEls=[...document.querySelectorAll('[data-timer]')];
const pendingTimers=new Set();
let lastState={timers:{},now:Date.now()};
let timerEpoch=0;
function labelStatus(s){return {idle:'Aguardando',running:'Em andamento',paused:'Pausado',finished:'Encerrado'}[s]||'—'}
function pad(n){return String(Math.floor(n)).padStart(2,'0')}
function displayRemaining(state){
  const elapsedRunning=state.status==='running'&&state.started_at
    ?Math.max(0,Math.floor((Date.now()-state.started_at)/1000)):0;
  const remaining=Math.max(0,state.duration-state.elapsed-elapsedRunning);
  return pad(remaining/60)+':'+pad(remaining%60);
}
function updateTimers(){
  for(const el of teamEls){
    const id=el.dataset.timer;
    const state=lastState.timers[id];
    if(!state)continue;
    const remaining=displayRemaining(state);
    el.textContent=remaining;
    el.classList.toggle('warning',remaining==='00:00'||(Number(remaining.split(':')[0])===0&&Number(remaining.split(':')[1])<=30));
    const status=document.querySelector('[data-timer-status="'+id+'"]');
    if(status)status.textContent=labelStatus(state.status);
  }
}
// Estado já presente no HTML: sem aguardar o primeiro polling remoto.
for(const node of document.querySelectorAll('[data-timer-initial]')){
  const id=node.closest('[data-team]')?.dataset.team||node.dataset.timer;
  if(!id)continue;
  try{
    const timer=JSON.parse(node.dataset.timerInitial);
    if(timer.started_at)timer.started_at+=Date.now()-(timer.server_now||Date.now());
    lastState.timers[id]=timer;
  }catch(e){/* próxima sincronização corrige o estado */ }
}
updateTimers();
async function poll(){
  if(!teamEls.length)return;
  const epoch=timerEpoch;
  try{
    const res=await fetch('/api/state',{credentials:'same-origin',cache:'no-store'});
    if(!res.ok||res.redirected)return;
    const data=await res.json();
    if(epoch!==timerEpoch)return;
    const diff=Date.now()-data.now;
    for(const [id,t] of Object.entries(data.timers||{})){
      if(pendingTimers.has(id))continue;
      if(t.started_at)t.started_at+=diff;
      lastState.timers[id]=t;
    }
    updateTimers();
  }catch(e){/* tenta novamente na próxima consulta */ }
}
if(teamEls.length){poll();setInterval(poll,2000);setInterval(updateTimers,250)}

// Somente coordenação: executar sem popup, reload nem notificação de sucesso.
// O botão muda a tela instantaneamente enquanto o servidor persiste a ação.
function optimisticTimer(current,action){
  const t={...current};
  const seconds=()=>Math.max(0,Math.floor((Date.now()-t.started_at)/1000));
  if(action==='start'&&t.status==='idle'){
    t.elapsed=0;t.started_at=Date.now();t.status='running';
  }else if(action==='pause'&&t.status==='running'){
    t.elapsed+=seconds();t.started_at=null;t.status='paused';
  }else if(action==='resume'&&t.status==='paused'){
    t.started_at=Date.now();t.status='running';
  }else if(action==='finish'&&(t.status==='running'||t.status==='paused')){
    if(t.status==='running')t.elapsed+=seconds();
    t.started_at=null;t.status='finished';
  }else if(action==='reset'){
    t.status='idle';t.elapsed=0;t.started_at=null;t.duration=300;
  }else if(action==='extend'){
    t.duration+=60;
  }else{
    return null;
  }
  return t;
}
for(const form of document.querySelectorAll('form[data-timer-control]')){
  form.addEventListener('submit',async(event)=>{
    event.preventDefault();
    const article=form.closest('[data-team]');
    const id=article?.dataset.team;
    if(!id||pendingTimers.has(id))return;
    const action=form.action.split('/').pop();
    const current=lastState.timers[id];
    if(!current)return;
    const next=optimisticTimer(current,action);
    if(!next)return;
    const errorBox=article.querySelector('[data-timer-error]');
    if(errorBox)errorBox.textContent='';
    const buttons=[...article.querySelectorAll('form[data-timer-control] button')];
    buttons.forEach(button=>button.disabled=true);
    pendingTimers.add(id);
    timerEpoch++;
    lastState.timers[id]=next;
    updateTimers();
    try{
      const response=await fetch(form.action,{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'},
        body:new URLSearchParams(new FormData(form))
      });
      if(response.redirected)throw Error('Sessão expirada. Entre novamente.');
      const data=await response.json().catch(()=>({}));
      if(!response.ok||!data.ok){
        throw Error(data.error||'Comando não gravado. Tente novamente.');
      }
      // Sucesso silencioso: nada de mensagem, confirmação ou reload.
    }catch(error){
      lastState.timers[id]=current;
      updateTimers();
      if(errorBox)errorBox.textContent=error.message||'Erro de sincronização.';
    }finally{
      pendingTimers.delete(id);
      timerEpoch++;
      buttons.forEach(button=>button.disabled=false);
      void poll();
    }
  });
}
// Ficha rápida: três notas, cinco participantes e bonus por uma camera.
const fastForm=document.querySelector('#fast-evaluate');
const fastSaveButton=document.querySelector('#quick-save');
const quickSaveStatus=document.querySelector('#quick-save-status');
const quickNext=document.querySelector('#quick-next');
let saveInProgress=false;
let savedSignature=null;
function updateTotal(){
  const selected=[1,2,3].map(i=>document.querySelector('input[name="c'+i+'"]:checked'));
  const sum=selected.every(Boolean)?selected.reduce((n,e)=>n+Number(e.value),0):null;
  const el=document.querySelector('#score-total');
  if(el)el.textContent=(sum===null?'—':sum)+' / 15';
  const used=fastForm?.querySelector('input[name="used"]:checked')?.value;
  const adjusted=sum===null?'—':Math.min(15,sum*(used==='1'?1.1:1)).toFixed(2).replace('.',',');
  const adjustedEl=document.querySelector('#score-adjusted');
  if(adjustedEl)adjustedEl.textContent=adjusted+' / 15';
  const bonusLabel=document.querySelector('#camera-bonus-label');
  if(bonusLabel)bonusLabel.textContent=used==='1'
    ?'Bônus de 10% aplicado (limitado a 15 pontos).'
    :used==='2'?'Sem bônus: duas câmeras utilizadas.':'Selecione as câmeras utilizadas para calcular o bônus.';
  if(!fastForm)return;
  const observations=['A1','A2','A3','D1','D2'].map(k=>fastForm.querySelector('input[name="'+k+'"]:checked'));
  const completed=observations.filter(Boolean).length;
  const scoresCompleted=selected.filter(Boolean).length;
  const obsCount=fastForm.querySelector('[data-obs-count]');
  if(obsCount)obsCount.textContent=completed+'/5';
  const scoreCount=fastForm.querySelector('[data-score-count]');
  if(scoreCount)scoreCount.textContent=scoresCompleted+'/3';

  const complete=completed===5&&scoresCompleted===3&&!!fastForm.querySelector('input[name="available"]:checked')&&!!fastForm.querySelector('input[name="used"]:checked');
  const progress=document.querySelector('#quick-form-progress');
  if(progress)progress.textContent=complete?'Ficha preenchida · confira e salve':'Selecione 5 participantes, 3 notas e câmeras';
}
function quickFormSignature(form){
  const d=new FormData(form);
  return [...d.entries()].map(([k,v])=>k+'='+v).join('&');
}
if(fastForm){
  fastForm.addEventListener('change',()=>{
    updateTotal();
    if(savedSignature!==null&&quickFormSignature(fastForm)!==savedSignature){
      if(quickSaveStatus)quickSaveStatus.textContent='Alterações ainda não salvas';
      if(quickNext)quickNext.hidden=true;
    }
  });
  fastForm.addEventListener('input',()=>{
    if(savedSignature!==null&&quickFormSignature(fastForm)!==savedSignature){
      if(quickSaveStatus)quickSaveStatus.textContent='Alterações ainda não salvas';
      if(quickNext)quickNext.hidden=true;
    }
  });
  fastForm.addEventListener('submit',async(event)=>{
    event.preventDefault();
    updateTotal();
    if(saveInProgress||!fastForm.reportValidity())return;
    const used=Number(fastForm.querySelector('input[name="used"]:checked')?.value||0);
    const available=Number(fastForm.querySelector('input[name="available"]:checked')?.value||0);
    if(used>available){
      if(quickSaveStatus)quickSaveStatus.textContent='As câmeras usadas não podem exceder as disponíveis.';
      return;
    }
    saveInProgress=true;
    if(fastSaveButton){fastSaveButton.disabled=true;fastSaveButton.textContent='Salvando...';}
    if(quickSaveStatus)quickSaveStatus.textContent='Registrando avaliação...';
    try{
      const res=await fetch(fastForm.action,{
        method:'POST',
        body:new FormData(fastForm),
        credentials:'same-origin',
        headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'},
        cache:'no-store'
      });
      if(res.redirected)throw Error('Sessão expirada. Entre novamente.');
      const data=await res.json().catch(()=>({}));
      if(!res.ok||!data.ok)throw Error(data.error||'Não foi possível salvar; tente novamente.');
      savedSignature=quickFormSignature(fastForm);
      if(quickSaveStatus)quickSaveStatus.textContent='✓ Avaliação salva · '+new Date(data.saved_at).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
      if(quickNext)quickNext.hidden=false;
    }catch(error){
      if(quickSaveStatus)quickSaveStatus.textContent=error.message||'Erro de conexão. Tente novamente.';
    }finally{
      saveInProgress=false;
      if(fastSaveButton){fastSaveButton.disabled=false;fastSaveButton.textContent='Salvar avaliação ✓';}
    }
  });
}
updateTotal();

// Login visual: apenas selecionar o avaliador e informar sua senha.
const quickLogin=document.querySelector('#quick-login');
if(quickLogin){
  const username=quickLogin.elements.namedItem('username');
  const password=quickLogin.elements.namedItem('password');
  const tiles=[...quickLogin.querySelectorAll('[data-login-user]')];
  const selectedIdentity=document.querySelector('#selected-access-name');
  function selectQuickUser(name){
    if(username)username.value=name;
    const chosen=tiles.find(tile=>tile.dataset.loginUser===name);
    for(const tile of tiles){
      const active=tile.dataset.loginUser===name;
      tile.classList.toggle('selected',active);
      tile.setAttribute('aria-pressed',active?'true':'false');
    }
    if(selectedIdentity)selectedIdentity.textContent=chosen
      ?'Selecionado: '+chosen.dataset.loginIdentity
      :'Login informado: '+name;
    if(password)password.focus();
  }
  for(const tile of tiles)tile.addEventListener('click',()=>selectQuickUser(tile.dataset.loginUser));
  if(username&&username.value)selectQuickUser(username.value);
  username?.addEventListener('input',()=>{
    const chosen=tiles.find(tile=>tile.dataset.loginUser===username.value);
    for(const tile of tiles){
      const active=tile.dataset.loginUser===username.value;
      tile.classList.toggle('selected',active);
      tile.setAttribute('aria-pressed',active?'true':'false');
    }
    if(selectedIdentity)selectedIdentity.textContent=chosen
      ?'Selecionado: '+chosen.dataset.loginIdentity
      :(username.value?'Login informado: '+username.value:'Selecione seu nome antes de informar a senha.');
  });
  quickLogin.addEventListener('submit',event=>{
    if(!username?.value){
      event.preventDefault();
      const details=username.closest('details');
      if(details)details.open=true;
      username.focus();
    }
  });
}
// Para formulários: confirmar apenas no envio, nunca ao clicar num campo.
document.querySelectorAll('[data-confirm]').forEach(element=>{
  element.addEventListener(element.tagName==='FORM'?'submit':'click',event=>{
    if(!confirm(element.dataset.confirm))event.preventDefault();
  });
});
document.querySelector('[data-copy-credentials]')?.addEventListener('click',async e=>{const name=e.currentTarget.dataset.copyCredentials;const password=document.querySelector('#new-password')?.textContent||'';try{await navigator.clipboard.writeText(`NEXT 2026 — Acesso do avaliador\nUsuário: ${name}\nSenha: ${password}`);e.currentTarget.textContent='Dados copiados!'}catch{alert('Selecione e copie o identificador e a senha acima.')}});


// Quadro de classificação: consultas autenticadas a cada 3 segundos.
// Nenhuma senha ou chave Supabase é enviada ao navegador.
const rankingBody=document.querySelector('[data-ranking-body]');
const rankingPreview=document.querySelector('[data-ranking-preview]');
let rankingRequestActive=false;
function formatAverage(value){
  return typeof value==='number'&&Number.isFinite(value) ? value.toFixed(2).replace('.',',') : '—';
}
function rankCell(tr,selector,value){
  const node=tr.querySelector(selector);
  if(node)node.textContent=String(value);
}
async function pollRanking(){
  if((!rankingBody&&!rankingPreview)||rankingRequestActive)return;
  rankingRequestActive=true;
  const state=document.querySelector('[data-rank-connect]');
  try{
    const res=await fetch('/api/results',{credentials:'same-origin',cache:'no-store'});
    if(res.redirected||!res.ok)throw Error((res.status===401||res.status===403||res.redirected)?'Sessão expirada. Entre novamente.':'Não foi possível atualizar o ranking.');
    const data=await res.json();
    if(rankingBody){for(const item of data.ranking){
      const tr=rankingBody.querySelector('[data-ranking-team="'+item.team_id+'"]');
      if(!tr)continue;
      rankCell(tr,'[data-rank]',item.rank===null?'—':item.rank+'º');
      rankCell(tr,'[data-team-name]',item.name);
      rankCell(tr,'[data-stand]','Grupo '+String(item.team_id).padStart(2,'0')+' · '+item.stand);
      rankCell(tr,'[data-c1]',formatAverage(item.c1_average));
      rankCell(tr,'[data-c2]',formatAverage(item.c2_average));
      rankCell(tr,'[data-c3]',formatAverage(item.c3_average));
      rankCell(tr,'[data-average]',formatAverage(item.average));
      rankCell(tr,'[data-base-average]',formatAverage(item.base_average));
      rankCell(tr,'[data-cameras]',item.one_camera_evaluations+' / '+item.evaluations);
      rankCell(tr,'[data-votes]',item.evaluations+' / '+item.expected);
      rankCell(tr,'[data-completeness]',!item.evaluations?'Sem avaliações':(item.complete?'Todas recebidas':'Parcial'));
      rankCell(tr,'[data-lock]',item.locked?'Notas bloqueadas':'');
      const bar=tr.querySelector('[data-bar]');
      if(bar)bar.value=item.average===null?0:item.average;
      tr.classList.toggle('no-score',item.evaluations===0);
      rankingBody.appendChild(tr); // Mantém a ordem calculada pelo servidor.
    }}
    if(rankingPreview){
      const fragment=document.createDocumentFragment();
      for(const item of data.ranking){
        const row=document.createElement('div');
        row.className='preview-row'+(!item.evaluations?' no-score':'');
        const rank=document.createElement('strong');
        rank.textContent=item.rank===null?'—':item.rank+'º';
        const name=document.createElement('span');
        name.textContent=item.name+' · '+item.stand;
        const mean=document.createElement('b');
        mean.textContent=formatAverage(item.average)+' / 15';
        const votes=document.createElement('small');
        votes.textContent=item.evaluations+' / '+item.expected+' fichas · '+item.one_camera_evaluations+' com 1 câmera';
        row.append(rank,name,mean,votes);
        fragment.appendChild(row);
      }
      rankingPreview.replaceChildren(fragment);
    }
    rankCell(document,'[data-expected-judges]',data.expected_judges);
    const stamp=document.querySelector('[data-ranking-updated]');
    if(stamp)stamp.textContent='Atualizado às '+new Date(data.updated_at).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    if(state)state.textContent='Conectado · atualização a cada 3 segundos';
  }catch(error){
    if(state)state.textContent=error.message||'Falha de atualização. Tentando novamente...';
  }finally{
    rankingRequestActive=false;
  }
}
if(rankingBody||rankingPreview){
  pollRanking();
  setInterval(pollRanking,3000);
}


// CONTINGENCIA: fotografar ficha offline; ler bolinhas; confirmar manualmente.
// A imagem e enviada ao Supabase Storage privado, nunca ha importacao automatica
// sem confirmacao explicita da coordenacao.
const scanForm=document.querySelector('#manual-scan');
const confirmForm=document.querySelector('#manual-confirm');
if(scanForm&&confirmForm){
  const scanStatus=document.querySelector('#manual-scan-status');
  const scanButton=document.querySelector('#manual-scan-button');
  const preview=document.querySelector('#manual-preview');
  const review=document.querySelector('#manual-review');
  const findings=document.querySelector('#manual-findings');
  const pair=document.querySelector('#manual-pair');
  const saveStatus=document.querySelector('#manual-save-status');
  const saveButton=document.querySelector('#manual-confirm-button');
  const replaceCheckbox=document.querySelector('#manual-replace');
  const replaceWrap=document.querySelector('#manual-replace-wrap');
  let previewURL=null;
  const setState=(node,value)=>{if(node)node.textContent=value;};
  replaceCheckbox?.addEventListener('change',()=>{
    if(replaceWrap)replaceWrap.hidden=!replaceCheckbox.checked;
    const input=replaceWrap?.querySelector('input[name="replace_confirmation"]');
    if(input)input.required=replaceCheckbox.checked;
  });
  scanForm.addEventListener('submit',async event=>{
    event.preventDefault();
    const file=scanForm.querySelector('input[type="file"]')?.files?.[0];
    if(!file){setState(scanStatus,'Selecione a fotografia da ficha.');return;}
    if(file.size>8*1024*1024){setState(scanStatus,'Foto maior que 8 MB.');return;}
    if(previewURL)URL.revokeObjectURL(previewURL);
    previewURL=URL.createObjectURL(file);
    if(preview){preview.src=previewURL;preview.hidden=false;}
    if(review)review.hidden=true;
    setState(scanStatus,'Analisando marcações e guardando comprovante...');
    scanButton.disabled=true;
    try{
      const res=await fetch(scanForm.action,{
        method:'POST',body:new FormData(scanForm),credentials:'same-origin',
        headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'},
        cache:'no-store'
      });
      if(res.redirected)throw Error('Sessão encerrada. Entre novamente.');
      const result=await res.json().catch(()=>({}));
      if(!res.ok||!result.ok)throw Error(result.error||'Falha ao ler fotografia.');
      confirmForm.reset();
      for(const name of ['token','group','judge']){
        const field=confirmForm.elements.namedItem(name);
        if(field)field.value=name==='token'?result.token:scanForm.elements.namedItem(name)?.value||'';
      }
      for(const [key,val] of Object.entries(result.answers||{})){
        if(val===null||val===undefined)continue;
        const control=confirmForm.elements.namedItem(key);
        if(control&&control.tagName==='SELECT')control.value=String(val);
      }
      if(replaceWrap)replaceWrap.hidden=true;
      setState(pair,result.group+' · '+result.judge);
      setState(findings,result.recognized+'/'+result.total+' campos reconhecidos. '+
         (result.warnings?.length?'Revise manualmente: '+result.warnings.join('; '):'Todas as marcações foram lidas; confira visualmente antes de salvar.'));
      setState(scanStatus,'Leitura concluída. Confira os campos antes de contabilizar.');
      if(review){review.hidden=false;review.scrollIntoView({behavior:'smooth',block:'start'});}
    }catch(err){
      setState(scanStatus,err.message||'Falha ao analisar. Confira a internet e tente novamente.');
    }finally{scanButton.disabled=false;}
  });
  confirmForm.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!confirmForm.reportValidity())return;
    if(!confirm('Conferiu visualmente a fotografia e todos os campos antes de contabilizar?'))return;
    saveButton.disabled=true;
    setState(saveStatus,'Gravando avaliação no ranking...');
    try{
      const res=await fetch(confirmForm.action,{
        method:'POST',body:new FormData(confirmForm),
        credentials:'same-origin',cache:'no-store',
        headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
      });
      if(res.redirected)throw Error('Sessão expirada. Entre novamente.');
      const result=await res.json().catch(()=>({}));
      if(!res.ok||!result.ok)throw Error(result.error||'Não foi possível contabilizar.');
      setState(saveStatus,'✓ Nota ponderada '+result.adjusted_total+'/15 (técnica '+result.total+
         '/15) de '+result.judge+' para '+result.group+' contabilizada no ranking. Comprovante salvo.');
      saveButton.disabled=true; // impedir segunda importacao do mesmo comprovante
    }catch(err){
      setState(saveStatus,err.message||'Falha ao registrar. Confira a conexão.');
      saveButton.disabled=false;
    }
  });
}
