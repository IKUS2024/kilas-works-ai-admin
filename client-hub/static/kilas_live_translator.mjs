import {VoiceRecorder} from './kilas_transcription_recorder.mjs?v=lifecycle-20261012';
import {TranslatorSession} from './kilas_live_translator_engine.mjs?v=realtime-input-20261013';
import {TranslatorPlayback} from './kilas_live_translator_playback.mjs?v=translation-integrity-20261013';
import {requestJSON,TranslatorTurns} from './kilas_live_translator_api.mjs?v=realtime-input-20261013';
import {RealtimeCapture} from './kilas_live_translator_realtime_capture.mjs?v=realtime-input-20261013';
import {RealtimeInput} from './kilas_live_translator_realtime_input.mjs?v=realtime-input-20261013';
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
 const batchCapture={
  async start({level,blob,error:onError}){
   if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder||!context)throw Error('Browser ini belum mendukung mikrofon.');
   recorder=new VoiceRecorder({mediaDevices:navigator.mediaDevices,Recorder:window.MediaRecorder,onBlob:raw=>{if(own!==recorder)return;monitorStop();if(own.translatorFinalized)blob(raw);else onError(Object.assign(Error('Ucapan terlalu panjang untuk satu rekaman. Jeda sebentar lalu tekan Lanjutkan; ucapan ini tidak diproses sebagian.'),{code:'utterance_limit'}));},onState:state=>{if(own!==recorder)return;if(state==='empty'){monitorStop();blob(new Blob([]));}if(state==='error')onError(Object.assign(Error('Mikrofon terputus. Periksa izin browser lalu tekan Lanjutkan.'),{code:'microphone_unavailable'}));}});
   const own=recorder;await own.start({userGesture:true,consent:true,enabled:true});
   if(own!==recorder||!own.stream)return;
   source=context.createMediaStreamSource(own.stream);analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
   const samples=new Float32Array(analyser.fftSize);let began=performance.now(),heard=false;
   interval=setInterval(()=>{if(!analyser)return;analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);if(rms>=.015)heard=true;level(rms);
    // Rotate an idle local buffer without ending the session or sending silence.
    // The shared recorder's 179s safety cap pauses a long utterance without
    // submitting truncated speech; ordinary utterances still wait for 2s silence.
    if(!heard&&performance.now()-began>=60000)onError(Object.assign(Error(''),{code:'capture_idle',recoverable:true,silent:true}));
   },50);
  },
  finalize(){monitorStop();if(recorder)recorder.translatorFinalized=true;recorder?.stop();},
  cancel(){monitorStop();recorder?.cancel();recorder=null;},
 };
 const realtimeCapture=new RealtimeCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});let activeCapture=batchCapture;
 const capture={
  start(options){activeCapture=options.inputMode==='realtime-v1'?realtimeCapture:batchCapture;return activeCapture.start(options);},
  finalize(){activeCapture.finalize();},cancel(){batchCapture.cancel();realtimeCapture.cancel();},
 };
 const player=new TranslatorPlayback({getContext:()=>context});
 const closeAudio=()=>{const own=context;context=null;if(own){try{own.close().catch(()=>{});}catch{}}};
 const playback={prepare:(...args)=>player.prepare(...args),play:(...args)=>player.play(...args),
  cancel:()=>player.cancel(),
  recover(error,signal,isCurrent){
   player.cancel();if(!context||context.state==='closed'||/^audio_(stalled|timeout|context|resume|start)$/.test(error?.code||'')){
    closeAudio();const AudioContext=window.AudioContext||window.webkitAudioContext;context=new AudioContext();
   }
   return player.prepare(signal,isCurrent);
  },
  stop(){player.cancel();closeAudio();},
 };
 async function json(url,options={}){
  try{return await requestJSON(url,{...options,csrf});}catch(e){if(e.code==='session_busy'){recoverRequested=true;recoveryError=true;}throw e;}
 }
 const turns=new TranslatorTurns({json,csrf});
 const api={
  input:new RealtimeInput({json,csrf}),
  async start(data,signal){try{return await json('/kilas-translator/live/sessions',{method:'POST',body:data,signal,timeoutMs:30000});}catch(e){recoverRequested=true;throw e;}},
  turn:(...args)=>turns.turn(...args),resume:(...args)=>turns.resume(...args),
  end:id=>recovery.endKnown(id),
 };
 const session=new TranslatorSession({api,capture,playback,onTiming:values=>{try{console.info('KILAS_LIVE_CLIENT_LATENCY '+Object.entries(values).filter(([,v])=>Number.isFinite(v)&&v>=0).map(([k,v])=>k+'='+v.toFixed(1)).join(' '));}catch{}},key:()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join(''),onError:showError,onResult:result=>{
  const text=document.querySelector('#live-translation');text.textContent=result.translated_text||'';text.hidden=!text.textContent;
 },onState:state=>{
  start.disabled=state!=='ended'||!setupReady||!recovery?.canStart();setup.hidden=state!=='ended';active.hidden=state==='ended';orb.dataset.state=state;
  const label={starting:'Menyiapkan sesi',resuming:'Menyiapkan audio',recovering:'Memulihkan sesi',paused:'Sesi dijeda',playing:'Memutar terjemahan',listening:session.inputMode==='realtime-v1'?'Mendengarkan realtime':'Mendengarkan mode rekaman'}[state]||'Memproses';orb.setAttribute('aria-label',label);
  document.querySelector('#live-resume').hidden=state!=='paused';
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
 document.querySelector('#live-resume').addEventListener('click',()=>{error.hidden=true;session.resume();});
 document.querySelector('#live-end').addEventListener('click',()=>session.end());window.addEventListener('pagehide',()=>{
  const id=session.id,key=session.pendingKey,ending=recovery.ending?recovery.active?.session_id:null;session.suspend();
  if(typeof navigator!=='undefined'&&typeof navigator.sendBeacon==='function'){
   const url=ending?'/kilas-translator/live/sessions/'+encodeURIComponent(ending)+'/end':id&&key?turns.path(id,key)+'/cancel':null;
   if(url){const data=new FormData();data.append('csrf_token',csrf);try{navigator.sendBeacon(url,data);}catch{}}
  }
 });
 document.addEventListener('visibilitychange',()=>{if(document.hidden)session.suspend();});
}
