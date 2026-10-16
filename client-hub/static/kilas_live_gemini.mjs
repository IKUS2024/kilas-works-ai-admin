import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {RealtimeCapture} from './kilas_live_translator_realtime_capture.mjs?v=app-language-20261015';
import {TranslatorPlayback} from './kilas_live_translator_playback.mjs?v=app-language-20261015';
import {TranslatorRecovery} from './kilas_live_translator_recovery.mjs?v=app-language-20261015';
import {syncLanguagePair,validLanguagePair} from './kilas_live_translator_languages.mjs?v=pair-layout-20261012';
import {TranslatorCallLayout} from './kilas_live_translator_call_layout.mjs?v=call-viewport-20261013';
import {GeminiSession,GeminiPlayer} from './kilas_live_gemini_engine.mjs?v=gemini-isolated-v1';
const root=document.querySelector('[data-gemini-live]');
if(root){
 const form=document.querySelector('#live-setup-form'),start=form.querySelector('[type=submit]'),active=document.querySelector('#live-active'),error=document.querySelector('#live-error');
 const first=form.querySelector('[name=language_a]'),second=form.querySelector('[name=language_b]'),csrf=form.querySelector('[name=csrf_token]').value;
 let context=null,session,recovery;
 const json=(url,options={})=>requestJSON(url,{...options,csrf});
 const showError=()=>{error.hidden=false;error.textContent=t('Sesi Gemini terputus. Ucapan ini tidak diulang otomatis.');};
 const getContext=()=>context;
 const prepare=new TranslatorPlayback({getContext});
 const capture=new RealtimeCapture({getContext,mediaDevices:navigator.mediaDevices});
 const layout=new TranslatorCallLayout({document,root,endButton:document.querySelector('#live-end')});
 const latency=values=>{try{console.info('KILAS_GEMINI_CLIENT_LATENCY '+Object.entries(values).filter(([,v])=>Number.isFinite(v)&&v>=0).map(([k,v])=>k+'='+v.toFixed(1)).join(' '));}catch{}};
 const player=new GeminiPlayer({getContext,onTiming:latency,onStarted:()=>{if(session.firstInputAt!==null)latency({first_audio_scheduled_ms:Math.max(0,performance.now()-session.firstInputAt)});},onError:e=>session.fail(e,session.version)});
 const update=()=>{start.disabled=Boolean(session?.active)||Boolean(session?.admissionPending)||!recovery?.canStart()||!validLanguagePair(first,second);};
 recovery=new TranslatorRecovery({api:{active:()=>json('/kilas-translator/live/sessions/active'),end:id=>json('/kilas-translator/live/sessions/'+id+'/end',{method:'POST',body:session.form(),timeoutMs:10000})},
  isIdle:()=>!session?.active,onError:showError,onChange:state=>{
   document.querySelector('#live-recovery').hidden=!state.active;document.querySelector('#live-recovery-status').textContent=state.active?t('Sesi sebelumnya masih aktif.'):'';update();
  }});
 session=new GeminiSession({json,capture,player,csrf,onTiming:latency,endOwned:id=>recovery.endKnown(id),onIdle:()=>recovery.refresh(),prepare:async(signal,current)=>{
  if(!context)context=new AudioContext();await prepare.prepare(signal,current);
 },onState:state=>{
  active.hidden=state==='ended';document.querySelector('#live-setup').hidden=state!=='ended';layout.setActive(state!=='ended');
  document.querySelector('#live-state').textContent=t(state==='listening'?'Mendengarkan':state==='draining'?'Memproses':'Menyiapkan sesi...');
  document.querySelector('#gemini-finish').disabled=state==='draining';update();
  if(state==='ended'){recovery.checked=false;update();}
 },onText:text=>{document.querySelector('#live-translation').textContent=text;},onError:showError});
 for(const select of [first,second])select.addEventListener('change',()=>{syncLanguagePair(first,second,select);update();});syncLanguagePair(first,second);update();
 form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity()||start.disabled)return;error.hidden=true;document.querySelector('#live-translation').textContent='';session.start(new FormData(form));});
 document.querySelector('#gemini-finish').addEventListener('click',()=>session.finish());
 document.querySelector('#live-end').addEventListener('click',()=>session.end());
 document.querySelector('#live-recovery-end').addEventListener('click',()=>recovery.endPrevious());
 document.querySelector('#live-recovery-check').addEventListener('click',()=>recovery.refresh());
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&session.active)session.end();});
 window.addEventListener('pagehide',()=>{if(session.active)session.end();});
 recovery.refresh();
}
