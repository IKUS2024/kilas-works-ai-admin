import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-reliable-20261023';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-reliable-20261023';
import {CallSession} from './kilas_interpreter_engine.mjs?v=interpreter-1';
const root=document.querySelector('#interpreter');
if(root){
 const field=id=>root.querySelector('#interpreter-'+id),left=field('left'),right=field('right'),end=field('end'),consent=field('consent');
 // Keep only this account's explicit language choices; never persist consent/audio.
 const a=field('language-a'),b=field('language-b');let restoredEqual=false;let previousPair=[a.value,b.value];
 try{
  const names=new Intl.DisplayNames([document.documentElement.lang||'en'],{type:'language',fallback:'none'});
  for(const select of [a,b])for(const option of select.options){try{const name=names.of(option.value);if(name&&name.toLowerCase()!==option.value.toLowerCase())option.textContent=name;}catch{}}
 }catch{}
 try{
  const saved=JSON.parse(localStorage.getItem(root.dataset.preferenceKey));
  if(saved&&[a,b].every((select,i)=>Array.from(select.options).some(option=>option.value===saved[i]))){a.value=saved[0];b.value=saved[1];restoredEqual=saved[0]===saved[1];}
 }catch{}
 const savePair=()=>{try{localStorage.setItem(root.dataset.preferenceKey,JSON.stringify([a.value,b.value]));}catch{}};
 const updatePair=(changed,notify=true)=>{
  if(a.value===b.value){
   const select=changed==='language-a'?a:b,other=select===a?b:a;
   const candidates=[previousPair[select===a?0:1],'en','id',...Array.from(select.options,option=>option.value)];
   select.value=candidates.find(code=>code!==other.value&&Array.from(select.options).some(option=>option.value===code));
   if(notify)showError('language_adjusted');
  }
  for(const [select,other] of [[a,b],[b,a]])for(const option of select.options)option.disabled=option.value===other.value;
  previousPair=[a.value,b.value];
  for(const select of [a,b]){select.dataset.language=select.value;select.title=select.selectedOptions[0].textContent;let full=select.parentNode.querySelector('.reference-language-full');if(!full){full=document.createElement('span');full.className='reference-language-full';full.setAttribute('aria-hidden','true');select.after(full);}full.textContent=select.title;full.hidden=select.title.length<22;}
  savePair();sync();
 };
 const request=(url,options={})=>requestJSON(url,{csrf:root.querySelector('[name=csrf_token]').value,...options});
 let active=false,pair=null,context=null,side=null,switching=false,generation=0,recoveryTimer=null;
 const sync=()=>{left.disabled=right.disabled=!active||switching;end.disabled=false;left.setAttribute('aria-pressed',String(side===pair?.a));right.setAttribute('aria-pressed',String(side===pair?.b));};
 const directionLabel=(button,source,target)=>{const from=document.createElement('span'),arrow=document.createElement('span'),to=document.createElement('span');from.textContent=source;arrow.textContent=' → ';arrow.className='interpreter-arrow';to.textContent=target;button.replaceChildren(from,arrow,to);};
 const enter=()=>{if(active)return;if(!consent.checked){consent.focus();showError('consent_required');return;}if(field('language-a').value===field('language-b').value){showError('same_language');return;}pair={a:field('language-a').value,b:field('language-b').value};directionLabel(left,a.selectedOptions[0].text,b.selectedOptions[0].text);directionLabel(right,b.selectedOptions[0].text,a.selectedOptions[0].text);for(const [button,source,target] of [[left,pair.a,pair.b],[right,pair.b,pair.a]]){button.firstElementChild.dataset.language=source;button.lastElementChild.dataset.language=target;}active=true;field('state').dataset.state='idle';field('setup').hidden=true;field('active').hidden=false;field('error').hidden=true;sync();};
 const messages={language_adjusted:'Bahasa yang sama telah disesuaikan.',call_provider_quota:'Kuota Gemini sedang tidak tersedia.',call_provider_billing:'Periksa billing akun Gemini.',consent_required:'Setujui pemrosesan ucapan terlebih dahulu.',same_language:'Pilih bahasa sumber dan tujuan yang berbeda.',budget_limit:'Batas biaya Translator tercapai.',already_processing:'Sesi sebelumnya belum selesai. Tunggu sebentar lalu pilih arah lagi.',attempt_limit:'Batas sesi tercapai. Coba lagi nanti.',call_unavailable:'Translator sedang tidak tersedia.',microphone_permission_denied:'Izinkan mikrofon di browser.',call_audio:'Audio belum siap. Periksa izin audio.',call_ended:'Sesi berakhir.',call_network:'Koneksi terputus. Pilih arah untuk mulai lagi.',call_provider:'Gemini menghentikan sesi.',call_provider_disconnected:'Koneksi Gemini terputus.'};
 const showError=code=>{const message=t(messages[code]||'Sesi terhenti. Pilih arah untuk mulai lagi.');field('error').hidden=active;field('error').textContent=message;if(active){field('state').dataset.state='error';field('state').textContent=message;}};
 const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
 const player=new CallPlayer({getContext:()=>context,onError:()=>session.fail({code:'call_audio'})});
 const stopAudio=()=>{clearTimeout(recoveryTimer);recoveryTimer=null;const own=context;context=null;if(own)own.close().catch(()=>{});};
 const openAudio=()=>{
  const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Object.assign(Error(),{code:'call_audio'});
  context=new Audio({latencyHint:'playback'});const own=context;
  own.addEventListener('statechange',()=>{
   if(context!==own||session.state==='ended')return;
   if(own.state==='running'){clearTimeout(recoveryTimer);recoveryTimer=null;player.resume();return;}
   player.suspend();if(!recoveryTimer)recoveryTimer=setTimeout(()=>{if(context===own&&own.state!=='running')session.fail({code:'call_audio'});},3500);
   if(own.state==='suspended')own.resume().catch(()=>{});
  });
  return new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Object.assign(Error(),{code:'call_audio'})),3500);Promise.resolve(own.resume()).then(()=>{clearTimeout(timeout);resolve();},error=>{clearTimeout(timeout);reject(error);});});
 };
 const session=new CallSession({request,capture,player,stopAudio,prepare:()=>context?.state==='running'?Promise.resolve():Promise.reject(Object.assign(Error(),{code:'call_audio'})),
  onState:state=>{field('state').dataset.state=state;field('state').textContent=t({ended:'Pilih arah bicara',connecting:'Menghubungkan…',listening:'Mendengarkan',speaking:'Menerjemahkan',reconnecting:'Menghubungkan kembali…'}[state]||state);field('orb').dataset.state=state==='speaking'?'playing':state==='connecting'||state==='reconnecting'?'processing':state==='ended'?'idle':'listening';if(state==='ended')side=null;sync();},onError:showError});
 async function select(source){
  if(!active||switching||!consent.checked||(side===source&&session.state!=='ended'))return;
  const ticket=++generation;switching=true;session.end();field('error').hidden=true;sync();
  try{
   // Resume audio in this click, before waiting for the old server End ACK.
   const audio=openAudio();await Promise.all([audio,session.ending]);
   if(ticket!==generation){return;}
   side=source;switching=false;sync();void session.start({source,target:source===pair.a?pair.b:pair.a,consent:true});
  }catch(error){if(ticket===generation){switching=false;session.end();showError(error.code||'call_network');sync();}}
 }
 left.addEventListener('click',()=>select(pair.a));right.addEventListener('click',()=>select(pair.b));consent.addEventListener('change',sync);field('start').addEventListener('click',enter);for(const name of ['language-a','language-b'])field(name).addEventListener('change',()=>updatePair(name));field('swap').addEventListener('click',()=>{const a=field('language-a'),b=field('language-b');[a.value,b.value]=[b.value,a.value];updatePair('language-b');});
 // Backgrounding stops capture immediately, but only explicit End leaves this screen.
 const suspend=()=>{++generation;switching=false;session.end();sync();};
 const close=()=>{suspend();active=false;field('error').hidden=true;field('setup').hidden=false;field('active').hidden=true;sync();};end.addEventListener('click',close);window.addEventListener('pagehide',suspend);document.addEventListener('visibilitychange',()=>{if(document.hidden)suspend();});updatePair('language-b',restoredEqual);
}
