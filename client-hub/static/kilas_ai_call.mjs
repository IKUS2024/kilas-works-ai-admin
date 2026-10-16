import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {RealtimeCapture} from './kilas_live_translator_realtime_capture.mjs?v=app-language-20261015';
import {GeminiPlayer} from './kilas_live_gemini_player.mjs?v=native-progressive-20261016';
import {CallSession} from './kilas_ai_call_engine.mjs?v=ai-call-20261016';

const dialog=document.querySelector('#ai-call-dialog');
if(dialog){
 const status=dialog.querySelector('#ai-call-status'),caption=dialog.querySelector('#ai-call-caption'),error=dialog.querySelector('#ai-call-error'),end=dialog.querySelector('#ai-call-end');
 const csrf=document.querySelector('meta[name=csrf-token]')?.content||document.querySelector('[name=csrf_token]')?.value;
 let context=null;
 const request=(url,options={})=>requestJSON(url,{csrf,...options});
 const capture=new RealtimeCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices,continuous:true});
 let session;
 const player=new GeminiPlayer({getContext:()=>context,maxBufferedSeconds:60,onError:()=>session?.fail({code:'call_audio'})});
 const messages={call_unavailable:'Panggilan belum tersedia untuk akun ini.',budget_limit:'Batas biaya tercapai. Panggilan dihentikan.',
  already_processing:'Selesaikan sesi suara yang sedang diproses sebelum memanggil.',service_busy:'Layanan sedang sibuk. Coba panggil lagi nanti.',
  attempt_limit:'Batas panggilan tercapai. Coba lagi nanti.',call_limit:'Batas sesi tercapai. Panggilan dihentikan.',
  call_ended:'Panggilan berakhir.',call_audio:'Audio belum siap. Periksa izin audio lalu mulai panggilan baru.',
  microphone_permission_denied:'Izin mikrofon ditolak. Izinkan mikrofon lalu mulai panggilan baru.'};
 const stopAudio=()=>{const own=context;context=null;if(own){try{own.close().catch(()=>{});}catch{}}};
 const prepare=signal=>{
  const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Object.assign(Error(''),{code:'call_audio'});
  context=new Audio();const own=context;
  own.addEventListener?.('statechange',()=>{if(context===own&&own.state!=='running'&&session?.state!=='ended')session.fail({code:'call_audio'});});
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Object.assign(Error(''),{code:'call_audio'})),5000);
   const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};signal.addEventListener('abort',cancel,{once:true});
   own.resume().then(()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);if(signal.aborted||context!==own)return reject(new DOMException('Aborted','AbortError'));if(own.state!=='running')return reject(Object.assign(Error(''),{code:'call_audio'}));resolve();},()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(Object.assign(Error(''),{code:'call_audio'}));});
  });
 };
 session=new CallSession({request,capture,player,prepare,stopAudio,
  onText:text=>{caption.textContent=text;caption.scrollTop=caption.scrollHeight;},
  onState:state=>{dialog.dataset.state=state;status.textContent=t({connecting:'Menghubungkan…',listening:'Mendengarkan',speaking:'Kilas berbicara',ended:'Panggilan berakhir.'}[state]||'Menghubungkan…');},
  onError:code=>{error.textContent=t(messages[code]||'Panggilan terputus. Periksa mikrofon dan koneksi lalu mulai panggilan baru.');error.hidden=false;}
 });
 const close=()=>{
  const ident=session.ident,admitted=session.admitted;session.end();
  if(ident&&admitted&&navigator.sendBeacon){const data=new FormData();data.append('csrf_token',csrf);try{navigator.sendBeacon('/kilas-ai/call/'+ident+'/end',data);}catch{}}
  if(dialog.open)dialog.close();document.body.classList.remove('kilas-ai-call-open');
 };
 document.querySelectorAll('[data-ai-call-launch]').forEach(button=>button.addEventListener('click',()=>{
  if(session.state!=='ended')return;
  error.hidden=true;error.textContent='';caption.textContent='';
  if(typeof dialog.showModal!=='function'){const notice=document.querySelector('#ai-notice,#agent-chat-error');if(notice){notice.hidden=false;notice.textContent=t('Browser ini belum mendukung panggilan suara.');}return;}
  dialog.showModal();document.body.classList.add('kilas-ai-call-open');end.focus({preventScroll:true});
  const send=button.parentNode.querySelector('[type=submit]');
  if(send?.disabled){status.textContent=t('Selesaikan jawaban chat sebelum memanggil.');return;}
  session.start();
 }));
 end.addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
 dialog.addEventListener('close',()=>{session.end();document.body.classList.remove('kilas-ai-call-open');});
 window.addEventListener('pagehide',close);document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});
}
