(() => {
  const setup=document.querySelector('#personal-voice-setup');if(!setup||setup.dataset.initialized)return;setup.dataset.initialized='true';
  const panel=document.querySelector('#voice-recorder'),open=document.querySelector('#open-recorder');
  const start=document.querySelector('#record-start'),stop=document.querySelector('#record-stop'),again=document.querySelector('#record-again'),cancel=document.querySelector('#record-cancel');
  const playback=document.querySelector('#record-playback'),consent=document.querySelector('#voice-consent'),save=document.querySelector('#save-personal-voice');
  const state=document.querySelector('#record-state'),timer=document.querySelector('#record-timer'),error=document.querySelector('#record-error');
  const selected=document.querySelector('#selected-voice'),stock=document.querySelector('#kilas-voice-choice'),generate=document.querySelector('#voice-generate');
  const library=document.querySelector('#saved-voice-choice'),nameInput=document.querySelector('#record-voice-name');
  const upload=document.querySelector('#voice-sample-file'),selection=document.querySelector('#voice-sample-selection');
  let replacing='';
  let recorder=null,stream=null,tick=null,blob=null,objectUrl='',started=0,version=0,saving=false,inspecting=false,inspection=null,inspectionTimer=null,filename='recording';
  function fail(text){error.textContent=text;error.hidden=false;}
  function tracksOff(){stream?.getTracks().forEach(t=>t.stop());stream=null;clearInterval(tick);tick=null;}
  function discard(){inspection?.abort();inspection=null;clearTimeout(inspectionTimer);inspectionTimer=null;inspecting=false;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl='';blob=null;filename='recording';upload.value='';selection.textContent='';selection.hidden=true;playback.pause();playback.removeAttribute('src');playback.hidden=true;consent.checked=false;save.disabled=true;}
  function choices(){const mine=document.querySelector('[name=voice_kind]:checked').value==='personal';setup.hidden=!mine;document.querySelector('#kilas-voice-options').hidden=mine;selected.value=mine?(library.value?'personal:'+library.value:''):stock.value;generate.disabled=setup.dataset.translationReady==='false'||saving||!panel.hidden||generate.dataset.enabled!=='true'||(mine?!library.value:!stock.value);}
  document.querySelectorAll('[name=voice_kind]').forEach(el=>el.addEventListener('change',()=>{if(!panel.hidden&&!saving){version++;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;}choices();}));stock.addEventListener('change',choices);document.addEventListener('voice-translation-state',choices);choices();
  function openRecorder(replace){if(saving||generate.dataset.enabled!=='true')return;if(replace&&(!library.value||!confirm('Ganti contoh suara ini? Suara saat ini tetap tersedia sampai penggantian berhasil.')))return;replacing=replace?library.value:'';nameInput.value=replace?library.selectedOptions[0].textContent:'Suara Saya';error.hidden=true;document.querySelector('#personal-ready').hidden=true;panel.hidden=false;state.textContent='Pilih file audio atau mulai merekam';timer.textContent='0:00';start.hidden=false;stop.hidden=true;again.hidden=true;choices();nameInput.focus({preventScroll:true});}
  open.addEventListener('click',()=>openRecorder(true));document.querySelector('#add-saved-voice').addEventListener('click',()=>openRecorder(false));
  upload.addEventListener('change',async()=>{
    const file=upload.files?.[0];if(saving||!file)return; // Closing the picker keeps the current sample.
    const current=++version;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();error.hidden=true;setup.dataset.operationKey=crypto.randomUUID().replaceAll('-','');
    start.hidden=false;start.disabled=false;stop.hidden=true;again.hidden=true;timer.textContent='0:00';state.textContent='Memeriksa audio…';
    const extension=file.name.split('.').pop().toLowerCase(),mime=file.type.split(';')[0].toLowerCase();
    const allowed=['audio/mpeg','audio/mp3','audio/wav','audio/x-wav','audio/vnd.wave','audio/mp4','audio/x-m4a','audio/ogg','audio/webm'];
    if(!file.size||file.size>10*1024*1024||(!allowed.includes(mime)&&!(['','application/octet-stream'].includes(mime)&&['mp3','wav','m4a','ogg','webm'].includes(extension)))){
      state.textContent='Audio belum dipilih';fail(!file.size?'File audio kosong. Pilih file lain.':file.size>10*1024*1024?'Audio maksimal 10 MB dan 3 menit. Pilih file yang lebih kecil.':'Format tidak didukung. Pilih MP3, WAV, M4A, OGG, atau WebM.');return;
    }
    inspecting=true;inspection=new AbortController();const controller=inspection,signal=controller.signal;let timedOut=false;
    inspectionTimer=setTimeout(()=>{timedOut=true;controller.abort();},30000);
    selection.hidden=false;selection.textContent=file.name;
    const data=new FormData(),csrf=document.querySelector('#audio-studio [name=csrf_token]').value;data.append('csrf_token',csrf);data.append('recording',file,file.name);
    try{
      const response=await fetch('/kilas-translator/personal-voice/inspect',{method:'POST',body:data,credentials:'same-origin',signal,headers:{'X-CSRF-Token':csrf}});
      if(current!==version)return;if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      const body=await response.json();if(current!==version)return;if(!response.ok)throw Error(body.error||'Audio belum dapat dibaca. Pilih file lain atau coba lagi.');
      if(!Number.isFinite(body.duration_ms)||body.duration_ms<=0||body.duration_ms>180000)throw Error('Audio maksimal 3 menit. Pilih file yang lebih singkat.');
      blob=file;filename=file.name;objectUrl=URL.createObjectURL(file);playback.src=objectUrl;playback.hidden=false;
      const seconds=Math.ceil(body.duration_ms/1000);timer.textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
      state.textContent='Audio siap didengarkan';save.disabled=!consent.checked;
    }catch(e){if(current!==version)return;discard();state.textContent='Audio belum dapat digunakan';fail(timedOut?'Pemeriksaan audio terlalu lama. Pilih file lagi untuk mencoba kembali.':e instanceof SyntaxError||e instanceof TypeError?'Audio belum dapat diperiksa. Pilih file lagi untuk mencoba kembali.':e.message);}
    finally{if(current===version){clearTimeout(inspectionTimer);inspectionTimer=null;inspecting=false;inspection=null;save.disabled=saving||!blob?.size||!consent.checked;}}
  });
  playback.addEventListener('error',()=>{if(blob&&!saving)fail('Contoh audio belum dapat diputar di perangkat ini. Coba perangkat lain untuk mendengarkan sebelum menyimpan.');});
  async function record(){
    if(saving)return;
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){fail('Mikrofon belum dapat digunakan. Periksa izin mikrofon lalu coba lagi.');return;}
    const current=++version;discard();error.hidden=true;setup.dataset.operationKey=crypto.randomUUID().replaceAll('-','');start.disabled=true;state.textContent='Menunggu izin mikrofon…';
    try{
      const incoming=await navigator.mediaDevices.getUserMedia({audio:true});if(current!==version){incoming.getTracks().forEach(t=>t.stop());return;}stream=incoming;
      const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
      recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);const chunks=[];
      recorder.addEventListener('dataavailable',e=>{if(e.data.size)chunks.push(e.data);});
      recorder.addEventListener('stop',()=>{if(current!==version)return;tracksOff();blob=new Blob(chunks,{type:recorder.mimeType||mime||'audio/webm'});objectUrl=URL.createObjectURL(blob);playback.src=objectUrl;playback.hidden=false;start.hidden=true;stop.hidden=true;again.hidden=false;state.textContent=Date.now()-started<60000?'Rekaman singkat. Disarankan 60-120 detik untuk kemiripan lebih baik.':'Rekaman siap didengarkan';save.disabled=!consent.checked||!blob.size;start.disabled=false;});
      recorder.addEventListener('error',()=>{if(current!==version)return;version++;tracksOff();discard();stop.hidden=true;start.hidden=false;start.disabled=false;state.textContent='Rekaman belum berhasil';fail('Mikrofon belum dapat digunakan. Upload audio atau periksa izin mikrofon lalu coba lagi.');});
      recorder.start();started=Date.now();start.hidden=true;stop.hidden=false;again.hidden=true;state.textContent='Mikrofon aktif · sedang merekam';
      tick=setInterval(()=>{const seconds=Math.floor((Date.now()-started)/1000);timer.textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;if(seconds>=179&&recorder.state==='recording')recorder.stop();},250);
    }catch{if(current!==version)return;tracksOff();start.disabled=false;state.textContent='Mikrofon belum tersedia';fail('Mikrofon belum dapat digunakan. Upload audio atau periksa izin mikrofon lalu coba lagi.');}
  }
  start.addEventListener('click',record);again.addEventListener('click',record);stop.addEventListener('click',()=>{if(recorder?.state==='recording'){stop.disabled=true;recorder.stop();stop.disabled=false;}});
  cancel.addEventListener('click',()=>{if(saving)return;version++;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;start.disabled=false;choices();open.focus({preventScroll:true});});
  consent.addEventListener('change',()=>{save.disabled=saving||inspecting||!blob?.size||!consent.checked;});
  save.addEventListener('click',async()=>{
    if(saving||inspecting||!blob?.size||!consent.checked)return;if(!nameInput.value.trim()){fail('Beri nama suara sebelum menyimpan.');nameInput.focus();return;}saving=true;setup.dataset.busy='true';error.hidden=true;choices();
    const controls=[...panel.querySelectorAll('button,input')];controls.forEach(el=>el.disabled=true);open.disabled=true;state.textContent='Sedang membuat Suara Saya…';
    const data=new FormData();data.append('csrf_token',document.querySelector('#audio-studio [name=csrf_token]').value);data.append('recording',blob,filename);data.append('consent','yes');data.append('operation_key',setup.dataset.operationKey);data.append('name',nameInput.value.trim());if(replacing)data.append('saved_voice_id',replacing);
    try{
      const response=await fetch('/kilas-translator/personal-voice',{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':document.querySelector('#audio-studio [name=csrf_token]').value}});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      const body=await response.json();if(!response.ok)throw Error(body.error||'Suara belum berhasil dibuat. Rekamanmu tetap aman untuk dicoba kembali.');
      setup.dataset.ready='true';setup.dataset.operationKey=crypto.randomUUID().replaceAll('-','');document.querySelector('#personal-voice-state').textContent='Siap digunakan';
      let option=[...library.options].find(el=>el.value===String(body.id));if(!option){library.querySelector('option[value=""]')?.remove();option=new Option(body.name,String(body.id));library.add(option);}option.textContent=body.name;option.dataset.preview='true';library.value=String(body.id);discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;updateLibrary();
    }catch(e){fail(e instanceof SyntaxError||e instanceof TypeError?'Suara belum berhasil dibuat. Rekamanmu tetap aman untuk dicoba kembali.':e.message);state.textContent='Rekaman siap dicoba kembali';}
    finally{saving=false;setup.dataset.busy='false';controls.forEach(el=>el.disabled=false);open.disabled=false;save.disabled=!blob?.size||!consent.checked;updateLibrary();}
  });
  window.addEventListener('pagehide',()=>{version++;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();});
  const script=document.querySelector('#audio-script'),language=document.querySelector('#voice-language'),label=document.querySelector('#voice-language-status');
  function detect(){
    if(language.value!=='auto'){label.textContent='Bahasa mengikuti naskah, kecuali kamu memilih Terjemahkan ke.';return;}
    const words=script.value.toLowerCase().match(/[a-z]+/g)||[];
    const id=words.filter(w=>['saya','kamu','selamat','datang','hari','ini','kita','untuk','dengan','dan','yang','suara','membuat'].includes(w)).length;
    const en=words.filter(w=>['welcome','good','morning','today','we','are','building','something','new','the','and','my','your','this','is','hello'].includes(w)).length;
    label.textContent=id>=2&&id>en?'Bahasa terdeteksi: Indonesian':en>=2&&en>id?'Bahasa terdeteksi: English':'Bahasa mengikuti naskah, kecuali kamu memilih Terjemahkan ke.';
  }
  script.addEventListener('input',detect);language.addEventListener('change',detect);
  document.querySelector('#play-personal-preview').addEventListener('click',async()=>{const sample=document.querySelector('#personal-preview'),notice=document.querySelector('#voice-preview-error');notice.hidden=true;try{sample.hidden=false;await sample.play();}catch{notice.textContent='Contoh suara belum dapat diputar. Coba lagi.';notice.hidden=false;}});
  function updateLibrary(){
    const ready=!!library.value,option=library.selectedOptions[0],sample=document.querySelector('#personal-preview');
    setup.dataset.ready=String(ready);document.querySelector('#personal-voice-state').textContent=ready?'Siap digunakan':'Suara kamu sendiri';
    sample.pause();sample.removeAttribute('src');sample.hidden=!ready||option.dataset.preview!=='true';
    if(!sample.hidden)sample.src='/kilas-translator/personal-voices/'+library.value+'/preview?v='+setup.dataset.operationKey;
    document.querySelector('#play-personal-preview').hidden=sample.hidden;document.querySelector('#voice-preview-missing').hidden=!ready||!sample.hidden;
    [open,document.querySelector('#rename-saved-voice'),document.querySelector('#delete-saved-voice')].forEach(el=>el.disabled=!ready||saving);
    open.disabled=open.disabled||generate.dataset.enabled!=='true';document.querySelector('#add-saved-voice').disabled=saving||generate.dataset.enabled!=='true';
    document.querySelector('#saved-voice-notice').textContent=ready?'Suara ini digunakan untuk Voice Over berikutnya.':'Rekam atau upload audio untuk menyimpannya di akun kamu.';
    choices();
  }
  library.addEventListener('change',()=>{document.querySelector('#saved-voice-rename').hidden=true;updateLibrary();});
  const renamePanel=document.querySelector('#saved-voice-rename'),newName=document.querySelector('#saved-voice-new-name'),libraryError=document.querySelector('#saved-voice-error');
  document.querySelector('#rename-saved-voice').addEventListener('click',()=>{if(saving||!library.value)return;renamePanel.hidden=false;newName.value=library.selectedOptions[0].textContent;newName.focus();});
  document.querySelector('#cancel-voice-name').addEventListener('click',()=>{renamePanel.hidden=true;});
  async function manage(action){
    if(saving||!library.value)return;const ident=library.value;
    if(action==='delete'&&!confirm('Hapus suara “'+library.selectedOptions[0].textContent+'”? Rekaman suara akan dihapus. MP3 yang sudah dibuat tetap tersedia.'))return;
    if(action==='rename'&&!newName.value.trim()){libraryError.textContent='Beri nama suara sebelum menyimpan.';libraryError.hidden=false;return;}
    saving=true;libraryError.hidden=true;library.disabled=true;choices();const buttons=[...document.querySelector('#personal-ready').querySelectorAll('button')];buttons.forEach(el=>el.disabled=true);
    document.querySelector('#saved-voice-notice').textContent=action==='delete'?'Menghapus suara…':'Menyimpan nama…';
    try{
      const data=new FormData();const csrf=document.querySelector('#audio-studio [name=csrf_token]').value;data.append('csrf_token',csrf);if(action==='rename')data.append('name',newName.value.trim());
      const response=await fetch('/kilas-translator/personal-voices/'+ident+'/'+action,{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      const body=await response.json();if(!response.ok)throw Error(body.error||'Perubahan belum tersimpan. Coba lagi.');
      if(action==='rename')library.selectedOptions[0].textContent=newName.value.trim();else{library.selectedOptions[0].remove();if(!library.options.length)library.add(new Option('Belum ada suara tersimpan',''));}
      renamePanel.hidden=true;
    }catch(e){libraryError.textContent=e instanceof TypeError||e instanceof SyntaxError?'Perubahan belum tersimpan. Coba lagi.':e.message;libraryError.hidden=false;}
    finally{saving=false;library.disabled=false;buttons.forEach(el=>el.disabled=false);updateLibrary();}
  }
  document.querySelector('#save-voice-name').addEventListener('click',()=>manage('rename'));
  document.querySelector('#delete-saved-voice').addEventListener('click',()=>manage('delete'));
  updateLibrary();
})();
