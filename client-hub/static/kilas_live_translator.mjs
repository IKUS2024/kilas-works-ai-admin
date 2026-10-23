import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {captureMode,compatibleRecorder,TranslatorAudioRoute} from './kilas_live_translator_capabilities.mjs?v=clauses-20261022';
import {VoiceRecorder} from './kilas_transcription_recorder.mjs?v=app-language-20261015';
import {StreamingTranslatorSession as TranslatorSession} from './kilas_live_translator_streaming.mjs?v=phrase-pause-20261023';
import {TranslatorPlayback} from './kilas_live_translator_playback.mjs?v=clauses-20261022';
import {requestJSON,TranslatorTurns} from './kilas_live_translator_api.mjs?v=clauses-20261022';
import {RealtimeCapture} from './kilas_live_translator_realtime_capture.mjs?v=clauses-20261022';
import {RealtimeInput} from './kilas_live_translator_realtime_input.mjs?v=clauses-20261022';
import {syncLanguagePair,validLanguagePair} from './kilas_live_translator_languages.mjs?v=explicit-pair-20261018';
import {TranslatorRecovery} from './kilas_live_translator_recovery.mjs?v=app-language-20261015';
import {TranslatorCallLayout} from './kilas_live_translator_call_layout.mjs?v=call-viewport-20261013';
import {bindRecordToggle,TranslatorMicrophone} from './kilas_live_translator_toggle.mjs?v=clauses-20261022';
import {TranslatorHistory} from './kilas_live_translator_history.mjs?v=clauses-20261022';
import {prepareProgressive,disposeProgressive,progressivePlay} from './kilas_live_translator_progressive.mjs?v=pending-play-20261020';
const root=document.querySelector('.kilas-live-translator');
if(root){
 const form=document.querySelector('#live-setup-form'),setup=document.querySelector('#live-setup'),active=document.querySelector('#live-active'),orb=active.querySelector('.kilas-live-orb'),error=document.querySelector('#live-error');
 const csrf=form.querySelector('[name=csrf_token]').value,start=form.querySelector('button[type=submit]');let context=null,source=null,analyser=null,interval=null,recorder=null;const audioRoute=new TranslatorAudioRoute(navigator),microphone=new TranslatorMicrophone(navigator.mediaDevices);
 const callLayout=new TranslatorCallLayout({document,root,endButton:document.querySelector('#live-end')});
 const setupReady=root.dataset.ready==='true'&&start.dataset.enabled==='true';
 const showError=(text,detail)=>{error.textContent=t(text);error.hidden=false;
  if(/^audio_(permission|resume|context|start|stalled)$/.test(detail?.code||'')){try{console.info('KILAS_LIVE_BROWSER_FAILURE stage=playback code='+detail.code);}catch{}}
  if(detail?.startupStage){if(detail.startupStage==='session_admission')recoverRequested=true;try{console.info('KILAS_LIVE_STARTUP_FAILURE stage='+detail.startupStage+' code='+(detail.code||'startup_failed'));}catch{}}
  if(detail?.inputStage&&['realtime_queue_full','realtime_protocol','realtime_turn_busy','realtime_chunk_invalid','realtime_no_speech'].includes(detail.code)){try{console.info('KILAS_LIVE_INPUT_FAILURE code='+detail.code);}catch{}}
 };
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
  async start({level,blob,error:onError,ready}){
   if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder||!context)throw Error(t('Browser ini belum mendukung mikrofon.'));
   let starting=true;
   recorder=new VoiceRecorder({mediaDevices:microphone,Recorder:compatibleRecorder(window.MediaRecorder),onBlob:raw=>{if(own!==recorder)return;monitorStop();if(own.translatorFinalized)blob(raw);else onError(Object.assign(Error(t('Ucapan terlalu panjang untuk satu rekaman. Jeda sebentar lalu tekan Lanjutkan; ucapan ini tidak diproses sebagian.')),{code:'utterance_limit'}));},onState:state=>{if(own!==recorder)return;if(state==='empty'){monitorStop();blob(new Blob([]));}if(state==='error'&&!starting)onError(Object.assign(Error(t('Mikrofon terputus. Periksa izin browser lalu tekan Lanjutkan.')),{code:'microphone_unavailable'}));}});
   const own=recorder;
   try{await own.start({userGesture:true,consent:true,enabled:true});}
   catch(e){if(e?.name==='NotAllowedError'||e?.name==='SecurityError')throw Object.assign(Error(t('Izin mikrofon ditolak. Izinkan mikrofon di browser lalu tekan Lanjutkan.')),{code:'microphone_permission_denied',startupStage:'microphone_start'});throw e;}
   finally{starting=false;}
   if(own!==recorder)return;if(!own.stream)throw Object.assign(Error(t('Mikrofon belum siap. Periksa izin browser lalu tekan Lanjutkan.')),{code:'microphone_unavailable'});
   source=context.createMediaStreamSource(own.stream);analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
   const samples=new Float32Array(analyser.fftSize);let began=performance.now(),heard=false;
   interval=setInterval(()=>{if(!analyser)return;analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);if(rms>=.015)heard=true;level(rms);
    // A held but silent microphone is released without paid silence input.
    if(!heard&&performance.now()-began>=60000)onError(Object.assign(Error(''),{code:'capture_idle',recoverable:true,silent:true}));
   },50);
   ready?.();
  },
  finalize(){monitorStop();if(recorder)recorder.translatorFinalized=true;recorder?.stop();},
  cancel(){monitorStop();recorder?.cancel();recorder=null;},
 };
 const realtimeCapture=new RealtimeCapture({getContext:()=>context,mediaDevices:microphone});let activeCapture=batchCapture,captureEpoch=0;
 const capture={
  get supportsDuplex(){return navigator.mediaDevices?.getSupportedConstraints?.().echoCancellation===true;},
  start(options){const epoch=++captureEpoch;const restore=()=>{if(epoch===captureEpoch)audioRoute.playback();};activeCapture=options.inputMode==='realtime-v1'?realtimeCapture:batchCapture;audioRoute.capture();
   const restored={...options,blob:value=>{restore();options.blob(value);},error:value=>{restore();options.error(value);}};
   return Promise.resolve(activeCapture.start(restored)).catch(e=>{restore();throw e;});},
  finalize(){activeCapture.finalize();},cancel(){++captureEpoch;microphone.cancel();batchCapture.cancel();realtimeCapture.cancel();audioRoute.playback();},
 };
 const latency=values=>{try{console.info('KILAS_LIVE_CLIENT_LATENCY '+Object.entries(values).filter(([,v])=>Number.isFinite(v)&&v>=0).map(([k,v])=>k+'='+v.toFixed(1)).join(' '));}catch{}};
 let history=null;const player=new TranslatorPlayback({getContext:()=>context,onTiming:latency,onStored:url=>history?.stored(url),onEvict:url=>history?.remove(url)});
 const closeAudio=()=>{disposeProgressive(player);const own=context;context=null;if(own){try{own.close().catch(()=>{});}catch{}}};
 const prepareAudio=(...args)=>{audioRoute.playback();return Promise.all([player.prepare(...args),prepareProgressive(player,...args)]);};
 const playback={get progressive(){return player.progressiveMedia?.ready?(...args)=>progressivePlay(player,...args):null;},has:url=>player.has(url),prepare:prepareAudio,play:async(url,signal,current,started)=>{const offset=player.resumeOffsets.get(url)||0;await player.play(url,signal,current,started,offset);player.resumeOffsets.delete(url);},prefetch:(...args)=>player.prefetch(...args),
  cancel:()=>player.cancel(),
  recover(error,signal,isCurrent){
   player.cancel();if(!context||context.state==='closed'||/^audio_(stalled|timeout|context|resume|start)$/.test(error?.code||'')){
    closeAudio();const AudioContext=window.AudioContext||window.webkitAudioContext;context=new AudioContext();
   }
   return prepareAudio(signal,isCurrent);
  },
  stop(){player.cancel();player.clearCache();history?.clear();closeAudio();audioRoute.restore();},
 };
 async function json(url,options={}){
  try{return await requestJSON(url,{...options,csrf});}catch(e){if(e.code==='session_busy'){recoverRequested=true;recoveryError=true;}throw e;}
 }
 const turns=new TranslatorTurns({json,csrf,wholeUtterance:true});
 const api={
  input:new RealtimeInput({json,csrf,holdToTalk:true,onTiming:latency}),
  clauses:{
   cancel:(id,key)=>turns.cancel(id,key),
   read:(id,key,signal)=>json(turns.path(id,key)+'/clauses',{signal,timeoutMs:10000}),
   ack:(id,key,index,signal)=>{const data=new FormData();data.append('csrf_token',csrf);data.append('index',String(index));return json(turns.path(id,key)+'/clauses',{method:'POST',body:data,signal,timeoutMs:10000});}
  },
  async start(data,signal){try{return await json('/kilas-translator/live/sessions',{method:'POST',body:data,signal,timeoutMs:30000});}catch(e){recoverRequested=true;throw e;}},
  turn:(...args)=>turns.turn(...args),resume:(...args)=>turns.resume(...args),
  end:id=>{const text=document.querySelector('#live-translation');text.textContent='';text.hidden=true;return recovery.endKnown(id);},
 };
 let holdControl=null;const holdButton=document.querySelector('#live-hold');
 const session=new TranslatorSession({api,capture,playback,pushToTalk:true,recordOnStart:true,continuous:true,onTiming:latency,key:()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join(''),onError:showError,onResult:result=>{
  const text=document.querySelector('#live-translation');text.textContent=result.translated_text||'';text.hidden=!text.textContent;
  history?.add(result,languageA.value);
  if(result.status==='COMPLETED'&&typeof result.translated_text==='string'&&result.translated_text.trim()){error.hidden=true;error.textContent='';}
 },onState:state=>{
  start.disabled=state!=='ended'||!setupReady||!recovery?.canStart();setup.hidden=state!=='ended';active.hidden=state==='ended';orb.dataset.state=state;
  history?.busy(state!=='ready');
  const recording=session.running||['opening','listening'].includes(state);holdButton.disabled=!recording&&!['ready','opening','listening'].includes(state);holdButton.setAttribute('aria-pressed',String(recording));
  holdButton.textContent=recording?'Stop':['preparing','starting','processing','finalizing','resuming','recovering'].includes(state)?t('Memproses'):'Start';
  holdButton.setAttribute('aria-label',recording?t('Stop Rekaman'):t('Mulai Rekam'));
  if(state==='ended'||state==='paused')holdControl?.reset();
  const label={ready:t('Mulai Rekam'),opening:t('Menyiapkan mikrofon'),paused:t('Sesi dijeda'),playing:t('Hasil'),replaying:t('Hasil'),listening:t('Mendengarkan')}[state]||t('Memproses');orb.setAttribute('aria-label',label);
  document.querySelector('#live-resume').hidden=state!=='paused';
  document.querySelector('#live-state').textContent=orb.getAttribute('aria-label');
  const modeNote=document.querySelector('#live-mode-note');
  if(modeNote){modeNote.hidden=!session.id;modeNote.textContent=session.inputMode==='realtime-v1'&&session.streaming?t('Terjemahan diputar per klausa sambil mikrofon tetap aktif. Gunakan earphone untuk mengurangi gema. Klausa yang sudah terdengar tidak direvisi. Stop mengakhiri input; End membatalkan sesi.'):session.inputMode==='realtime-v1'?t('Bicara saat Mendengarkan. Jeda ucapan diterjemahkan otomatis; tunggu suara selesai sebelum berbicara lagi. Stop menghentikan percakapan setelah hasil saat ini.'):t('Mode rekaman: tekan Stop untuk memproses ucapan, lalu Start untuk giliran berikutnya.');}
  callLayout.setActive(state!=='ended');
  if(state==='ended'&&(recoverRequested||session.admissionPending)){recoverRequested=false;recovery.checked=false;recovery.refresh();}
 }});
 history=new TranslatorHistory({element:document.querySelector('#live-history'),languageName:code=>[...languageA.options].find(option=>option.value===code)?.textContent||code,replay:url=>session.replay(url),available:url=>player.has(url)});
 holdControl=bindRecordToggle({button:holdButton,session,window,document});
 recovery=new TranslatorRecovery({api:{active:()=>json('/kilas-translator/live/sessions/active',{timeoutMs:10000}),end(id){const data=new FormData();data.append('csrf_token',csrf);return json('/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/end',{method:'POST',body:data,keepalive:true,timeoutMs:10000});}},isIdle:()=>session.state==='ended',onError:text=>{recoveryError=true;showError(text);},onChange:state=>{
  start.disabled=session.state!=='ended'||!setupReady||!state.canStart();
  const confirmedActive=Boolean(state.active)&&(state.checked||state.ending),idle=session.state==='ended';
  recoveryPanel.hidden=!idle||!confirmedActive;
  // Preserve the action label while disabled/aria-busy and status report readiness.
  start.textContent='Start';
  start.setAttribute?.('aria-busy',String(state.pending));
  sessionStatus.textContent=idle&&state.pending&&!confirmedActive?t('Memeriksa sesi...'):'';
  recoveryRetry.hidden=!idle||state.pending||state.checked||confirmedActive;
  recoveryEnd.hidden=!state.active;recoveryEnd.disabled=state.pending;recoveryCheck.disabled=state.pending;
  recoveryStatus.textContent=state.ending?t('Mengakhiri sesi sebelumnya...'):state.pending?t('Memeriksa sesi...'):state.active?t('Sesi sebelumnya masih aktif.')+(state.active.processing?t(' Ada ucapan yang masih diproses.'):''):t('Status sesi belum terverifikasi. Periksa sesi saat jaringan siap.');
  if(state.canStart()&&recoveryError){error.hidden=true;recoveryError=false;}
  if(recoveryExpiry!==null){clearTimeout(recoveryExpiry);recoveryExpiry=null;}
  if(session.state==='ended'&&!state.pending&&state.active?.expires_in_seconds>0)recoveryExpiry=setTimeout(()=>recovery.refresh(),state.active.expires_in_seconds*1000);
 }});
 recoveryEnd.addEventListener('click',()=>recovery.endPrevious());recoveryCheck.addEventListener('click',()=>recovery.refresh());recoveryRetry.addEventListener('click',()=>recovery.refresh());
 window.addEventListener('online',()=>{recovery.refresh();if(!document.hidden)session.foreground();});recovery.refresh();
 form.addEventListener('submit',event=>{event.preventDefault();if(!setupReady||session.state!=='ended'||!recovery.canStart())return;if(!form.reportValidity())return;
  if(!validLanguagePair(languageA,languageB)){showError(t('Pilih dua bahasa yang berbeda sebelum memulai sesi.'));languageB.focus();return;}
  error.hidden=true;document.querySelector('#live-translation').hidden=true;const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext){showError(t('Browser ini belum mendukung audio sesi.'));return;}
  context=new AudioContext();const transport=captureMode(context,window,navigator.mediaDevices);if(!transport){closeAudio();showError(t('Browser ini belum mendukung mikrofon.'));return;}
  const data=new FormData(form);data.append('capture_transport',transport);holdControl.arm();session.start(data);
  if(session.state!=='ended'){audioRoute.capture();microphone.prime();}
 });
 document.querySelector('#live-resume').addEventListener('click',()=>{error.hidden=true;session.resume();});
 document.querySelector('#live-end').addEventListener('click',()=>session.end());window.addEventListener('pagehide',()=>{
  const id=session.id,key=session.pendingKey,ending=recovery.ending?recovery.active?.session_id:null;microphone.cancel();session.suspend();
  if(typeof navigator!=='undefined'&&typeof navigator.sendBeacon==='function'){
   const url=ending?'/kilas-translator/live/sessions/'+encodeURIComponent(ending)+'/end':id&&key&&!session.outputPending?turns.path(id,key)+'/cancel':null;
   if(url){const data=new FormData();data.append('csrf_token',csrf);try{navigator.sendBeacon(url,data);}catch{}}
  }
 });
 document.addEventListener('visibilitychange',()=>{if(document.hidden){microphone.cancel();session.suspend();}else session.foreground();});
}
