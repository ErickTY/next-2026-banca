'use strict';
const teamEls=[...document.querySelectorAll('[data-timer]')];
let lastState=null;
function labelStatus(s){return {idle:'Aguardando',running:'Em andamento',paused:'Pausado',finished:'Encerrado'}[s]||'—'}
function pad(n){return String(Math.floor(n)).padStart(2,'0')}
function displayRemaining(state){const delta=state.status==='running'?Math.max(0,Math.floor((Date.now()-state.started_at)/1000)):0;const remain=Math.max(0,state.duration-state.elapsed-delta);return `${pad(remain/60)}:${pad(remain%60)}`}
function updateTimers(){if(!lastState)return;for(const el of teamEls){const id=el.dataset.timer;const state=lastState.timers[id];if(!state)continue;let rem=displayRemaining(state);el.textContent=rem;el.classList.toggle('warning',rem==='00:00'||(Number(rem.split(':')[0])===0&&Number(rem.split(':')[1])<=30));const status=document.querySelector(`[data-timer-status="${id}"]`);if(status)status.textContent=labelStatus(state.status)}}
async function poll(){if(!teamEls.length)return;try{const res=await fetch('/api/state',{credentials:'same-origin',cache:'no-store'});if(res.ok){const data=await res.json();const diff=Date.now()-data.now;data.timers&&Object.values(data.timers).forEach(s=>{if(s.started_at)s.started_at+=diff});lastState=data;updateTimers()}}catch(e){/* next polling attempt */}}
if(teamEls.length){poll();setInterval(poll,2000);setInterval(updateTimers,250)}
function updateTotal(){const values=[1,2,3].map(i=>document.querySelector(`input[name="c${i}"]:checked`));const el=document.querySelector('#score-total');if(el)el.textContent=values.every(Boolean)?`${values.reduce((n,e)=>n+Number(e.value),0)} / 15`:'— / 15'}
document.querySelectorAll('input[type="radio"]').forEach(x=>x.addEventListener('change',updateTotal));
document.querySelectorAll('[data-confirm]').forEach(x=>x.addEventListener('click',e=>{if(!confirm(x.dataset.confirm))e.preventDefault()}));
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
    if(!res.ok)throw Error(res.status===403||res.redirected?'Sessão expirada. Entre novamente.':'Não foi possível atualizar o ranking.');
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
        votes.textContent=item.evaluations+' / '+item.expected+' fichas';
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
