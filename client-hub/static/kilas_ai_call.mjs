import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-user-first-20261017';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-jitter-20261016';
import {CallSession} from './kilas_ai_call_engine.mjs?v=call-reset-state-20261017';
import {renderCallSources} from './kilas_ai_call_sources.mjs?v=call-public-search-20261017';

const dialog=document.querySelector('#ai-call-dialog');
if(dialog){
 // The Call belongs to the viewport, outside the chat layout and its forms.
 document.body.append(dialog);
 const status=dialog.querySelector('#ai-call-status'),caption=dialog.querySelector('#ai-call-caption'),error=dialog.querySelector('#ai-call-error'),end=dialog.querySelector('#ai-call-end');
 const csrf=document.querySelector('meta[name=csrf-token]')?.content||document.querySelector('[name=csrf_token]')?.value;
 let context=null,launcher=null;
 const request=(url,options={})=>requestJSON(url,{csrf,...options});
 const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
 let session;
 const player=new CallPlayer({getContext:()=>context,onError:()=>session?.fail({code:'call_audio'})});
 const messages={call_unavailable:'Panggilan belum tersedia untuk akun ini.',budget_limit:'Batas biaya tercapai. Panggilan dihentikan.',
  account_credit_limit:'Kapasitas Premium belum cukup untuk permintaan ini. Tambah kapasitas atau lanjutkan Chat biasa.',
  already_processing:'Selesaikan sesi suara yang sedang diproses sebelum memanggil.',service_busy:'Layanan sedang sibuk. Coba panggil lagi nanti.',
  attempt_limit:'Batas panggilan tercapai. Coba lagi nanti.',
  call_ended:'Panggilan berakhir.',call_audio:'Audio belum siap. Periksa izin audio lalu mulai panggilan baru.',
  microphone_permission_denied:'Izin mikrofon ditolak. Izinkan mikrofon lalu mulai panggilan baru.'};
 const stopAudio=()=>{const own=context;context=null;if(own){try{own.close().catch(()=>{});}catch{}}};
 const prepare=signal=>{
  const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Object.assign(Error(''),{code:'call_audio'});
  context=new Audio({latencyHint:'playback'});const own=context;
  own.addEventListener?.('statechange',()=>{if(context===own&&own.state!=='running'&&session?.state!=='ended')session.fail({code:'call_audio'});});
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Object.assign(Error(''),{code:'call_audio'})),5000);
   const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};signal.addEventListener('abort',cancel,{once:true});
   own.resume().then(()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);if(signal.aborted||context!==own)return reject(new DOMException('Aborted','AbortError'));if(own.state!=='running')return reject(Object.assign(Error(''),{code:'call_audio'}));resolve();},()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(Object.assign(Error(''),{code:'call_audio'}));});
  });
 };
 session=new CallSession({request,capture,player,prepare,stopAudio,
  onText:text=>{caption.textContent=text;caption.scrollTop=caption.scrollHeight;},
  onSources:(citations,checkedOn)=>renderCallSources(dialog.querySelector('#ai-call-sources'),citations,checkedOn),
  onState:state=>{dialog.dataset.state=state;status.textContent=t({connecting:'Menghubungkan…',listening:'Mendengarkan',speaking:'Kilas berbicara',ended:'Panggilan berakhir.'}[state]||'Menghubungkan…');},
  onError:code=>{error.textContent=t(messages[code]||'Panggilan terputus. Periksa mikrofon dan koneksi lalu mulai panggilan baru.');error.hidden=false;}
 });
 const syncViewport=()=>{
  if(!dialog.open)return;const viewport=window.visualViewport;
  dialog.classList.toggle('ai-call-compact',(viewport?.height||window.innerHeight)<440);
  for(const [name,value] of Object.entries({width:viewport?.width||window.innerWidth,height:viewport?.height||window.innerHeight,left:viewport?.offsetLeft||0,top:viewport?.offsetTop||0})){
   if(Number.isFinite(value))dialog.style.setProperty('--ai-call-'+name,value+'px');
  }
 };
 const conceal=()=>{dialog.hidden=true;document.body.classList.remove('kilas-ai-call-open');if(launcher?.isConnected&&!document.hidden)launcher.focus({preventScroll:true});};
 const close=()=>{
  const ident=session.ident,admitted=session.admitted;session.end();
  if(ident&&admitted&&navigator.sendBeacon){const data=new FormData();data.append('csrf_token',csrf);try{navigator.sendBeacon('/kilas-ai/call/'+ident+'/end',data);}catch{}}
  if(dialog.open)dialog.close();conceal();
 };
 document.querySelectorAll('[data-ai-call-launch]').forEach(button=>button.addEventListener('click',()=>{
  if(session.state!=='ended')return;
  launcher=button;
  error.hidden=true;error.textContent='';caption.textContent='';
  if(typeof dialog.showModal!=='function'){const notice=document.querySelector('#ai-notice,#agent-chat-error');if(notice){notice.hidden=false;notice.textContent=t('Browser ini belum mendukung panggilan suara.');}return;}
  document.activeElement?.blur();dialog.hidden=false;
  try{dialog.showModal();}catch{conceal();return;}
  syncViewport();document.body.classList.add('kilas-ai-call-open');end.focus({preventScroll:true});
  const send=button.parentNode.querySelector('[type=submit]');
  if(send?.disabled){status.textContent=t('Selesaikan jawaban chat sebelum memanggil.');return;}
  session.start();
 }));
 end.addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
 dialog.addEventListener('close',()=>{session.end();conceal();});
 window.addEventListener('resize',syncViewport);window.visualViewport?.addEventListener('resize',syncViewport);window.visualViewport?.addEventListener('scroll',syncViewport);
 window.addEventListener('pagehide',close);document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});
}
