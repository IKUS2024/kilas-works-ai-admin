/* Video speech -> the existing editable script. No Translate/TTS/job auto-submit. */
(() => {
  const root=document.querySelector('#voice-video-script');if(!root)return;
  const form=document.querySelector('#voice-video-extract-form'),script=document.querySelector('#audio-script'),file=document.querySelector('#voice-video-file'),consent=document.querySelector('#voice-video-consent');
  const button=document.querySelector('#voice-video-extract'),stop=document.querySelector('#voice-video-stop'),undoButton=document.querySelector('#voice-video-undo'),status=document.querySelector('#voice-video-status');
  let version=0,operation=null,undo=null,pendingText=null;
  const applyButton=document.querySelector('#voice-video-apply');
  function discardResult(){pendingText=null;applyButton.hidden=true;}
  script.addEventListener('input',()=>{version++;undo=null;undoButton.hidden=true;});
  function write(text){script.value=text;script.dispatchEvent(new Event('input',{bubbles:true}));}
  function done(current){if(operation!==current)return;operation=null;root.dataset.busy='false';stop.hidden=true;button.disabled=root.dataset.ready!=='true';file.disabled=root.dataset.ready!=='true';consent.disabled=root.dataset.ready!=='true';}
  function cancel(){
    discardResult();const current=operation;if(!current)return;
    operation=null;root.dataset.busy='false';current.controller.abort();stop.hidden=true;button.disabled=root.dataset.ready!=='true';file.disabled=root.dataset.ready!=='true';consent.disabled=root.dataset.ready!=='true';
    const body=new FormData();body.append('action','cancel');body.append('operation_key',current.key);body.append('csrf_token',form.querySelector('[name=csrf_token]').value);
    fetch(form.action,{method:'POST',body,credentials:'same-origin',keepalive:true}).catch(()=>{});
    status.textContent='Dihentikan. Naskah semula tetap aman. Pemrosesan yang sudah dikirim tidak diulang atau dibatalkan biayanya otomatis.';
  }
  applyButton.addEventListener('click',()=>{
    if(operation||!pendingText)return;
    const text=pendingText,before=script.value,beforeVersion=version;
    if(before&&before!==text&&!confirm('Ganti naskah sekarang dengan hasil video? Kamu bisa mengurungkannya sebelum mengedit lagi.'))return;
    if(operation||pendingText!==text||version!==beforeVersion||script.value!==before){status.textContent='Naskah berubah saat konfirmasi; edit kamu tidak ditimpa.';return;}
    write(text);undo={before,applied:text,version};undoButton.hidden=false;discardResult();script.scrollIntoView({block:'center'});script.focus();status.textContent='Hasil video dipakai. Periksa naskah; Generate tetap perlu kamu klik sendiri.';
  });
  stop.addEventListener('click',cancel);file.addEventListener('change',()=>{cancel();undo=null;undoButton.hidden=true;});
  window.addEventListener('pagehide',cancel);
  undoButton.addEventListener('click',()=>{if(operation||!undo)return;if(version!==undo.version||script.value!==undo.applied){undoButton.hidden=true;status.textContent='Naskah sudah diedit; edit tersebut tidak ditimpa.';return;}const previous=undo.before;write(previous);status.textContent='Naskah sebelum unggah dipulihkan.';});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(operation||root.dataset.ready!=='true')return;
    if(document.querySelector('#voice-script-assist')?.dataset.busy==='true'||document.querySelector('#audio-studio')?.dataset.scriptEditing==='true'||document.querySelector('[data-audio-form][aria-busy=true]')){status.textContent='Selesaikan proses naskah atau audio yang sedang berjalan terlebih dahulu.';return;}
    const chosen=file.files[0];if(!chosen||!consent.checked){status.textContent='Pilih video MP4 dan setujui pemrosesan ucapan terlebih dahulu.';return;}
    if(!/\.mp4$/i.test(chosen.name)||chosen.size>Number(file.dataset.maxBytes)){status.textContent='Pilih MP4 dalam batas ukuran yang tertera. Naskah tetap aman.';return;}
    discardResult();
    const key=Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
    const current={key,controller:new AbortController(),before:script.value,version};operation=current;root.dataset.busy='true';stop.hidden=false;button.disabled=true;file.disabled=true;consent.disabled=true;
    const data=new FormData();data.append('video',chosen);data.append('consent','yes');data.append('operation_key',key);data.append('csrf_token',form.querySelector('[name=csrf_token]').value);
    status.textContent='Membaca ucapan dari video… Naskah tetap bisa kamu edit.';
    try{
      const response=await fetch(form.action,{method:'POST',body:data,credentials:'same-origin',signal:current.controller.signal});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      let result;try{result=await response.json();}catch(_){throw Error('Video belum dapat dijadikan naskah. Naskah semula tetap aman.');}
      if(!response.ok)throw Error(result.error||'Video belum dapat dijadikan naskah. Naskah semula tetap aman.');
      if(operation!==current)return;
      if(result.status!=='COMPLETED'||typeof result.text!=='string'||!result.text.trim())throw Error('Permintaan ini sudah dihentikan, belum selesai, atau pernah diproses. Tidak ada pengulangan otomatis; naskah tetap aman.');
      if(result.text.length>4000)throw Error('Hasil lebih dari 4.000 karakter. Naskah tidak dipotong atau ditimpa. Pilih video lebih pendek.');
      pendingText=result.text;applyButton.hidden=false;
      if(version!==current.version||script.value!==current.before){status.textContent='Naskah sudah kamu edit selama pemrosesan. Hasil video tidak menimpa edit tersebut.';return;}
      if(current.before&&current.before!==result.text&&!confirm('Ganti naskah sekarang dengan ucapan dari video? Kamu bisa mengurungkannya sebelum mengedit lagi.')){status.textContent='Naskah semula dipertahankan.';return;}
      if(operation!==current||version!==current.version||script.value!==current.before){status.textContent='Naskah telah berubah; edit kamu tidak ditimpa.';return;}
      discardResult();write(result.text);undo={before:current.before,applied:result.text,version};undoButton.hidden=false;script.scrollIntoView({block:'center'});script.focus();status.textContent='Ucapan masuk ke kolom Naskah dalam bahasa aslinya. Periksa dahulu; Generate Voice Over tetap perlu kamu klik sendiri.';
    }catch(error){if(operation===current)status.textContent=error.name==='AbortError'?'Dihentikan. Naskah semula tetap aman.':error.message||'Video belum dapat dijadikan naskah. Naskah semula tetap aman.';}
    finally{done(current);}
  });
})();
