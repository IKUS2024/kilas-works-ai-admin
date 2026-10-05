(() => {
  const setup=document.querySelector('#personal-voice-setup');if(!setup)return;
  const panel=document.querySelector('#voice-recorder'),open=document.querySelector('#open-recorder');
  const start=document.querySelector('#record-start'),stop=document.querySelector('#record-stop'),again=document.querySelector('#record-again'),cancel=document.querySelector('#record-cancel');
  const playback=document.querySelector('#record-playback'),consent=document.querySelector('#voice-consent'),save=document.querySelector('#save-personal-voice');
  const state=document.querySelector('#record-state'),timer=document.querySelector('#record-timer'),error=document.querySelector('#record-error');
  const selected=document.querySelector('#selected-voice'),stock=document.querySelector('#kilas-voice-choice'),generate=document.querySelector('#voice-generate');
  let recorder=null,stream=null,tick=null,blob=null,objectUrl='',started=0,version=0,saving=false;
  function fail(text){error.textContent=text;error.hidden=false;}
  function tracksOff(){stream?.getTracks().forEach(t=>t.stop());stream=null;clearInterval(tick);tick=null;}
  function discard(){if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl='';blob=null;playback.pause();playback.removeAttribute('src');playback.hidden=true;consent.checked=false;save.disabled=true;}
  function choices(){const mine=document.querySelector('[name=voice_kind]:checked').value==='personal';setup.hidden=!mine;document.querySelector('#kilas-voice-options').hidden=mine;selected.value=mine?'personal':stock.value;generate.disabled=setup.dataset.translationReady==='false'||saving||!panel.hidden||generate.dataset.enabled!=='true'||(mine?setup.dataset.ready!=='true':!stock.value);}
  document.querySelectorAll('[name=voice_kind]').forEach(el=>el.addEventListener('change',()=>{if(!panel.hidden&&!saving){version++;if(recorder?.state==='recording')recorder.stop();tracksOff();discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;}choices();}));stock.addEventListener('change',choices);document.addEventListener('voice-translation-state',choices);choices();
  open.addEventListener('click',()=>{if(setup.dataset.ready==='true'&&!confirm('Rekaman baru akan mengganti Suara Saya. Suara saat ini tetap tersedia sampai penggantian berhasil.'))return;error.hidden=true;document.querySelector('#personal-ready').hidden=true;panel.hidden=false;state.textContent='Siap merekam';timer.textContent='0:00';start.hidden=false;stop.hidden=true;again.hidden=true;choices();start.focus({preventScroll:true});});
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
    if(saving||!blob?.size||!consent.checked)return;saving=true;setup.dataset.busy='true';error.hidden=true;choices();
    const controls=[...panel.querySelectorAll('button,input')];controls.forEach(el=>el.disabled=true);open.disabled=true;state.textContent='Sedang membuat Suara Saya…';
    const data=new FormData();data.append('csrf_token',document.querySelector('#audio-studio [name=csrf_token]').value);data.append('recording',blob,'recording');data.append('consent','yes');data.append('operation_key',setup.dataset.operationKey);if(setup.dataset.ready==='true')data.append('replace','yes');
    try{
      const response=await fetch('/kilas-translator/personal-voice',{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':document.querySelector('#audio-studio [name=csrf_token]').value}});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      const body=await response.json();if(!response.ok)throw Error(body.error||'Suara belum berhasil dibuat. Rekamanmu tetap aman untuk dicoba kembali.');
      setup.dataset.ready='true';setup.dataset.operationKey=crypto.randomUUID().replaceAll('-','');document.querySelector('#personal-voice-state').textContent='Siap digunakan';
      document.querySelector('#personal-ready h3')?.remove();document.querySelector('#personal-ready p')?.remove();
      if(!document.querySelector('#personal-ready strong')){const label=document.createElement('strong');label.textContent='Suara Saya · Siap digunakan';document.querySelector('#personal-ready').prepend(label);}
      document.querySelector('#voice-preview-missing').hidden=true;document.querySelector('#play-personal-preview').hidden=false;const sample=document.querySelector('#personal-preview');sample.src='/kilas-translator/personal-voice/preview?v='+setup.dataset.operationKey;sample.hidden=false;open.textContent='Rekam Ulang Suara';open.classList.add('secondary');discard();panel.hidden=true;document.querySelector('#personal-ready').hidden=false;
    }catch(e){fail(e instanceof SyntaxError||e instanceof TypeError?'Suara belum berhasil dibuat. Rekamanmu tetap aman untuk dicoba kembali.':e.message);state.textContent='Rekaman siap dicoba kembali';}
    finally{saving=false;setup.dataset.busy='false';controls.forEach(el=>el.disabled=false);open.disabled=false;save.disabled=!blob?.size||!consent.checked;choices();}
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
})();
