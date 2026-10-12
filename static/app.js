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
