import {VoiceRecorder} from './kilas_transcription_recorder.mjs?v=lifecycle-20261012';

export function appendDictation(current, text, limit=4000) {
  if(typeof text!=='string'||!text.trim())throw Error('Tidak ada ucapan terbaca. Naskah tetap aman.');
  const result=current+(current&&!current.endsWith('\n')?'\n':'')+text.trim();
  if(result.length>limit)throw Error('Naskah dan dikte melebihi 4.000 karakter. Naskah tetap aman; rekam ucapan lebih pendek.');
  return result;
}

const root=globalThis.document?.querySelector('#voice-dictation');
if(root){
  const script=document.querySelector('#audio-script');
  const start=root.querySelector('#dictation-start'),stop=root.querySelector('#dictation-stop'),cancel=root.querySelector('#dictation-cancel'),undo=root.querySelector('#dictation-undo');
  const status=root.querySelector('#dictation-status'),error=root.querySelector('#dictation-error'),studio=document.querySelector('#audio-studio');
  const csrf=studio.querySelector('[name=csrf_token]').value;
  let version=0,key='',controller=null,busy=false,before='',after='';
  const fail=message=>{error.textContent=message;error.hidden=false;};
  const controls=()=>{start.disabled=busy||root.dataset.ready!=='true';stop.hidden=!busy||!!controller;cancel.hidden=!busy;studio.dataset.dictationBusy=String(busy);};
  const recorder=new VoiceRecorder({mediaDevices:navigator.mediaDevices,Recorder:window.MediaRecorder,onBlob:blob=>submit(blob),onState:state=>{
    if(state==='recording'){status.textContent='Mikrofon aktif · rekam maksimal 3 menit';controls();}
    if(state==='cancelled'){busy=false;status.textContent='Dikte dibatalkan. Naskah tetap aman.';controls();}
    if(state==='error'||state==='empty'){busy=false;status.textContent='';fail(state==='empty'?'Rekaman kosong. Naskah tetap aman; rekam kembali.':'Mikrofon belum tersedia. Periksa izin lalu coba lagi.');controls();}
  }});
  async function submit(blob){
    if(!busy)return;
    const ticket=version;controller=new AbortController();status.textContent='Menyiapkan naskah…';controls();
    const data=new FormData();data.append('recording',blob,'recording');data.append('operation_key',key);data.append('consent','yes');data.append('csrf_token',csrf);
    try{
      const response=await fetch('/kilas-translator/voice-script/dictate',{method:'POST',body:data,signal:controller.signal,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});
      if(response.redirected)throw Error('Sesi berakhir. Naskah tetap aman; masuk kembali.');
      const body=await response.json();if(!response.ok)throw Error(body.error||'Dikte belum berhasil.');
      if(ticket!==version)return;
      if(body.status!=='COMPLETED'||typeof body.text!=='string')throw Error('Hasil belum tersedia. Tidak ada pengulangan otomatis; naskah tetap aman.');
      before=script.value;after=appendDictation(before,body.text,script.maxLength);script.value=after;script.dispatchEvent(new Event('input',{bubbles:true}));undo.hidden=false;
      status.textContent='Dikte ditambahkan. Naskah dapat diedit.';
    }catch(e){if(ticket===version&&e.name!=='AbortError'){status.textContent='';fail(e instanceof SyntaxError||e instanceof TypeError?'Jaringan belum tersedia. Naskah tetap aman; rekam kembali bila ingin mencoba.':e.message);}}
    finally{if(ticket===version){busy=false;controller=null;key='';controls();}}
  }
  start.addEventListener('click',async()=>{
    if(busy||root.dataset.ready!=='true'||studio.querySelector('[aria-busy=true]')||studio.dataset.scriptEditing==='true'||document.querySelector('#voice-video-script')?.dataset.busy==='true')return;
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){fail('Browser ini belum mendukung mikrofon. Kamu tetap dapat mengetik.');return;}
    const ticket=++version;key='dictate-'+(crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join(''));busy=true;error.hidden=true;undo.hidden=true;status.textContent='Menunggu izin mikrofon…';controls();
    try{await recorder.start({userGesture:true,consent:true,enabled:true});}catch{if(ticket!==version)return;busy=false;controls();fail('Izin mikrofon belum tersedia. Periksa izin browser lalu coba lagi.');}
  });
  stop.addEventListener('click',()=>{stop.disabled=true;recorder.stop();stop.disabled=false;});
  function end(){
    const oldKey=key;version++;recorder.cancel();controller?.abort();controller=null;busy=false;status.textContent='Dikte dibatalkan. Naskah tetap aman.';controls();
    if(oldKey){const data=new FormData();data.append('operation_key',oldKey);data.append('action','cancel');data.append('csrf_token',csrf);fetch('/kilas-translator/voice-script/dictate',{method:'POST',body:data,credentials:'same-origin',keepalive:true}).catch(()=>{});key='';}
  }
  cancel.addEventListener('click',end);window.addEventListener('pagehide',()=>{if(busy)end();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&busy)end();});
  undo.addEventListener('click',()=>{if(script.value!==after){fail('Naskah sudah diedit. Urungkan secara manual agar perubahanmu tetap aman.');return;}script.value=before;script.dispatchEvent(new Event('input',{bubbles:true}));undo.hidden=true;});
  controls();
}
