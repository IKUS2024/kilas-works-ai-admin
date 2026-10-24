import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-reliable-20261023';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-reliable-20261023';
import {CallSession} from './kilas_interpreter_engine.mjs?v=interpreter-1';
const root=document.querySelector('#interpreter');
if(root){
 const field=id=>root.querySelector('#interpreter-'+id),left=field('left'),right=field('right'),end=field('end'),consent=field('consent');
 const request=(url,options={})=>requestJSON(url,{csrf:root.querySelector('[name=csrf_token]').value,...options});
 let context=null,side=null,switching=false,generation=0,recoveryTimer=null;
 const sync=()=>{left.disabled=right.disabled=!consent.checked||switching;end.disabled=!switching&&session.state==='ended';consent.disabled=switching||session.state!=='ended';left.setAttribute('aria-pressed',String(side==='id'));right.setAttribute('aria-pressed',String(side==='en'));};
 const messages={budget_limit:'Batas biaya Translator tercapai.',already_processing:'Sesi sebelumnya belum selesai. Tunggu sebentar lalu pilih arah lagi.',attempt_limit:'Batas sesi tercapai. Coba lagi nanti.',call_unavailable:'Translator sedang tidak tersedia.',microphone_permission_denied:'Izinkan mikrofon di browser.',call_audio:'Audio belum siap. Periksa izin audio.',call_ended:'Sesi berakhir.',call_network:'Koneksi terputus. Pilih arah untuk mulai lagi.',call_provider:'Gemini menghentikan sesi.',call_provider_disconnected:'Koneksi Gemini terputus.'};
 const showError=code=>{field('error').hidden=false;field('error').textContent=messages[code]||'Sesi terhenti. Pilih arah untuk mulai lagi.';};
 const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
 const player=new CallPlayer({getContext:()=>context,onError:()=>session.fail({code:'call_audio'})});
 // Scale only copied playback PCM; microphone and shared Call player are untouched.
 const push=player.push.bind(player);player.push=(raw,scope)=>{const gain=Number(field('volume').value)/100;if(gain===1)return push(raw,scope);const copy=raw.slice(),view=new DataView(copy.buffer);for(let at=0;at<copy.length;at+=2)view.setInt16(at,Math.round(view.getInt16(at,true)*gain),true);return push(copy,scope);};
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
  onText:text=>{field('caption').textContent=text;},onOriginal:text=>{field('original').textContent=text;},
  onState:state=>{field('state').textContent={ended:'Pilih arah bicara',connecting:'Menghubungkan…',listening:'Mendengarkan',speaking:'Menerjemahkan',reconnecting:'Menghubungkan kembali…'}[state]||state;if(state==='ended')side=null;sync();},onError:showError});
 async function select(source){
  if(switching||!consent.checked||(side===source&&session.state!=='ended'))return;
  const ticket=++generation;switching=true;session.end();field('error').hidden=true;field('original').textContent='';sync();
  try{
   // Resume audio in this click, before waiting for the old server End ACK.
   const audio=openAudio();await Promise.all([audio,session.ending]);
   if(ticket!==generation){return;}
   side=source;switching=false;sync();void session.start({source,target:source==='id'?'en':'id',consent:true});
  }catch(error){if(ticket===generation){switching=false;session.end();showError(error.code||'call_network');sync();}}
 }
 left.addEventListener('click',()=>select('id'));right.addEventListener('click',()=>select('en'));consent.addEventListener('change',sync);
 const close=()=>{++generation;switching=false;session.end();sync();};end.addEventListener('click',close);window.addEventListener('pagehide',close);document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});sync();
}
