import {VoiceRecorder} from './kilas_transcription_recorder.mjs';

export function bindTranscription(root) {
  const panel=root.querySelector('[data-transcription]');if(!panel)return ()=>{};
  const q=name=>panel.querySelector(`[data-stt-${name}]`),consent=q('consent'),file=q('file'),record=q('record'),stop=q('stop'),send=q('send'),cancel=q('cancel'),discard=q('discard'),preview=q('preview'),text=q('text'),use=q('use'),status=q('status');
  const enabled=panel.dataset.ready==='true',csrf=root.querySelector('[name=csrf_token]').value;
  let audio=null,url=null,key=panel.dataset.key||'',busy=false,epoch=0,controller=null,disposed=false,recording=false;
  const endpoint=()=>panel.dataset.url.replace('OPERATION_KEY',encodeURIComponent(key));
  const unlock=()=>{text.disabled=busy;record.disabled=!enabled||busy||recording;file.disabled=!enabled||busy||recording;send.disabled=!enabled||busy||recording||!audio||!consent.checked;cancel.hidden=!busy;stop.hidden=!recording;discard.hidden=!audio&&!text.value;};
  const dropAudio=()=>{if(url)URL.revokeObjectURL(url);url=null;audio=null;preview.pause();preview.removeAttribute('src');preview.hidden=true;};
  const showAudio=blob=>{++epoch;dropAudio();key='';panel.dataset.key='';audio=blob;url=URL.createObjectURL(blob);preview.src=url;preview.hidden=false;unlock();};
  const update=data=>{
    if(data.project_id!==Number(panel.dataset.url.match(/projects\/(\d+)/)[1])||data.conversation_id!==Number(root.dataset.conversation))throw Error('Respons proyek tidak cocok. Muat ulang chat.');
    if(data.status==='COMPLETED'){text.value=data.text;use.disabled=false;status.textContent='Transkrip siap. Periksa dan edit sebelum memakai naskah.';}
    else if(data.status==='PROCESSING')status.textContent='Permintaan belum selesai. Muat ulang untuk memeriksa status; jangan kirim ulang dengan permintaan baru.';
    else {use.disabled=true;status.textContent=data.status==='CANCELLED'?'Transkripsi dibatalkan.':'Hasil transkripsi belum tersedia atau tidak pasti. Mencoba lagi dengan audio baru dapat menimbulkan biaya baru.';}
    unlock();
  };
  const recorder=new VoiceRecorder({mediaDevices:navigator.mediaDevices,Recorder:window.MediaRecorder,
    onBlob:showAudio,onState:state=>{recording=state==='recording';status.textContent=state==='recording'?'Mikrofon aktif. Hentikan untuk mendengarkan rekaman.':state==='error'?'Rekaman gagal. Periksa izin mikrofon.':state==='cancelled'?'Rekaman dibatalkan.':'Rekaman siap didengarkan.';unlock();}});
  record.addEventListener('click',async event=>{
    if(!enabled||busy||recording)return;
    if(audio&&!confirm('Ganti audio yang dipilih?'))return;
    recording=true;unlock();
    try {await recorder.start({userGesture:event.isTrusted,consent:consent.checked,enabled});}catch(error){recording=false;unlock();status.textContent=error.message==='Setujui pemrosesan audio dan mulai rekaman melalui tombol.'?error.message:'Mikrofon belum tersedia. Periksa izin lalu coba lagi.';}
  });
  stop.addEventListener('click',()=>recorder.stop());
  consent.addEventListener('change',()=>{if(!consent.checked&&recording){recorder.cancel();recording=false;dropAudio();}unlock();});
  file.addEventListener('change',()=>{if(busy)return;const item=file.files[0];if(!item)return;if(item.size>10*1024*1024){status.textContent='Audio maksimal 10 MiB.';file.value='';return;}showAudio(item);status.textContent='Audio siap didengarkan. Klik Transkripsikan audio untuk mengirim.';});
  const cancelBody=()=>{const body=new FormData();body.set('csrf_token',csrf);body.set('action','cancel');return body;};
  cancel.addEventListener('click',async()=>{
    if(!key)return;const ticket=++epoch;controller?.abort();
    status.textContent='Meminta pembatalan…';
    try {const response=await fetch(endpoint(),{method:'POST',body:cancelBody()});if(!response.ok)throw Error();const data=await response.json();if(ticket===epoch&&!disposed){busy=false;update(data);}}
    catch {if(ticket===epoch&&!disposed){busy=false;status.textContent='Pembatalan belum terkonfirmasi. Muat ulang untuk memeriksa status.';unlock();}}
  });
  discard.addEventListener('click',()=>{if(busy)return;recorder.cancel();recording=false;dropAudio();text.value='';use.disabled=true;file.value='';status.textContent='Audio dan draft lokal dibuang. Transkrip server dan versi proyek tetap tersimpan.';unlock();});
  send.addEventListener('click',async()=>{
    if(!enabled||busy||recording||!audio||!consent.checked)return;
    if(text.value&&!confirm('Ganti draft transkrip dengan hasil baru?'))return;
    if(key&&status.textContent.includes('belum selesai'))return;
    key=key||crypto.randomUUID();panel.dataset.key=key;const ticket=++epoch;controller=new AbortController();busy=true;unlock();
    text.value='';use.disabled=true;status.textContent='Mengirim audio untuk transkripsi…';
    const body=new FormData();body.set('csrf_token',csrf);body.set('consent','yes');body.set('audio',audio,audio.name||'recording');
    try {const response=await fetch(endpoint(),{method:'POST',body,signal:controller.signal});const data=await response.json();if(ticket!==epoch||disposed)return;if(!response.ok)throw Error(data.error||'Transkripsi belum berhasil.');busy=false;update(data);}
    catch(error){if(ticket===epoch&&!disposed){busy=false;status.textContent=error.name==='AbortError'?'Periksa status permintaan sebelum mencoba lagi.':error.message==='Failed to fetch'?'Koneksi terputus. Muat ulang untuk memeriksa status; permintaan bisa sudah diproses.':error.message;unlock();}}
  });
  use.addEventListener('click',()=>{
    if(!text.value.trim())return;const script=root.querySelector('textarea[name=script]');if(!script)return;
    if(script.value&&script.value!==text.value&&!confirm('Ganti draft naskah yang belum disimpan?'))return;
    script.value=text.value;root.querySelector('[name=reviewed]').checked=false;script.closest('details').open=true;script.focus();status.textContent='Draft disalin. Periksa naskah dan simpan sebagai versi baru.';
  });
  // Recover persisted status after reload, but never automatically submit audio.
  text.addEventListener('input',()=>{++epoch;});
  if(key){const recoveryEpoch=epoch;fetch(endpoint(),{headers:{Accept:'application/json'}}).then(async response=>{if(response.ok){const data=await response.json();if(!disposed&&epoch===recoveryEpoch)update(data);}}).catch(()=>{if(!disposed&&epoch===recoveryEpoch)status.textContent='Status belum terbaca. Muat ulang chat.';});}
  unlock();
  return ()=>{if(disposed)return;disposed=true;++epoch;controller?.abort();recorder.cancel();dropAudio();if(busy&&key)fetch(endpoint(),{method:'POST',body:cancelBody(),keepalive:true}).catch(()=>{});};
}
