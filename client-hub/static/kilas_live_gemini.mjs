import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {RealtimeCapture} from './kilas_live_translator_realtime_capture.mjs?v=utterance-gate-20261016';
import {TranslatorPlayback} from './kilas_live_translator_playback.mjs?v=app-language-20261015';
import {TranslatorRecovery} from './kilas_live_translator_recovery.mjs?v=app-language-20261015';
import {syncLanguagePair,validLanguagePair} from './kilas_live_translator_languages.mjs?v=pair-layout-20261012';
import {TranslatorCallLayout} from './kilas_live_translator_call_layout.mjs?v=call-viewport-20261013';
import {GeminiSession,GeminiPlayer} from './kilas_live_gemini_engine.mjs?v=native-pair-20261016';
import {PlaybackEcho} from './kilas_live_gemini_echo.mjs?v=native-pair-20261016';
const root=document.querySelector('[data-gemini-live]');
if(root){
 const admissionReady=root.dataset.geminiReady==='true';
 const form=document.querySelector('#live-setup-form'),start=form.querySelector('[type=submit]'),active=document.querySelector('#live-active'),error=document.querySelector('#live-error');
 const first=form.querySelector('[name=language_a]'),second=form.querySelector('[name=language_b]'),csrf=form.querySelector('[name=csrf_token]').value;
 let context=null,session,recovery;
 const json=(url,options={})=>requestJSON(url,{...options,csrf});
 const showError=e=>{error.hidden=false;error.textContent=t(e?.code==='budget_limit'?'Batas biaya tercapai. Sesi dihentikan.':e?.code==='attempt_limit'?'Batas penggunaan Live Translator tercapai. Sesi dijeda.':e?.code==='gemini_playback_backlog'?'Antrean audio penuh. Ucapan tidak diulang otomatis.':'Sesi terputus. Periksa koneksi sebelum mulai lagi.');};
 const getContext=()=>context;
 const prepare=new TranslatorPlayback({getContext});
 const capture=new RealtimeCapture({getContext,mediaDevices:navigator.mediaDevices,continuous:true,frameSamples:1600});
 const layout=new TranslatorCallLayout({document,root,endButton:document.querySelector('#live-end')});
 const latency=values=>{try{console.info('KILAS_GEMINI_CLIENT_LATENCY '+Object.entries(values).filter(([,v])=>Number.isFinite(v)&&v>=0).map(([k,v])=>k+'='+v.toFixed(1)).join(' '));}catch{}};
 const echo=new PlaybackEcho({getContext});
 const player=new GeminiPlayer({getContext,maxBufferedSeconds:90,onScheduled:(buffer,at)=>echo.remember(buffer,at),onHold:at=>echo.hold(at),onPlaying:()=>{if(!session.speech?.active)session.state('playing');},onTiming:latency,onStarted:()=>{if(session.firstInputAt!==null)latency({first_audio_scheduled_ms:Math.max(0,performance.now()-session.firstInputAt)});},onError:e=>session.fail(e,session.version)});
 const update=()=>{start.disabled=!admissionReady||Boolean(session?.active)||Boolean(session?.admissionPending)||!recovery?.canStart()||!validLanguagePair(first,second);};
 recovery=new TranslatorRecovery({api:{active:()=>json('/kilas-translator/live/sessions/active'),end:id=>json('/kilas-translator/live/sessions/'+id+'/end',{method:'POST',body:session.form(),timeoutMs:10000})},
  isIdle:()=>!session?.active,onError:showError,onChange:state=>{
   document.querySelector('#live-recovery').hidden=!state.active;document.querySelector('#live-recovery-status').textContent=state.active?t('Sesi sebelumnya masih aktif.'):'';update();
   document.querySelector('#live-recovery-check').hidden=state.checked||state.pending||Boolean(session?.active);
  }});
 session=new GeminiSession({json,capture,player,csrf,utterancePlayback:true,isEcho:bytes=>echo.matches(bytes),onTiming:latency,onAdmissionChange:update,endOwned:id=>recovery.endKnown(id),onIdle:()=>recovery.refresh(),prepare:async(signal,current)=>{
  echo.reset();if(!context)context=new AudioContext();await prepare.prepare(signal,current);
 },onState:state=>{
  active.hidden=state==='ended';document.querySelector('#live-setup').hidden=state!=='ended';layout.setActive(state!=='ended');
  document.querySelector('#live-state').textContent=t(state==='listening'?'Mendengarkan':state==='playing'?'Memutar terjemahan':state==='renewing'||state==='processing'||state==='draining'?'Memproses':'Menyiapkan sesi...');update();
  if(state==='ended'){recovery.checked=false;update();}
 },onWarning:()=>{document.querySelector('#live-session-status').textContent=t('Bagian akhir terjemahan belum terkonfirmasi.');},onError:showError});
 const pairSummary=()=>{const summary=document.querySelector('#gemini-pair-summary');if(root.dataset.geminiTranslationMode==='two_way'&&summary)summary.textContent=(first.selectedOptions[0]?.textContent||'')+' ↔ '+(second.selectedOptions[0]?.textContent||'');};
 for(const select of [first,second])select.addEventListener('change',()=>{syncLanguagePair(first,second,select);pairSummary();update();});syncLanguagePair(first,second);pairSummary();update();
 form.addEventListener('submit',event=>{event.preventDefault();if(!admissionReady||start.disabled||!form.reportValidity())return;error.hidden=true;document.querySelector('#live-session-status').textContent='';session.start(new FormData(form));});
 document.querySelector('#live-end').addEventListener('click',()=>session.end());
 document.querySelector('#live-recovery-end').addEventListener('click',()=>recovery.endPrevious());
 document.querySelector('#live-recovery-check').addEventListener('click',()=>recovery.refresh());
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&session.active)session.end();});
 window.addEventListener('pagehide',()=>{if(session.active)session.end();});
 recovery.refresh();
}
