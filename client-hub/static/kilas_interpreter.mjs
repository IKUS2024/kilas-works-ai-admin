import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=translator-auth-20261031';
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-reliable-20261023';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-reliable-20261023';
import {MicrophoneMeter} from './kilas_interpreter_meter.mjs?v=mic-wave-20261110';
import {CallSession} from './kilas_interpreter_engine.mjs?v=mic-wave-20261110';
const root=document.querySelector('#interpreter');
if(root){
 const field=id=>root.querySelector('#interpreter-'+id),left=field('left'),right=field('right'),orb=field('orb'),end=field('end'),consent=field('consent');
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
  if(pair&&(pair.a!==a.value||pair.b!==b.value)){
   const selectedRight=selectedSource===pair.b;
   ++generation;switching=false;session.end();clearTranscript();
   pair={a:a.value,b:b.value};selectedSource=selectedRight?pair.b:pair.a;
  }else if(!pair){pair={a:a.value,b:b.value};selectedSource=pair.a;}
  previousPair=[a.value,b.value];
  for(const select of [a,b]){select.dataset.language=select.value;select.title=select.selectedOptions[0].textContent;let full=select.parentNode.querySelector('.reference-language-full');if(!full){full=document.createElement('span');full.className='reference-language-full';full.setAttribute('aria-hidden','true');select.after(full);}full.textContent=select.title;full.hidden=select.title.length<22;}
  savePair();sync();
 };
 const request=(url,options={})=>requestJSON(url,{csrf:root.querySelector('[name=csrf_token]').value,...options});
 let active=true,pair=null,context=null,side=null,selectedSource=null,switching=false,generation=0,recoveryTimer=null,authExpired=false,lastState='ended',newTranscript=true;
 const sync=()=>{
  for(const control of [a,b])control.disabled=authExpired;end.disabled=false;
  const names=code=>code===pair?.a?a.selectedOptions[0].text:b.selectedOptions[0].text;
  const recording=side!==null&&!['ended','idle'].includes(session.state)&&!session.finishRequested;
  const processing=!['ended','idle'].includes(session.state)&&(session.finishRequested||session.speaking);
  orb.disabled=!active||switching||authExpired||processing;
  orb.setAttribute('aria-pressed',String(recording));
  orb.setAttribute('aria-busy',String(switching||processing));
  orb.setAttribute('aria-label',processing?t(session.speaking?'Terjemahan diputar. Tunggu giliran.':'Menerjemahkan'):recording?t('Hentikan dan terjemahkan'):t('Mulai mendengarkan {source} ke {target}',{source:names(selectedSource||pair?.a),target:names(selectedSource===pair?.b?pair?.a:pair?.b)}));
  if(pair)field('current-direction').textContent=names(selectedSource)+' → '+names(selectedSource===pair.a?pair.b:pair.a);
  for(const [button,source,target] of [[left,pair?.a,pair?.b],[right,pair?.b,pair?.a]]){
   button.disabled=!active||authExpired;
   button.setAttribute('aria-pressed',String(source===selectedSource&&selectedSource!==null));
   button.dataset.selected=String(source===selectedSource&&selectedSource!==null);button.closest('.interpreter-language-card').dataset.selected=button.dataset.selected;
   if(pair)button.setAttribute('aria-label',t('Pilih arah bicara')+': '+names(source)+' → '+names(target));
  }
 };
 const messages={
  language_adjusted:'Bahasa yang sama telah disesuaikan.',call_provider_quota:'Kuota Gemini sedang tidak tersedia.',call_provider_billing:'Periksa billing akun Gemini.',
  consent_required:'Setujui pemrosesan ucapan terlebih dahulu.',same_language:'Pilih bahasa sumber dan tujuan yang berbeda.',call_settings_invalid:'Pilih bahasa dari daftar yang tersedia.',
  budget_limit:'Batas biaya Translator tercapai.',account_credit_limit:'Batas biaya Translator tercapai.',already_processing:'Sesi sebelumnya belum selesai. Tunggu sebentar lalu pilih arah lagi.',attempt_limit:'Batas sesi tercapai. Coba lagi nanti.',service_busy:'Translator sedang sibuk. Coba lagi sebentar.',
  call_unavailable:'Translator sedang tidak tersedia.',auth_required:'Sesi akun berakhir. Masuk kembali.',
  microphone_permission_denied:'Izinkan mikrofon di browser.',microphone_permission_timeout:'Periksa izin mikrofon browser, lalu pilih arah lagi.',
  microphone_unavailable:'Periksa mikrofon yang terhubung, lalu pilih arah lagi.',realtime_capture_unavailable:'Browser ini belum mendukung input suara. Gunakan browser yang mendukung mikrofon dan AudioWorklet.',
  realtime_input_timeout:'Mikrofon belum mengirim suara. Periksa perangkat, lalu pilih arah lagi.',realtime_capture_failed:'Input suara terputus. Periksa mikrofon, lalu pilih arah lagi.',realtime_module_timeout:'Input audio belum dimuat. Periksa koneksi, lalu pilih arah lagi.',
  audio_resume:'Audio belum siap. Izinkan audio browser, lalu pilih arah lagi.',call_audio:'Audio belum siap. Izinkan audio browser, lalu pilih arah lagi.',
  call_backlog:'Audio tertunda. Periksa koneksi, lalu pilih arah lagi.',request_timeout:'Koneksi belum merespons. Periksa jaringan, lalu pilih arah lagi.',
  response_invalid:'Layanan belum merespons dengan benar. Coba lagi sebentar.',call_protocol:'Layanan belum merespons dengan benar. Coba lagi sebentar.',
  call_input_invalid:'Audio belum selesai dikirim. Periksa koneksi, lalu pilih arah lagi.',call_output_invalid:'Layanan belum merespons dengan benar. Coba lagi sebentar.',
  call_transport:'Koneksi suara terputus. Periksa mikrofon dan jaringan, lalu pilih arah lagi.',
  call_ended:'Sesi berakhir.',call_network:'Koneksi terputus. Pilih arah untuk mulai lagi.',call_provider:'Gemini menghentikan sesi.',call_provider_disconnected:'Koneksi Gemini terputus.'
 };
 const showError=code=>{
  const message=t(messages[code]||'Sesi terhenti. Pilih arah untuk mulai lagi.');
  field('error').hidden=!['consent_required','language_adjusted'].includes(code);field('error').textContent=message;
  if(active){field('state').dataset.state='error';field('state').textContent=message;}
  if(code==='auth_required'){authExpired=true;field('login').hidden=false;sync();field('login').focus();}
 };
 // Latest utterance only, in DOM memory; never localStorage, history or a new provider request.
 const clearTranscript=()=>{
  for(const kind of ['original','caption']){field(kind).textContent='';field(kind+'-wrap').hidden=true;}
  field('transcript-empty').hidden=false;newTranscript=true;
 };
 const caption=(kind,text)=>{
  if(!text)return; // End/error must not discard a useful already-received translation.
  if(newTranscript){clearTranscript();newTranscript=false;}
  if(field(kind).textContent!==text)field(kind).textContent=text;
  field(kind+'-wrap').hidden=false;field('transcript-empty').hidden=true;
 };
 const meter=new MicrophoneMeter({element:field('microphone')});
 const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
 const player=new CallPlayer({getContext:()=>context,onError:()=>session.fail({code:'call_audio'})});
 const stopAudio=()=>{clearTimeout(recoveryTimer);recoveryTimer=null;const own=context;context=null;if(own)own.close().catch(()=>{});};
 const openAudio=()=>{
  const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Object.assign(Error(),{code:'call_audio'});
  try{context=new Audio({latencyHint:'playback'});}catch{throw Object.assign(Error(),{code:'call_audio'});}const own=context;
  own.addEventListener('statechange',()=>{
   if(context!==own||session.state==='ended')return;
   if(own.state==='running'){clearTimeout(recoveryTimer);recoveryTimer=null;player.resume();return;}
   player.suspend();if(!recoveryTimer)recoveryTimer=setTimeout(()=>{if(context===own&&own.state!=='running')session.fail({code:'call_audio'});},3500);
   if(own.state==='suspended')own.resume().catch(()=>{});
  });
  return new Promise((resolve,reject)=>{
   const failed=()=>{clearTimeout(timeout);reject(Object.assign(Error(),{code:'call_audio'}));};
   const timeout=setTimeout(failed,3500);
   try{Promise.resolve(own.resume()).then(()=>{clearTimeout(timeout);resolve();},failed);}catch{failed();}
  });
 };
 const session=new CallSession({request,capture,player,stopAudio,prepare:()=>context?context.resume():Promise.reject(Object.assign(Error(),{code:'call_audio'})),
  onLevel:rms=>meter.update(rms),onState:state=>{
   if(['connecting','starting'].includes(state))clearTranscript();
   if(state==='listening'&&lastState==='speaking')newTranscript=true;
   field('state').dataset.state=state;
   field('state').textContent=t({idle:'Siap · mikrofon belum aktif',starting:'Menyiapkan mikrofon…',ended:'Siap · mikrofon belum aktif',connecting:'Menghubungkan…',listening:'Terhubung · mendengarkan',processing:'Menerjemahkan',speaking:'Terjemahan diputar. Tunggu giliran.',reconnecting:'Menghubungkan kembali…'}[state]||'Pilih arah bicara');
   field('orb').dataset.state=state==='speaking'?'playing':['connecting','reconnecting','processing','starting'].includes(state)?'processing':['ended','idle'].includes(state)?'idle':'listening';
   if(['ended','idle'].includes(state))side=null;lastState=state;sync();
  },onText:text=>caption('caption',text),onOriginal:text=>caption('original',text),onError:showError});
 function chooseDirection(source){
  if(!active||authExpired||source===selectedSource)return;
  // Switching direction cancels the old turn immediately, even during setup or
  // playback. A future start still awaits its server cancellation before admission.
  ++generation;switching=false;session.end();clearTranscript();
  selectedSource=source;sync();
 }
 async function toggleRecording(){
  const source=selectedSource||pair?.a;
  if(!active||switching||authExpired)return;
  if(!consent.checked){field('consent-panel').hidden=false;consent.focus();showError('consent_required');return;}
  if(side===source&&!['ended','idle'].includes(session.state)){session.finish();sync();return;}
  if(session.state==='idle'){side=source;void session.start();sync();return;}
  selectedSource=source;
  const ticket=++generation;switching=true;session.end();clearTranscript();field('error').hidden=true;sync();
  try{
   // Resume audio in this click, before waiting for the old server End ACK.
   const audio=openAudio();await Promise.all([audio,session.ending]);
   if(ticket!==generation){return;}
   const target=source===pair.a?pair.b:pair.a;
   field('original').lang=source;field('caption').lang=target;
   side=source;switching=false;sync();void session.start({source,target,consent:consent.checked,turn_mode:'tap',reuse_session:true});
  }catch(error){if(ticket===generation){switching=false;session.end();showError(error.code||'call_network');sync();}}
 }
 orb.addEventListener('click',toggleRecording);
 left.addEventListener('click',()=>chooseDirection(pair.a));right.addEventListener('click',()=>chooseDirection(pair.b));
 consent.checked=false; // Never restore browser-form state as processing permission.
 consent.addEventListener('change',()=>{field('error').hidden=true;if(!consent.checked)suspend();else if(session.state==='ended'){field('state').dataset.state='ended';field('state').textContent=t('Siap · mikrofon belum aktif');}sync();});
 for(const name of ['language-a','language-b'])field(name).addEventListener('change',()=>updatePair(name));
 // Backgrounding, navigation and explicit End stop capture immediately.
 const suspend=()=>{const interrupted=switching||!['ended','idle'].includes(session.state);++generation;switching=false;session.end();sync();if(active&&interrupted)field('state').textContent=t('Sesi berakhir.')+' '+t('Ketuk logo K untuk mendengarkan. Ketuk lagi untuk berhenti dan terjemahkan.');};
 const close=()=>{suspend();consent.checked=false;clearTranscript();field('transcript').open=false;field('error').hidden=true;field('consent-panel').hidden=true;sync();if(authExpired)showError('auth_required');else orb.focus();};
 end.addEventListener('click',close);window.addEventListener('pagehide',suspend);document.addEventListener('visibilitychange',()=>{if(document.hidden)suspend();});
 // A history-cache restore never resumes recording or silently restores consent.
 window.addEventListener('pageshow',event=>{if(event.persisted)close();});
 updatePair('language-b',restoredEqual);
}
