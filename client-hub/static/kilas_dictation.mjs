import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {VoiceRecorder} from './kilas_transcription_recorder.mjs?v=app-language-20261015';

export function appendDictation(current, text, limit=4000) {
  if(typeof text!=='string'||!text.trim())throw Error(t('Tidak ada ucapan terbaca. Naskah tetap aman.'));
  const result=current+(current&&!current.endsWith('\n')?'\n':'')+text.trim();
  if(result.length>limit)throw Error(t('Naskah dan dikte melebihi 4.000 karakter. Naskah tetap aman; rekam ucapan lebih pendek.'));
  return result;
}

// Recognition events contain the full result list, including earlier final
// results. Read that list once rather than appending repeated event payloads.
export function finalDictation(results) {
  return Array.from(results).filter(result=>result.isFinal).map(result=>result[0]?.transcript||'').join(' ').trim();
}

const root=globalThis.document?.querySelector('#voice-dictation');
if(root){
  const script=document.querySelector('#audio-script');
  const start=root.querySelector('#dictation-start'),stop=root.querySelector('#dictation-stop'),cancel=root.querySelector('#dictation-cancel'),undo=root.querySelector('#dictation-undo');
  const status=root.querySelector('#dictation-status'),error=root.querySelector('#dictation-error'),studio=document.querySelector('#audio-studio');
  const csrf=studio.querySelector('[name=csrf_token]').value;
  const serverReady=root.dataset.ready==='true';
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const browserMode=!serverReady&&typeof Recognition==='function';
  const supported=serverReady||browserMode;
  let version=0,key='',controller=null,busy=false,before='',after='',recognition=null,browserTimer=null,stopTimer=null,stopping=false;
  const fail=message=>{error.textContent=message;error.hidden=false;};
  const controls=()=>{start.disabled=busy||!supported;stop.hidden=!busy||!!controller;stop.disabled=stopping;cancel.hidden=!busy;studio.dataset.dictationBusy=String(busy);};
  const applyText=text=>{
    const current=script.value,next=appendDictation(current,text,script.maxLength);
    before=current;after=next;script.value=next;script.dispatchEvent(new Event('input',{bubbles:true}));undo.hidden=false;
    status.textContent=t('Dikte ditambahkan. Naskah dapat diedit.');
  };
  const clearBrowserTimers=()=>{clearTimeout(browserTimer);clearTimeout(stopTimer);browserTimer=null;stopTimer=null;};
  const recorder=new VoiceRecorder({mediaDevices:navigator.mediaDevices,Recorder:window.MediaRecorder,onBlob:blob=>submit(blob),onState:state=>{
    if(state==='recording'){status.textContent=t('Mikrofon aktif · rekam maksimal 3 menit');controls();}
    if(state==='cancelled'){busy=false;status.textContent=t('Dikte dibatalkan. Naskah tetap aman.');controls();}
    if(state==='error'||state==='empty'){busy=false;status.textContent='';fail(state==='empty'?t('Rekaman kosong. Naskah tetap aman; rekam kembali.'):t('Mikrofon belum tersedia. Periksa izin lalu coba lagi.'));controls();}
  }});
  async function submit(blob){
    if(!busy)return;
    const ticket=version;controller=new AbortController();status.textContent=t('Menyiapkan naskah…');controls();
    const data=new FormData();data.append('recording',blob,'recording');data.append('operation_key',key);data.append('consent','yes');data.append('csrf_token',csrf);
    try{
      const response=await fetch('/kilas-translator/voice-script/dictate',{method:'POST',body:data,signal:controller.signal,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});
      if(response.redirected)throw Error(t('Sesi berakhir. Naskah tetap aman; masuk kembali.'));
      const body=await response.json();if(!response.ok)throw Error(body.error||t('Dikte belum berhasil.'));
      if(ticket!==version)return;
      if(body.status!=='COMPLETED'||typeof body.text!=='string')throw Error(t('Hasil belum tersedia. Tidak ada pengulangan otomatis; naskah tetap aman.'));
      applyText(body.text);
    }catch(e){if(ticket===version&&e.name!=='AbortError'){status.textContent='';fail(e instanceof SyntaxError||e instanceof TypeError?t('Jaringan belum tersedia. Naskah tetap aman; rekam kembali bila ingin mencoba.'):e.message);}}
    finally{if(ticket===version){busy=false;controller=null;key='';controls();}}
  }
  function browserStart(ticket){
    let text='';
    let own;
    try{own=new Recognition();}catch{busy=false;controls();status.textContent='';fail(t('Pengenalan suara browser belum tersedia. Coba Chrome atau Safari terbaru, atau ketik naskah.'));return;}
    recognition=own;
    own.lang=({id:'id-ID',en:'en-US',es:'es-ES',zh:'zh-CN'})[document.documentElement.lang]||document.documentElement.lang||navigator.language||'id-ID';
    own.continuous=true;own.interimResults=true;own.maxAlternatives=1;
    const current=()=>ticket===version&&recognition===own;
    const release=()=>{recognition=null;clearBrowserTimers();busy=false;stopping=false;controls();};
    const finish=()=>{
      if(!current())return;
      release();
      try{applyText(text);}catch(e){status.textContent='';fail(e.message);}
    };
    own.onstart=()=>{if(!current())return;status.textContent=t('Mikrofon aktif · rekam maksimal 3 menit');};
    own.onresult=event=>{if(current())text=finalDictation(event.results);};
    own.onerror=event=>{
      if(!current())return;
      release();try{own.abort();}catch{}
      status.textContent='';
      fail(t(event.error==='not-allowed'||event.error==='service-not-allowed'?'Izin mikrofon belum tersedia. Periksa izin browser lalu coba lagi.':event.error==='no-speech'?'Tidak ada ucapan terbaca. Naskah tetap aman.':event.error==='network'?'Pengenalan suara browser tidak terhubung. Periksa internet lalu coba lagi; naskah tetap aman.':'Pengenalan suara browser belum tersedia. Coba Chrome atau Safari terbaru, atau ketik naskah.'));
    };
    own.onend=finish;
    try{own.start();if(current())browserTimer=setTimeout(()=>browserStop(),179000);}catch{
      if(!current())return;release();try{own.abort();}catch{}
      status.textContent='';fail(t('Pengenalan suara browser belum tersedia. Coba Chrome atau Safari terbaru, atau ketik naskah.'));
    }
    function browserStop(){
      if(!current()||stopping)return;
      stopping=true;status.textContent=t('Menyiapkan naskah…');controls();
      try{own.stop();}catch{finish();try{own.abort();}catch{}return;}
      if(current())stopTimer=setTimeout(()=>{if(!current())return;finish();try{own.abort();}catch{}},8000);
    }
    // Use the same stop path for the explicit button and the recording limit.
    own.finishRecording=browserStop;
  }
  start.addEventListener('click',async()=>{
    if(busy||!supported||studio.querySelector('[aria-busy=true]')||studio.dataset.scriptEditing==='true'||document.querySelector('#voice-video-script')?.dataset.busy==='true'||document.querySelector('#personal-voice-setup')?.dataset.recorderOpen==='true')return;
    if(browserMode){
      if(!window.confirm(t('Rekam Naskah akan memakai pengenalan suara browser. Suara dapat dikirim ke layanan browser untuk diubah menjadi teks, bukan ke ElevenLabs. Lanjutkan?')))return;
      const ticket=++version;busy=true;stopping=false;error.hidden=true;undo.hidden=true;status.textContent=t('Menunggu izin mikrofon…');controls();browserStart(ticket);return;
    }
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){fail(t('Browser ini belum mendukung mikrofon. Kamu tetap dapat mengetik.'));return;}
    const ticket=++version;key='dictate-'+(crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join(''));busy=true;error.hidden=true;undo.hidden=true;status.textContent=t('Menunggu izin mikrofon…');controls();
    try{await recorder.start({userGesture:true,consent:true,enabled:true});}catch{if(ticket!==version)return;busy=false;controls();fail(t('Izin mikrofon belum tersedia. Periksa izin browser lalu coba lagi.'));}
  });
  stop.addEventListener('click',()=>{if(browserMode){recognition?.finishRecording();return;}stop.disabled=true;recorder.stop();stop.disabled=false;});
  function end(){
    const oldKey=key;version++;const oldRecognition=recognition;recognition=null;clearBrowserTimers();try{oldRecognition?.abort();}catch{}recorder.cancel();controller?.abort();controller=null;busy=false;stopping=false;status.textContent=t('Dikte dibatalkan. Naskah tetap aman.');controls();
    if(oldKey){const data=new FormData();data.append('operation_key',oldKey);data.append('action','cancel');data.append('csrf_token',csrf);fetch('/kilas-translator/voice-script/dictate',{method:'POST',body:data,credentials:'same-origin',keepalive:true}).catch(()=>{});key='';}
  }
  cancel.addEventListener('click',end);window.addEventListener('pagehide',()=>{if(busy)end();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&busy)end();});
  undo.addEventListener('click',()=>{if(script.value!==after){fail(t('Naskah sudah diedit. Urungkan secara manual agar perubahanmu tetap aman.'));return;}script.value=before;script.dispatchEvent(new Event('input',{bubbles:true}));undo.hidden=true;});
  root.dataset.engine=serverReady?'server':browserMode?'browser':'unavailable';
  if(browserMode){start.title=t('Record Script');status.textContent=t('Dikte memakai pengenalan suara browser. Izin diminta saat mulai.');}
  if(!supported){status.textContent=t('Rekam Naskah belum didukung browser ini. Coba Chrome atau Safari terbaru, atau ketik naskah.');}
  controls();
}
