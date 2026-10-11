/* Video speech -> the existing editable script. No Translate/TTS/job auto-submit. */
(() => {
  const root=document.querySelector('#voice-video-script');if(!root)return;
  const form=document.querySelector('#voice-video-extract-form'),script=document.querySelector('#audio-script'),file=document.querySelector('#voice-video-file'),consent=document.querySelector('#voice-video-consent');
  const button=document.querySelector('#voice-video-extract'),stop=document.querySelector('#voice-video-stop'),undoButton=document.querySelector('#voice-video-undo'),status=document.querySelector('#voice-video-status');
  let version=0,operation=null,undo=null,pendingText=null,pendingKind=null;
  const applyButton=document.querySelector('#voice-video-apply');
  function discardResult(){pendingText=null;pendingKind=null;applyButton.hidden=true;}
  script.addEventListener('input',()=>{version++;undo=null;undoButton.hidden=true;});
  function write(text){script.value=text;script.dispatchEvent(new Event('input',{bubbles:true}));}
  function done(current){if(operation!==current)return;operation=null;root.dataset.busy='false';stop.hidden=true;if(button)button.disabled=root.dataset.ready!=='true';if(file)file.disabled=root.dataset.ready!=='true';if(consent)consent.disabled=root.dataset.ready!=='true';}
  function cancel(){
    discardResult();const current=operation;if(!current)return;
    operation=null;root.dataset.busy='false';current.controller.abort();stop.hidden=true;if(button)button.disabled=root.dataset.ready!=='true';if(file)file.disabled=root.dataset.ready!=='true';if(consent)consent.disabled=root.dataset.ready!=='true';
    const body=new FormData();body.append('action','cancel');body.append('operation_key',current.key);body.append('csrf_token',document.querySelector('#voiceover-panel [name=csrf_token]').value);
    fetch(current.endpoint,{method:'POST',body,credentials:'same-origin',keepalive:true}).catch(()=>{});
    status.textContent='Dihentikan. Naskah semula tetap aman. Pemrosesan yang sudah dikirim tidak diulang atau dibatalkan biayanya otomatis.';
  }
  applyButton.addEventListener('click',()=>{
    if(operation||!pendingText)return;
    const text=pendingText,before=script.value,beforeVersion=version;
    if(before&&before!==text&&!confirm('Ganti naskah sekarang dengan hasil transkripsi? Kamu bisa mengurungkannya sebelum mengedit lagi.'))return;
    if(operation||pendingText!==text||version!==beforeVersion||script.value!==before){status.textContent='Naskah berubah saat konfirmasi; edit kamu tidak ditimpa.';return;}
    const kind=pendingKind;write(text);undo={before,applied:text,version};undoButton.hidden=false;discardResult();script.scrollIntoView({block:'center'});script.focus();status.textContent=kind==='audio_reconstruction'?'Rekonstruksi audio dipakai; bukan naskah asli. Periksa dahulu, lalu Generate sendiri.':'Naskah dipakai. Periksa dahulu; Generate tetap perlu kamu klik sendiri.';
  });
  stop.addEventListener('click',cancel);file?.addEventListener('change',()=>{cancel();undo=null;undoButton.hidden=true;});
  window.addEventListener('pagehide',cancel);
  undoButton.addEventListener('click',()=>{if(operation||!undo)return;if(version!==undo.version||script.value!==undo.applied){undoButton.hidden=true;status.textContent='Naskah sudah diedit; edit tersebut tidak ditimpa.';return;}const previous=undo.before;write(previous);status.textContent='Naskah sebelum transkripsi dipulihkan.';});
  async function start(legacy=null){
    if(operation||root.dataset.ready!=='true')return;
    if(document.querySelector('#voice-script-assist')?.dataset.busy==='true'||document.querySelector('#audio-studio')?.dataset.scriptEditing==='true'||document.querySelector('#audio-studio')?.dataset.dictationBusy==='true'||document.querySelector('[data-audio-form][aria-busy=true]')){status.textContent='Selesaikan proses naskah atau audio yang sedang berjalan terlebih dahulu.';return;}
    const chosen=file?.files[0];if(!legacy&&(!chosen||!consent.checked)){status.textContent='Pilih video MP4 dan setujui pemrosesan ucapan terlebih dahulu.';return;}
    if(!legacy&&(!/\.mp4$/i.test(chosen.name)||chosen.size>Number(file.dataset.maxBytes))){status.textContent='Pilih MP4 dalam batas ukuran yang tertera. Naskah tetap aman.';return;}
    if(legacy&&!confirm('Transkripsikan ucapan dari audio hasil melalui ElevenLabs? Ini rekonstruksi, bukan naskah asli sebelum diterjemahkan. ElevenLabs memakai logging bawaan dan dapat menyimpan audio serta transkrip. Generate Voice Over tidak berjalan otomatis.'))return;
    if(operation)return;
    discardResult();
    const key=(legacy?'legacy-'+legacy.jobId+'-':'')+Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
    const current={key,endpoint:legacy?legacy.endpoint:form.action,jobId:legacy?.jobId,controller:new AbortController(),before:script.value,version};operation=current;root.dataset.busy='true';stop.hidden=false;if(button)button.disabled=true;if(file)file.disabled=true;if(consent)consent.disabled=true;
    const data=new FormData();if(!legacy)data.append('video',chosen);data.append('consent','yes');data.append('operation_key',key);data.append('csrf_token',document.querySelector('#voiceover-panel [name=csrf_token]').value);
    root.hidden=false;root.open=true;document.querySelector('#voiceover-tab')?.click();status.textContent=legacy?'Merekonstruksi ucapan dari audio hasil… Draf tetap bisa diedit.':'Membaca ucapan dari video… Naskah tetap bisa kamu edit.';
    try{
      const response=await fetch(current.endpoint,{method:'POST',body:data,credentials:'same-origin',signal:current.controller.signal});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      let result;try{result=await response.json();}catch(_){throw Error('Video belum dapat dijadikan naskah. Naskah semula tetap aman.');}
      if(!response.ok)throw Error(result.error||'Video belum dapat dijadikan naskah. Naskah semula tetap aman.');
      if(operation!==current)return;
      if(result.status!=='COMPLETED'||typeof result.text!=='string'||!result.text.trim())throw Error('Permintaan ini sudah dihentikan, belum selesai, atau pernah diproses. Tidak ada pengulangan otomatis; naskah tetap aman.');
      if(result.text.length>4000)throw Error('Hasil lebih dari 4.000 karakter. Naskah tidak dipotong atau ditimpa. Pilih video lebih pendek.');
      if(legacy&&(result.job_id!==Number(current.jobId)||!['audio_reconstruction','original_script'].includes(result.source_kind)))throw Error('Hasil tidak cocok dengan audio yang dipilih. Draf tetap aman.');
      pendingText=result.text;pendingKind=result.source_kind||'video';applyButton.textContent=legacy?'Gunakan hasil audio':'Gunakan hasil video';undoButton.textContent=legacy?'Urungkan naskah audio':'Urungkan naskah video';applyButton.hidden=false;
      if(version!==current.version||script.value!==current.before){status.textContent='Naskah sudah kamu edit selama pemrosesan. Hasil transkripsi tidak menimpa edit tersebut.';return;}
      if(current.before&&current.before!==result.text&&!confirm('Ganti naskah sekarang dengan hasil transkripsi? Kamu bisa mengurungkannya sebelum mengedit lagi.')){status.textContent='Naskah semula dipertahankan.';return;}
      if(operation!==current||version!==current.version||script.value!==current.before){status.textContent='Naskah telah berubah; edit kamu tidak ditimpa.';return;}
      discardResult();write(result.text);undo={before:current.before,applied:result.text,version};undoButton.hidden=false;script.scrollIntoView({block:'center'});script.focus();status.textContent=result.source_kind==='audio_reconstruction'?'Rekonstruksi ucapan dari audio hasil masuk ke Naskah; ini bukan naskah asli sebelum diterjemahkan. Periksa dan edit dahulu; Generate tetap perlu diklik sendiri.':result.source_kind==='original_script'?'Naskah asli tersimpan dibuka tanpa transkripsi. Generate tetap perlu diklik sendiri.':'Ucapan masuk ke kolom Naskah dalam bahasa aslinya. Periksa dahulu; Generate Voice Over tetap perlu kamu klik sendiri.';
    }catch(error){if(operation===current)status.textContent=error.name==='AbortError'?'Dihentikan. Naskah semula tetap aman.':error.message||'Video belum dapat dijadikan naskah. Naskah semula tetap aman.';}
    finally{done(current);}
  }
  form.addEventListener('submit',event=>{event.preventDefault();start();});
  document.addEventListener('click',event=>{const target=event.target.closest('[data-audio-reconstruct]');if(!target||target.disabled)return;event.preventDefault();start({endpoint:target.dataset.audioReconstruct,jobId:target.dataset.audioJobId});});
})();
