import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-reliable-20261023';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-output-20261024';
import {CallSession} from './kilas_ai_call_engine.mjs?v=call-reliable-20261023';
import {renderCallSources} from './kilas_ai_call_sources.mjs?v=call-public-search-20261017';

const dialog=document.querySelector('#ai-call-dialog');
if(dialog){
 // The Call belongs to the viewport, outside the chat layout and its forms.
 document.body.append(dialog);
 const status=dialog.querySelector('#ai-call-status'),caption=dialog.querySelector('#ai-call-caption'),error=dialog.querySelector('#ai-call-error'),end=dialog.querySelector('#ai-call-end');
 const csrf=document.querySelector('meta[name=csrf-token]')?.content||document.querySelector('[name=csrf_token]')?.value;
 let context=null,output=null,launcher=null,busyChat=false,muted=false,held=false,speaker=true;
 const settings=dialog.querySelector('#ai-call-settings'),start=dialog.querySelector('#ai-call-start'),normal=dialog.querySelector('#ai-call-normal');
 const field=name=>dialog.querySelector('#ai-call-'+name);
 const controls=dialog.querySelector('.reference-call-actions');
 const syncControls=()=>{
  for(const track of capture.stream?.getAudioTracks()||[])track.enabled=!muted&&!held;
  if(output)output.gain.value=speaker&&!held?1:0;
  field('mute')?.setAttribute('aria-pressed',String(muted));field('hold')?.setAttribute('aria-pressed',String(held));field('speaker')?.setAttribute('aria-pressed',String(speaker));
  if(controls)controls.hidden=session?.state==='ended';
 };
 const statusRegion=dialog.querySelector('.reference-call-status');
 if(statusRegion)dialog.insertBefore(statusRegion,dialog.querySelector('.ai-call-footer'));
 const statusCapsule=statusRegion?.querySelector('span');
 if(statusCapsule)new window.MutationObserver(()=>{statusCapsule.textContent=status.textContent;}).observe(status,{childList:true,subtree:true,characterData:true});
 const syncSettings=()=>{
  const mode=field('mode').value,roast=mode==='roast';
  field('learning').hidden=mode!=='learning';field('roleplay').hidden=mode!=='roleplay';field('consent').hidden=!roast;
  for(const option of field('character').options)option.disabled=roast?option.value!=='roast':option.value==='roast';
  if(roast)field('character').value='roast';else if(field('character').value==='roast')field('character').value='friendly';
  if(!roast)field('roast-opt-in').checked=false;
  start.disabled=busyChat||(roast&&!field('roast-opt-in').checked);
 };
 field('mode').addEventListener('change',syncSettings);field('roast-opt-in').addEventListener('change',syncSettings);
 const chosenSettings=()=>({mode:field('mode').value,character:field('character').value,
  target_language:field('target-language').value,level:field('level').value,
  explanation_language:field('explanation-language').value,scenario:field('scenario').value,roast_opt_in:field('roast-opt-in').checked});
 const request=(url,options={})=>requestJSON(url,{csrf,...options});
 const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
 const captureStart=capture.start.bind(capture);
 capture.start=options=>captureStart({...options,ready:()=>{syncControls();options.ready?.();},pcm:raw=>options.pcm(muted||held?new Uint8Array(raw.length):raw)});
 let session;
 const player=new CallPlayer({getContext:()=>context,getDestination:ctx=>output||ctx.destination,onError:()=>session?.fail({code:'call_audio'})});
 const messages={call_unavailable:'Panggilan belum tersedia untuk akun ini.',budget_limit:'Batas biaya tercapai. Panggilan dihentikan.',
  account_credit_limit:'Kapasitas Premium belum cukup untuk permintaan ini. Tambah kapasitas atau lanjutkan Chat biasa.',
  already_processing:'Selesaikan sesi suara yang sedang diproses sebelum memanggil.',service_busy:'Layanan sedang sibuk. Coba panggil lagi nanti.',
  attempt_limit:'Batas panggilan tercapai. Coba lagi nanti.',
  call_network:'Koneksi panggilan belum pulih. Pengaturan tetap tersimpan; mulai lagi saat siap.',
  request_timeout:'Koneksi panggilan belum pulih. Pengaturan tetap tersimpan; mulai lagi saat siap.',
  call_backlog:'Pengiriman audio tertunda terlalu lama. Pengaturan tetap tersimpan; coba lagi.',
  call_provider:'Layanan suara menghentikan sesi. Pengaturan tetap tersimpan; coba lagi.',
  call_provider_disconnected:'Layanan suara terputus dan konteks tidak dapat dipulihkan. Mulai panggilan baru saat siap.',
  call_transport:'Sesi suara terhenti. Pengaturan tetap tersimpan; coba mulai lagi.',
  call_protocol:'Respons sesi tidak valid. Mulai panggilan baru saat siap.',
  call_output_invalid:'Respons audio tidak valid. Mulai panggilan baru saat siap.',
  microphone_unavailable:'Mikrofon tidak lagi tersedia. Sambungkan kembali lalu mulai panggilan.',
  realtime_input_timeout:'Browser berhenti mengirim audio mikrofon. Buka kembali tab ini lalu mulai panggilan.',
  realtime_capture_failed:'Perekam audio browser berhenti. Mulai panggilan baru saat siap.',
  call_ended:'Panggilan berakhir.',call_audio:'Audio belum siap. Periksa izin audio lalu mulai panggilan baru.',
  microphone_permission_denied:'Izin mikrofon ditolak. Izinkan mikrofon lalu mulai panggilan baru.'};
 let audioRecoveryTimer=null;
 const stopAudio=()=>{clearTimeout(audioRecoveryTimer);audioRecoveryTimer=null;const own=context;context=null;output=null;if(own){try{own.close().catch(()=>{});}catch{}}};
 const prepare=signal=>{
  const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Object.assign(Error(''),{code:'call_audio'});
  context=new Audio({latencyHint:'playback'});const own=context;output=own.createGain();output.connect(own.destination);syncControls();
  own.addEventListener?.('statechange',()=>{
   if(context!==own||signal.aborted||session?.state==='ended')return;
   if(own.state==='running'){clearTimeout(audioRecoveryTimer);audioRecoveryTimer=null;try{player.resume();}catch{session.fail({code:'call_audio'});}return;}
   if(audioRecoveryTimer)return;
   player.suspend();status.textContent=t('Memulihkan audio…');
   audioRecoveryTimer=setTimeout(()=>{audioRecoveryTimer=null;if(context===own&&!signal.aborted&&own.state!=='running')session.fail({code:'call_audio'});},3500);
   // Resume the existing context only. Never reacquire a mic or restart an ended call.
   if(own.state==='suspended')Promise.resolve(own.resume()).catch(()=>{});
  });
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Object.assign(Error(''),{code:'call_audio'})),5000);
   const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};signal.addEventListener('abort',cancel,{once:true});
   own.resume().then(()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);if(signal.aborted||context!==own)return reject(new DOMException('Aborted','AbortError'));if(own.state!=='running')return reject(Object.assign(Error(''),{code:'call_audio'}));resolve();},()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(Object.assign(Error(''),{code:'call_audio'}));});
  });
 };
 session=new CallSession({request,capture,player,prepare,stopAudio,
  onText:text=>{caption.textContent=text;caption.scrollTop=caption.scrollHeight;},
  onSources:(citations,checkedOn)=>renderCallSources(dialog.querySelector('#ai-call-sources'),citations,checkedOn),
  onState:state=>{if(state==='connecting'){dialog.scrollTop=0;}if(state==='ended'){muted=false;held=false;speaker=true;}queueMicrotask(syncControls);settings.hidden=state!=='ended';start.hidden=state!=='ended';normal.hidden=state==='ended';end.hidden=state==='ended';field('end-label').hidden=state==='ended';field('summary').hidden=state==='ended';dialog.dataset.state=state;status.textContent=held?t('On hold'):t({reconnecting:'Menghubungkan kembali…',connecting:'Menghubungkan…',listening:'Mendengarkan',speaking:'Kilas berbicara',ended:'Panggilan berakhir.'}[state]||'Menghubungkan…');},
  onError:code=>{error.textContent=t(messages[code]||messages.call_transport);error.hidden=false;start.textContent=t('Coba panggilan lagi');}
 });
 field('mute')?.addEventListener('click',()=>{muted=!muted;syncControls();});
 field('hold')?.addEventListener('click',()=>{held=!held;syncControls();if(held)status.textContent=t('On hold');else status.textContent=t(session.state==='speaking'?'Kilas berbicara':'Mendengarkan');});
 field('speaker')?.addEventListener('click',()=>{speaker=!speaker;syncControls();});
 // Keep End in the same action row, with the existing cancellation handler.
 const endSlot=dialog.querySelector('.reference-call-end-slot');if(endSlot)endSlot.append(end,field('end-label'));
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
  launcher=button;busyChat=false;field('roast-opt-in').checked=false;
  error.hidden=true;error.textContent='';caption.textContent='';
  if(typeof dialog.showModal!=='function'){const notice=document.querySelector('#ai-notice,#agent-chat-error');if(notice){notice.hidden=false;notice.textContent=t('Browser ini belum mendukung panggilan suara.');}return;}
  document.activeElement?.blur();dialog.hidden=false;
  try{dialog.showModal();}catch{conceal();return;}
  syncViewport();document.body.classList.add('kilas-ai-call-open');dialog.dataset.state='ended';settings.hidden=false;start.hidden=false;normal.hidden=true;end.hidden=true;field('end-label').hidden=true;field('summary').hidden=true;start.textContent=t('Mulai panggilan');syncSettings();start.focus({preventScroll:true});
 const send=button.closest('.kilas-home-workspace')?.querySelector('#ai-send,#agent-chat-form button[type=submit]')||button.parentNode.querySelector('[type=submit]');
  if(send?.disabled){busyChat=true;start.disabled=true;status.textContent=t('Selesaikan jawaban chat sebelum memanggil.');return;}
  status.textContent=t('Pilih mode, lalu mulai panggilan.');
 }));
 start.addEventListener('click',()=>{if(start.disabled)return;error.hidden=true;field('summary').textContent=field('mode').selectedOptions[0].textContent+' · '+field('character').selectedOptions[0].textContent;session.start(chosenSettings());});
 normal.addEventListener('click',()=>{session.end();field('mode').value='normal';field('character').value='friendly';field('roast-opt-in').checked=false;syncSettings();status.textContent=t('Audio dihentikan. Mulai lagi dalam mode Normal.');start.focus({preventScroll:true});});
 field('close').addEventListener('click',close);
 end.addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
 dialog.addEventListener('close',()=>{session.end();conceal();});
 window.addEventListener('resize',syncViewport);window.visualViewport?.addEventListener('resize',syncViewport);window.visualViewport?.addEventListener('scroll',syncViewport);
 window.addEventListener('pagehide',close);document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});
}
