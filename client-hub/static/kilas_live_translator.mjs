import {VoiceRecorder} from './kilas_transcription_recorder.mjs?v=lifecycle-20261012';
import {TranslatorSession} from './kilas_live_translator_engine.mjs?v=bounded-audio-20261012';
import {TranslatorPlayback} from './kilas_live_translator_playback.mjs?v=bounded-audio-20261012';
import {syncLanguagePair,validLanguagePair} from './kilas_live_translator_languages.mjs?v=pair-layout-20261012';
import {TranslatorRecovery} from './kilas_live_translator_recovery.mjs?v=owner-recovery-20261012';
const root=document.querySelector('.kilas-live-translator');
if(root){
 const form=document.querySelector('#live-setup-form'),setup=document.querySelector('#live-setup'),active=document.querySelector('#live-active'),orb=active.querySelector('.kilas-live-orb'),error=document.querySelector('#live-error');
 const csrf=form.querySelector('[name=csrf_token]').value,start=form.querySelector('button');let context=null,source=null,analyser=null,interval=null,recorder=null;
 const setupReady=root.dataset.ready==='true'&&!start.disabled;
 const showError=text=>{error.textContent=text;error.hidden=false;};
 let recovery=null,recoverRequested=false,recoveryError=false,recoveryExpiry=null;
 const recoveryPanel=document.querySelector('#live-recovery'),recoveryStatus=document.querySelector('#live-recovery-status'),recoveryEnd=document.querySelector('#live-recovery-end'),recoveryCheck=document.querySelector('#live-recovery-check');
 const recoveryRetry=document.querySelector('#live-recovery-retry'),sessionStatus=document.querySelector('#live-session-status');
 const languageA=form.elements.language_a,languageB=form.elements.language_b;
 const syncLanguages=(changed=languageA)=>syncLanguagePair(languageA,languageB,changed);
 languageA.addEventListener('change',()=>syncLanguages(languageA));
 languageB.addEventListener('change',()=>syncLanguages(languageB));
 window.addEventListener('pageshow',()=>{syncLanguages();recovery?.refresh();});
 form.addEventListener('reset',()=>queueMicrotask(()=>syncLanguages()));
 syncLanguages();
 function monitorStop(){if(interval!==null)clearInterval(interval);interval=null;source?.disconnect();source=null;analyser?.disconnect();analyser=null;}
 const capture={
  async start({level,blob,error:onError}){
   if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder||!context)throw Error('Browser ini belum mendukung mikrofon.');
   recorder=new VoiceRecorder({mediaDevices:navigator.mediaDevices,Recorder:window.MediaRecorder,onBlob:raw=>{monitorStop();blob(raw);},onState:state=>{if(state==='empty'){monitorStop();blob(new Blob([]));}if(state==='error')onError(Error('Mikrofon terputus. Periksa izin browser lalu mulai kembali.'));}});
   const own=recorder;await own.start({userGesture:true,consent:true,enabled:true});
   if(own!==recorder||!own.stream)return;
   source=context.createMediaStreamSource(own.stream);analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
   const samples=new Float32Array(analyser.fftSize);let began=performance.now(),heard=false;
   interval=setInterval(()=>{if(!analyser)return;analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);if(rms>=.015)heard=true;level(rms);
    // Silence never dispatches STT. A continuous/idle recording has a bounded lifetime.
    if(performance.now()-began>=60000)onError(Error(heard?'Ucapan terlalu panjang. Akhiri kalimat dengan jeda lalu mulai kembali.':'Tidak ada ucapan terbaca. Mulai kembali saat siap.'));
   },50);
  },
  finalize(){monitorStop();recorder?.stop();},
  cancel(){monitorStop();recorder?.cancel();recorder=null;},
 };
 const player=new TranslatorPlayback({getContext:()=>context});
 const playback={prepare:(...args)=>player.prepare(...args),play:(...args)=>player.play(...args),
  stop(){player.cancel();const own=context;context=null;if(own){try{own.close().catch(()=>{});}catch{}}},
 };
 async function json(url,options={}){
  const {timeoutMs,...requestOptions}=options,controller=timeoutMs?new AbortController():null;
  const timer=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
  try{
   const response=await fetch(url,{...requestOptions,...(controller?{signal:controller.signal}:{}),credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':csrf}});
   if(response.redirected)throw Error('Sesi akun berakhir. Masuk kembali.');
   let body;try{body=await response.json();}catch{throw Error('Layanan belum tersedia. Mulai kembali bila jaringan siap.');}
   if(!response.ok){if(body.code==='session_busy'){recoverRequested=true;recoveryError=true;}const failure=Error(body.error||'Layanan belum tersedia.');failure.code=body.code;throw failure;}return body;
  }finally{if(timer!==null)clearTimeout(timer);}
 }
 const pause=signal=>new Promise((resolve,reject)=>{const cancel=()=>{clearTimeout(timer);reject(new DOMException('Ended','AbortError'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},500);signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();});
 const api={
  start:(data,signal)=>json('/kilas-translator/live/sessions',{method:'POST',body:data,signal}),
  async turn(id,key,blob,signal){
   const url='/kilas-translator/live/sessions/'+id+'/turns/'+key,data=new FormData();data.append('recording',blob,'recording');data.append('csrf_token',csrf);
   await json(url,{method:'POST',body:data,signal});const deadline=performance.now()+180000;
   while(!signal.aborted){const result=await json(url,{signal});if(result.status==='COMPLETED')return result;if(result.status==='FAILED'){const e=Error(result.error);if(result.recoverable)e.code='no_speech';throw e;}if(result.status==='CANCELLED')throw Error('Sesi sudah berakhir.');if(performance.now()>deadline)throw Error('Pemrosesan belum selesai. Sesi dihentikan; tidak diulang otomatis.');await pause(signal);}
   throw new DOMException('Ended','AbortError');
  },
  end:id=>recovery.endKnown(id),
 };
 const session=new TranslatorSession({api,capture,playback,key:()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join(''),onError:showError,onResult:result=>{
  const text=document.querySelector('#live-translation');text.textContent=result.translated_text||'';text.hidden=!text.textContent;
 },onState:state=>{
  start.disabled=state!=='ended'||!setupReady||!recovery?.canStart();setup.hidden=state!=='ended';active.hidden=state==='ended';orb.dataset.state=state;orb.setAttribute('aria-label',state==='starting'?'Menyiapkan sesi':state==='playing'?'Memutar terjemahan':state==='listening'?'Mendengarkan':'Memproses');
  document.querySelector('#live-state').textContent=orb.getAttribute('aria-label');
  if(state==='ended'&&recoverRequested){recoverRequested=false;recovery.refresh();}
 }});
 recovery=new TranslatorRecovery({api:{active:()=>json('/kilas-translator/live/sessions/active',{timeoutMs:10000}),end(id){const data=new FormData();data.append('csrf_token',csrf);return json('/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/end',{method:'POST',body:data,keepalive:true,timeoutMs:10000});}},isIdle:()=>session.state==='ended',onError:text=>{recoveryError=true;showError(text);},onChange:state=>{
  start.disabled=session.state!=='ended'||!setupReady||!state.canStart();
  const confirmedActive=Boolean(state.active)&&(state.checked||state.ending),idle=session.state==='ended';
  recoveryPanel.hidden=!idle||!confirmedActive;
  // Keep initial checks in the existing Start control; no conflict panel or form shift.
  start.textContent=state.pending&&!confirmedActive?'Memeriksa sesi...':'Start';
  start.setAttribute?.('aria-busy',String(state.pending));
  sessionStatus.textContent=idle&&state.pending&&!confirmedActive?'Memeriksa sesi...':'';
  recoveryRetry.hidden=!idle||state.pending||state.checked||confirmedActive;
  recoveryEnd.hidden=!state.active;recoveryEnd.disabled=state.pending;recoveryCheck.disabled=state.pending;
  recoveryStatus.textContent=state.ending?'Mengakhiri sesi sebelumnya...':state.pending?'Memeriksa sesi...':state.active?'Sesi sebelumnya masih aktif.'+(state.active.processing?' Ada ucapan yang masih diproses.':''):'Status sesi belum terverifikasi. Periksa sesi saat jaringan siap.';
  if(state.canStart()&&recoveryError){error.hidden=true;recoveryError=false;}
  if(recoveryExpiry!==null){clearTimeout(recoveryExpiry);recoveryExpiry=null;}
  if(session.state==='ended'&&!state.pending&&state.active?.expires_in_seconds>0)recoveryExpiry=setTimeout(()=>recovery.refresh(),state.active.expires_in_seconds*1000);
 }});
 recoveryEnd.addEventListener('click',()=>recovery.endPrevious());recoveryCheck.addEventListener('click',()=>recovery.refresh());recoveryRetry.addEventListener('click',()=>recovery.refresh());
 window.addEventListener('online',()=>recovery.refresh());recovery.refresh();
 form.addEventListener('submit',event=>{event.preventDefault();if(!setupReady||session.state!=='ended'||!recovery.canStart())return;if(!form.reportValidity())return;
  if(!validLanguagePair(languageA,languageB)){showError('Pilih dua bahasa yang berbeda sebelum memulai sesi.');languageB.focus();return;}
  error.hidden=true;document.querySelector('#live-translation').hidden=true;const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext){showError('Browser ini belum mendukung audio sesi.');return;}
  context=new AudioContext();session.start(new FormData(form));
 });
 document.querySelector('#live-end').addEventListener('click',()=>session.end());window.addEventListener('pagehide',()=>{const id=session.id||(recovery.ending?recovery.active?.session_id:null);session.end();if(id&&typeof navigator!=='undefined'&&typeof navigator.sendBeacon==='function'){const data=new FormData();data.append('csrf_token',csrf);try{navigator.sendBeacon('/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/end',data);}catch{}}});
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&session.state!=='ended'){showError('Sesi berakhir saat halaman ditinggalkan.');session.end();}});
}
