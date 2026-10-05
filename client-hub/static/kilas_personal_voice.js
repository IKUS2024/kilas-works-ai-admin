(() => {
  const setup=document.querySelector('#personal-voice-setup');if(!setup||setup.dataset.initialized)return;setup.dataset.initialized='true';
  const panel=document.querySelector('#voice-recorder'),open=document.querySelector('#open-recorder');
  const start=document.querySelector('#record-start'),stop=document.querySelector('#record-stop'),again=document.querySelector('#record-again'),cancel=document.querySelector('#record-cancel');
  const playback=document.querySelector('#record-playback'),consent=document.querySelector('#voice-consent'),save=document.querySelector('#save-personal-voice');
  const state=document.querySelector('#record-state'),timer=document.querySelector('#record-timer'),error=document.querySelector('#record-error');
  const selected=document.querySelector('#selected-voice'),stock=document.querySelector('#kilas-voice-choice'),generate=document.querySelector('#voice-generate');
  const library=document.querySelector('#saved-voice-choice'),nameInput=document.querySelector('#record-voice-name');
  let replacing='';
  let recorder=null,stream=null,tick=null,blob=null,objectUrl='',started=0,version=0,saving=false;
  function fail(text){error.textContent=text;error.hidden=false;}
  function tracksOff(){stream?.getTracks().forEach(t=>t.stop());stream=null;clearInterval(tick);tick=null;}
  function discard(){if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl='';blob=null;playback.pause();playback.removeAttribute('src');playback.hidden=true;consent.checked=false;save.disabled=true;}
  function choices(){const mine=document.querySelector('[name=voice_kind]:checked').value==='personal';setup.hidden=!mine;document.querySelector('#kilas-voice-options').hidden=mine;selected.value=mine?(library.value?'personal:'+library.value:''):stock.value;generate.disabled=setup.dataset.translationReady==='false'||saving||!panel.hidden||generate.dataset.enabled!=='true'||(mine?!library.value:!stock.value);}
  document.querySelectorAll('[name=voice_kind]').forEach(el=>el.addEventListener('change',()=>{if(!panel.hidden&&!saving){version++;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;}choices();}));stock.addEventListener('change',choices);document.addEventListener('voice-translation-state',choices);choices();
  function openRecorder(replace){if(saving||generate.dataset.enabled!=='true')return;if(replace&&(!library.value||!confirm('Rekam ulang suara ini? Suara saat ini tetap tersedia sampai penggantian berhasil.')))return;replacing=replace?library.value:'';nameInput.value=replace?library.selectedOptions[0].textContent:'Suara Saya';error.hidden=true;document.querySelector('#personal-ready').hidden=true;panel.hidden=false;state.textContent='Siap merekam';timer.textContent='0:00';start.hidden=false;stop.hidden=true;again.hidden=true;choices();nameInput.focus({preventScroll:true});}
  open.addEventListener('click',()=>openRecorder(true));document.querySelector('#add-saved-voice').addEventListener('click',()=>openRecorder(false));
  async function record(){
    if(saving)return;
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){fail('Mikrofon belum dapat digunakan. Periksa izin mikrofon lalu coba lagi.');return;}
    const current=++version;discard();error.hidden=true;start.disabled=true;state.textContent='Menunggu izin mikrofon…';
    try{
      const incoming=await navigator.mediaDevices.getUserMedia({audio:true});if(current!==version){incoming.getTracks().forEach(t=>t.stop());return;}stream=incoming;
      const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
      recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);const chunks=[];
      recorder.addEventListener('dataavailable',e=>{if(e.data.size)chunks.push(e.data);});
      recorder.addEventListener('stop',()=>{tracksOff();if(current!==version)return;blob=new Blob(chunks,{type:recorder.mimeType||mime||'audio/webm'});objectUrl=URL.createObjectURL(blob);playback.src=objectUrl;playback.hidden=false;start.hidden=true;stop.hidden=true;again.hidden=false;state.textContent=Date.now()-started<60000?'Rekaman singkat. Disarankan 60-120 detik untuk kemiripan lebih baik.':'Rekaman siap didengarkan';save.disabled=!consent.checked||!blob.size;start.disabled=false;});
      recorder.addEventListener('error',()=>{version++;tracksOff();discard();stop.hidden=true;start.hidden=false;start.disabled=false;state.textContent='Rekaman belum berhasil';fail('Mikrofon belum dapat digunakan. Periksa izin mikrofon lalu coba lagi.');});
      recorder.start();started=Date.now();start.hidden=true;stop.hidden=false;again.hidden=true;state.textContent='Mikrofon aktif · sedang merekam';
      tick=setInterval(()=>{const seconds=Math.floor((Date.now()-started)/1000);timer.textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;if(seconds>=179&&recorder.state==='recording')recorder.stop();},250);
    }catch{tracksOff();start.disabled=false;state.textContent='Mikrofon belum tersedia';fail('Mikrofon belum dapat digunakan. Periksa izin mikrofon lalu coba lagi.');}
  }
  start.addEventListener('click',record);again.addEventListener('click',record);stop.addEventListener('click',()=>{if(recorder?.state==='recording'){stop.disabled=true;recorder.stop();stop.disabled=false;}});
  cancel.addEventListener('click',()=>{if(saving)return;version++;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;start.disabled=false;choices();open.focus({preventScroll:true});});
  consent.addEventListener('change',()=>{save.disabled=saving||!blob?.size||!consent.checked;});
  save.addEventListener('click',async()=>{
    if(saving||!blob?.size||!consent.checked)return;if(!nameInput.value.trim()){fail('Beri nama suara sebelum menyimpan.');nameInput.focus();return;}saving=true;setup.dataset.busy='true';error.hidden=true;choices();
    const controls=[...panel.querySelectorAll('button,input')];controls.forEach(el=>el.disabled=true);open.disabled=true;state.textContent='Sedang membuat Suara Saya…';
    const data=new FormData();data.append('csrf_token',document.querySelector('#audio-studio [name=csrf_token]').value);data.append('recording',blob,'recording');data.append('consent','yes');data.append('operation_key',setup.dataset.operationKey);data.append('name',nameInput.value.trim());if(replacing)data.append('saved_voice_id',replacing);
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
    document.querySelector('#saved-voice-notice').textContent=ready?'Suara ini digunakan untuk Voice Over berikutnya.':'Tambahkan rekaman suara untuk menyimpannya di akun kamu.';
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
