import {TabAudioSession,ChunkQueue} from './kilas_live_core.mjs';
const root=document.querySelector('#live-assist');
if(root) {
  const q=id=>root.querySelector('#live-'+id),start=q('start'),stop=q('stop'),mode=q('mode'),target=q('target'),consent=q('consent'),provider=q('provider'),status=q('status'),meter=q('meter'),original=q('original'),translated=q('translated'),facts=q('facts'),reply=q('reply'),suggest=q('suggest');
  const ready=root.dataset.providerReady==='true',csrf=q('csrf').value;
  let token='',generation=0,replyController=null,pipelineController=null,replyCount=0,hasCaption=false;
  const errorMessages={consent_required:'Setujui capture audio sebelum mulai.',permission_denied:'Pemilihan tab dibatalkan atau izin ditolak.',audio_missing:'Tab tidak menyediakan audio. Pilih Tab Chrome dan aktifkan Bagikan audio tab.',tab_required:'Pilih tab Chrome, bukan jendela atau seluruh layar.',gesture_required:'Mulai melalui tombol Pilih tab & mulai.',unsupported:'Gunakan Chrome desktop melalui HTTPS.',backpressure:'Pemrosesan tertinggal. Sesi dihentikan agar potongan audio tidak menumpuk.',limit:'Batas 2 menit tercapai. Mulai sesi baru bila diperlukan.',source_ended:'Berbagi tab dihentikan. Sesi dibersihkan.',budget_unavailable:'Pemrosesan provider belum aktif. Persetujuan biaya diperlukan.'};
  if(root.dataset.qaOnly==='true')Object.assign(errorMessages,{limit:'Batas 120 detik tes sekali ini tercapai. Sesi dibersihkan.',chunk_failed:'Tes berhenti karena provider, batas biaya atau masa sesi. Tidak mencoba ulang; allowance tes sekali ini tetap terpakai.',qa_session_already_used:'Sesi QA sekali ini sudah dipakai dan tidak dapat dimulai ulang.',qa_budget_exhausted:'Sisa batas biaya QA tidak cukup. Pemrosesan dihentikan.',qa_expired:'Sesi atau izin harga QA telah berakhir.',backpressure:'Pemrosesan tertinggal. Tes sekali ini dihentikan dan tidak diulang.'});
  const post=async(operation,body,signal)=>{
    body.set('csrf_token',csrf);if(token)body.set('session_id',token);
    const response=await fetch(root.dataset.action.replace('OPERATION',operation),{method:'POST',body,signal});
    if(!response.ok){let code='provider_failed';try{code=(await response.json()).code||code;}catch{}throw Error(code);}
    return response.json();
  };
  const clear=(clearFacts=true)=>{original.replaceChildren();translated.replaceChildren();reply.value='';if(clearFacts)facts.value='';hasCaption=false;replyCount=0;suggest.disabled=true;};
  const closeProvider=()=>{++generation;queue.clear();pipelineController?.abort();replyController?.abort();pipelineController=replyController=null;const old=token;token='';if(old){const body=new FormData();body.set('session_id',old);body.set('csrf_token',csrf);fetch(root.dataset.action.replace('OPERATION','stop'),{method:'POST',body,keepalive:true}).catch(()=>{});}clear();};
  const fail=reason=>{audio.stop(reason);status.textContent=errorMessages[reason]||'Pemrosesan berhenti. Tidak ada retry otomatis. Mulai sesi baru untuk mencoba kembali.';};
  const queue=new ChunkQueue({
    send:async(chunk,signal)=>{const body=new FormData();body.set('sequence',String(chunk.sequence));body.set('audio',new Blob([chunk.buffer],{type:'audio/wav'}),'tab-audio.wav');return post('chunk',body,signal);},
    onResult:data=>{if(data.silence){status.textContent='Audio tab aktif · potongan hening dilewati.';return;}for(const [node,text] of [[original,data.original],[translated,data.translated]]){const p=document.createElement('p');p.textContent=text;node.append(p);while(node.children.length>12)node.firstElementChild.remove();node.scrollTop=node.scrollHeight;}hasCaption=true;suggest.disabled=mode.value!=='call'||replyCount>=3;status.textContent='Mendengarkan audio tab · caption dan terjemahan diperbarui.';},onError:fail});
  const audio=new TabAudioSession({enabled:true,mediaDevices:navigator.mediaDevices,
    onLevel:value=>{meter.value=value;},
    onChunk:chunk=>{if(provider.checked){if(token)queue.push(chunk);else fail('session_start_slow');}},
    onState:({state,reason})=>{
      root.dataset.state=state;root.dataset.reason=reason;const active=state==='active'||state==='starting';start.disabled=active;stop.disabled=!active;mode.disabled=target.disabled=consent.disabled=active;provider.disabled=active||!ready;
      q('indicator').textContent=state==='active'?'● Audio tab aktif':state==='starting'?'Memilih sumber audio…':'Audio tab tidak aktif.';
      if(state==='starting'){clear(false);status.textContent='Pilih Tab Chrome dan centang Bagikan audio tab.';}
      else if(state==='active'){status.textContent=provider.checked?'Audio tab aktif · menyiapkan pemrosesan…':'Audio tab aktif · pemrosesan provider tidak aktif; belum ada caption.';}
      else {closeProvider();status.textContent=errorMessages[reason]||'Berhenti. Audio dan teks sesi dibersihkan.';}
    }});
  mode.addEventListener('change',()=>{q('call').hidden=mode.value!=='call';});
  start.addEventListener('click',async event=>{
    if(start.disabled)return;
    const sampleConsent=q('sample-consent');
    if(sampleConsent&&provider.checked&&!sampleConsent.checked){status.textContent='Setujui penggunaan audio contoh non-sensitif untuk tes sekali ini.';return;}
    const pending=audio.start({consent:consent.checked,userGesture:event.isTrusted}); // No awaited network request before chooser.
    await pending;if(audio.state!=='active'||!provider.checked)return;
    const ticket=generation;pipelineController=new AbortController();
    const body=new FormData();body.set('consent','yes');body.set('mode',mode.value);body.set('target',target.value);
    if(sampleConsent?.checked)body.set('sample_consent','yes');
    try{const data=await post('start',body,pipelineController.signal);if(ticket!==generation){const cleanup=new FormData();cleanup.set('session_id',data.session_id);cleanup.set('csrf_token',csrf);fetch(root.dataset.action.replace('OPERATION','stop'),{method:'POST',body:cleanup,keepalive:true}).catch(()=>{});return;}token=data.session_id;status.textContent='Mendengarkan audio tab · menunggu potongan pertama sekitar 10 detik.';}
    catch(error){if(ticket===generation)fail(error.message);}
  });
  stop.addEventListener('click',()=>audio.stop());
  suggest.addEventListener('click',async()=>{
    if(!token||!hasCaption||mode.value!=='call'||replyCount>=3||suggest.disabled)return;
    if(reply.value&&!confirm('Ganti draft jawaban yang sudah kamu edit?'))return;
    reply.disabled=true;
    suggest.disabled=true;replyCount++;const ticket=generation;replyController=new AbortController();const body=new FormData();body.set('operation_key',crypto.randomUUID());body.set('facts',facts.value);
    status.textContent='Menyiapkan draft jawaban untuk kamu periksa…';
    try{const data=await post('reply',body,replyController.signal);if(ticket===generation){reply.value=data.text;status.textContent='Draft siap. Periksa fakta dan ubah sebelum membacanya sendiri.';}}
    catch(error){if(ticket===generation)status.textContent=errorMessages[error.message]||'Draft belum tersedia. Tidak mencoba ulang otomatis.';}
    finally{reply.disabled=false;if(ticket===generation)suggest.disabled=replyCount>=3;}
  });
  window.addEventListener('pagehide',()=>audio.stop('source_ended'));
}
