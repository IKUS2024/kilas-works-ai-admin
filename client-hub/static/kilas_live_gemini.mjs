import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {RealtimeCapture} from './kilas_live_translator_realtime_capture.mjs?v=utterance-gate-20261016';
import {TranslatorPlayback} from './kilas_live_translator_playback.mjs?v=app-language-20261015';
import {TranslatorRecovery} from './kilas_live_translator_recovery.mjs?v=app-language-20261015';
import {syncLanguagePair,validLanguagePair} from './kilas_live_translator_languages.mjs?v=pair-layout-20261012';
import {TranslatorCallLayout} from './kilas_live_translator_call_layout.mjs?v=call-viewport-20261013';
import {GeminiSession,GeminiPlayer} from './kilas_live_gemini_engine.mjs?v=output-boundary-20261024';
import {PlaybackEcho} from './kilas_live_gemini_echo.mjs?v=native-echo-recovery-20261016';
import {GeminiCaptions} from './kilas_live_gemini_captions.mjs?v=streaming-20261023';
const root=document.querySelector('[data-gemini-live]');
if(root){
 const admissionReady=root.dataset.geminiReady==='true';
 const form=document.querySelector('#live-setup-form'),start=form.querySelector('[type=submit]'),active=document.querySelector('#live-active'),error=document.querySelector('#live-error');
 const first=form.querySelector('[name=language_a]'),second=form.querySelector('[name=language_b]'),csrf=form.querySelector('[name=csrf_token]').value;
 let context=null,gain=null,session,recovery;
 const captions=new GeminiCaptions({root:document.querySelector('#native-captions'),document,labels:{original:t('Teks asli'),translation:t('Terjemahan')}});
 const json=(url,options={})=>requestJSON(url,{...options,csrf});
 const showError=e=>{error.hidden=false;error.textContent=t(e?.name==='NotAllowedError'?'Izinkan mikrofon di browser, lalu coba lagi.':e?.name==='NotFoundError'?'Mikrofon tidak ditemukan. Sambungkan mikrofon, lalu coba lagi.':navigator.onLine===false?'Anda sedang offline. Sambungkan internet, lalu mulai kembali.':e?.code==='budget_limit'?'Batas biaya tercapai. Sesi dihentikan.':e?.code==='attempt_limit'?'Batas penggunaan Live Translator tercapai. Sesi dijeda.':e?.code==='gemini_playback_backlog'?'Antrean audio penuh. Ucapan tidak diulang otomatis.':'Sesi terputus. Periksa koneksi sebelum mulai lagi.');};
 const getContext=()=>context;
 const outputContext=()=>context?{state:context.state,get currentTime(){return context.currentTime;},destination:gain||context.destination,createBuffer:(...args)=>context.createBuffer(...args),createBufferSource:()=>context.createBufferSource()}:null;
 const prepare=new TranslatorPlayback({getContext});
 const capture=new RealtimeCapture({getContext,mediaDevices:navigator.mediaDevices,continuous:true,frameSamples:1600});
 const layout=new TranslatorCallLayout({document,root,endButton:document.querySelector('#live-end')});
 const fitViewport=()=>{
  const view=window.visualViewport;
  for(const name of ['width','height','left','top','right','bottom'])root.style.removeProperty(name);
  if(session?.active&&view){Object.assign(root.style,{width:view.width+'px',height:view.height+'px',left:view.offsetLeft+'px',top:view.offsetTop+'px',right:'auto',bottom:'auto'});}
 };
 window.visualViewport?.addEventListener('resize',fitViewport);window.visualViewport?.addEventListener('scroll',fitViewport);
 window.addEventListener('resize',fitViewport);
 const latency=values=>{try{console.info('KILAS_GEMINI_CLIENT_LATENCY '+Object.entries(values).filter(([,v])=>Number.isFinite(v)&&v>=0).map(([k,v])=>k+'='+v.toFixed(1)).join(' '));}catch{}};
 const echo=new PlaybackEcho({getContext});
 const player=new GeminiPlayer({getContext:outputContext,maxBufferedSeconds:90,onScheduled:(buffer,at)=>echo.remember(buffer,at),onHold:at=>echo.hold(at),onPlaying:()=>{if(!session.speech?.active)session.state('playing');},onTiming:latency,onStarted:()=>{if(session.firstInputAt!==null)latency({first_audio_scheduled_ms:Math.max(0,performance.now()-session.firstInputAt)});},onError:e=>session.fail(e,session.version)});
 const update=()=>{start.disabled=!admissionReady||Boolean(session?.active)||Boolean(session?.admissionPending)||!recovery?.canStart()||!validLanguagePair(first,second);};
 recovery=new TranslatorRecovery({api:{active:()=>json('/kilas-translator/live/sessions/active'),end:id=>json('/kilas-translator/live/sessions/'+id+'/end',{method:'POST',body:session.form(),timeoutMs:10000})},
  isIdle:()=>!session?.active,onError:showError,onChange:state=>{
   document.querySelector('#live-recovery').hidden=!state.active;document.querySelector('#live-recovery-status').textContent=state.active?t('Sesi sebelumnya masih aktif.'):'';update();
   document.querySelector('#live-recovery-check').hidden=state.checked||state.pending||Boolean(session?.active);
  }});
 session=new GeminiSession({json,capture,player,csrf,utterancePlayback:true,waitForOutputBeforeFinish:true,endpointMs:600,packetBytes:3200,readRetries:2,onText:(text,detail)=>{captions.update(text,detail);document.querySelector('#native-caption-empty').hidden=Boolean(document.querySelector('#native-captions').children.length);},isEcho:bytes=>echo.matches(bytes),onTiming:latency,onAdmissionChange:update,endOwned:id=>recovery.endKnown(id),onIdle:()=>recovery.refresh(),prepare:async(signal,current)=>{
  echo.reset();captions.reset();document.querySelector('#native-caption-empty').hidden=false;
  captions.labels[first.value]=second.selectedOptions[0].textContent+' → '+first.selectedOptions[0].textContent;captions.labels[second.value]=first.selectedOptions[0].textContent+' → '+second.selectedOptions[0].textContent;
  if(!context){context=new AudioContext();gain=context.createGain();gain.connect(context.destination);}gain.gain.value=Number(document.querySelector('#native-volume').value)/100;await prepare.prepare(signal,current);
 },onState:state=>{
  active.hidden=state==='ended';document.querySelector('#live-setup').hidden=state!=='ended';layout.setActive(state!=='ended');fitViewport();
  document.querySelector('#live-state').textContent=t(state==='reconnecting'?'Menghubungkan kembali…':state==='listening'?'Mendengarkan':state==='playing'?'Memutar terjemahan':state==='renewing'||state==='processing'||state==='draining'?'Memproses':'Menyiapkan sesi...');update();
  if(state==='ended'){recovery.checked=false;update();}
 },onWarning:()=>{document.querySelector('#live-session-status').textContent=t('Bagian akhir terjemahan belum terkonfirmasi.');},onError:showError});
 const pairSummary=()=>{document.querySelector('#native-active-pair').textContent=(first.selectedOptions[0]?.textContent||'')+' ↔ '+(second.selectedOptions[0]?.textContent||'');const summary=document.querySelector('#gemini-pair-summary');if(root.dataset.geminiTranslationMode==='two_way'&&summary)summary.textContent=(first.selectedOptions[0]?.textContent||'')+' ↔ '+(second.selectedOptions[0]?.textContent||'');};
 for(const select of [first,second])select.addEventListener('change',()=>{syncLanguagePair(first,second,select);pairSummary();update();});syncLanguagePair(first,second);pairSummary();update();
 form.addEventListener('submit',event=>{event.preventDefault();if(!admissionReady||start.disabled||!form.reportValidity())return;error.hidden=true;document.querySelector('#live-session-status').textContent='';session.start(new FormData(form));});
 document.querySelector('#native-swap').addEventListener('click',()=>{if(session.active)return;const old=first.value;first.value=second.value;second.value=old;for(const select of [first,second])select.dispatchEvent(new Event('change',{bubbles:true}));});
 document.querySelector('#native-volume').addEventListener('input',event=>{if(gain)gain.gain.value=Number(event.target.value)/100;});
 document.querySelector('#live-end').addEventListener('click',()=>session.end());
 document.querySelector('#live-recovery-end').addEventListener('click',()=>recovery.endPrevious());
 document.querySelector('#live-recovery-check').addEventListener('click',()=>recovery.refresh());
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&session.active)session.end();});
 window.addEventListener('pagehide',()=>{if(session.active)session.end();});
 recovery.refresh();
}
