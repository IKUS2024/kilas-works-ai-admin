import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-reliable-20261023';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-reliable-20261023';
import {CallSession} from './kilas_interpreter_engine.mjs?v=interpreter-1';
const root=document.querySelector('#interpreter');
if(root){
 const field=id=>root.querySelector('#interpreter-'+id),left=field('left'),right=field('right'),end=field('end'),consent=field('consent');
 const request=(url,options={})=>requestJSON(url,{csrf:root.querySelector('[name=csrf_token]').value,...options});
 let active=false,pair=null,context=null,side=null,switching=false,generation=0,recoveryTimer=null;
 const sync=()=>{left.disabled=right.disabled=!active||switching;end.disabled=false;left.setAttribute('aria-pressed',String(side===pair?.a));right.setAttribute('aria-pressed',String(side===pair?.b));};
 const enter=()=>{if(active)return;if(!consent.checked){consent.focus();showError('consent_required');return;}if(field('language-a').value===field('language-b').value){showError('same_language');return;}pair={a:field('language-a').value,b:field('language-b').value};left.textContent=field('language-a').selectedOptions[0].text+' → '+field('language-b').selectedOptions[0].text;right.textContent=field('language-b').selectedOptions[0].text+' → '+field('language-a').selectedOptions[0].text;active=true;field('setup').hidden=true;field('active').hidden=false;field('error').hidden=true;sync();};
 const messages={call_provider_quota:'Kuota Gemini sedang tidak tersedia.',call_provider_billing:'Periksa billing akun Gemini.',consent_required:'Setujui pemrosesan ucapan terlebih dahulu.',same_language:'Pilih bahasa sumber dan tujuan yang berbeda.',budget_limit:'Batas biaya Translator tercapai.',already_processing:'Sesi sebelumnya belum selesai. Tunggu sebentar lalu pilih arah lagi.',attempt_limit:'Batas sesi tercapai. Coba lagi nanti.',call_unavailable:'Translator sedang tidak tersedia.',microphone_permission_denied:'Izinkan mikrofon di browser.',call_audio:'Audio belum siap. Periksa izin audio.',call_ended:'Sesi berakhir.',call_network:'Koneksi terputus. Pilih arah untuk mulai lagi.',call_provider:'Gemini menghentikan sesi.',call_provider_disconnected:'Koneksi Gemini terputus.'};
 const showError=code=>{const message=t(messages[code]||'Sesi terhenti. Pilih arah untuk mulai lagi.');field('error').hidden=active;field('error').textContent=message;if(active)field('state').textContent=message;};
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
  return own.resume();
 };
 const session=new CallSession({request,capture,player,stopAudio,prepare:()=>context?.state==='running'?Promise.resolve():Promise.reject(Object.assign(Error(),{code:'call_audio'})),
  onState:state=>{field('state').textContent=t({ended:'Pilih arah bicara',connecting:'Menghubungkan…',listening:'Mendengarkan',speaking:'Menerjemahkan',reconnecting:'Menghubungkan kembali…'}[state]||state);field('orb').dataset.state=state==='speaking'?'playing':state==='connecting'||state==='reconnecting'?'processing':'listening';if(state==='ended')side=null;sync();},onError:showError});
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
 left.addEventListener('click',()=>select(pair.a));right.addEventListener('click',()=>select(pair.b));consent.addEventListener('change',sync);field('start').addEventListener('click',enter);for(const name of ['language-a','language-b'])field(name).addEventListener('change',sync);field('swap').addEventListener('click',()=>{const a=field('language-a'),b=field('language-b');[a.value,b.value]=[b.value,a.value];sync();});
 // Backgrounding stops capture immediately, but only explicit End leaves this screen.
 const suspend=()=>{++generation;switching=false;session.end();sync();};
 const close=()=>{suspend();active=false;field('error').hidden=true;field('setup').hidden=false;field('active').hidden=true;sync();};end.addEventListener('click',close);window.addEventListener('pagehide',suspend);document.addEventListener('visibilitychange',()=>{if(document.hidden)suspend();});sync();
}
