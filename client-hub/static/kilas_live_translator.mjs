import {VoiceRecorder} from './kilas_transcription_recorder.mjs';
import {TranslatorSession} from './kilas_live_translator_engine.mjs';
const root=document.querySelector('.kilas-live-translator');
if(root){
 const form=document.querySelector('#live-setup-form'),setup=document.querySelector('#live-setup'),active=document.querySelector('#live-active'),orb=active.querySelector('.kilas-live-orb'),error=document.querySelector('#live-error');
 const csrf=form.querySelector('[name=csrf_token]').value,start=form.querySelector('button');let context=null,source=null,analyser=null,interval=null,recorder=null,output=null,playReject=null;
 const showError=text=>{error.textContent=text;error.hidden=false;};
 function monitorStop(){if(interval!==null)clearInterval(interval);interval=null;source?.disconnect();source=null;analyser?.disconnect();analyser=null;}
 const capture={
  async start({level,blob,error:onError}){
   if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder||!context)throw Error('Browser ini belum mendukung mikrofon.');
   recorder=new VoiceRecorder({mediaDevices:navigator.mediaDevices,Recorder:window.MediaRecorder,onBlob:raw=>{monitorStop();blob(raw);},onState:state=>{if(state==='error')onError(Error('Mikrofon terputus. Periksa izin browser lalu mulai kembali.'));}});
   const own=recorder;await own.start({userGesture:true,consent:true,enabled:true});
   if(own!==recorder||!own.stream)return;
   source=context.createMediaStreamSource(own.stream);analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
   const samples=new Float32Array(analyser.fftSize);let began=performance.now(),heard=false;
   interval=setInterval(()=>{if(!analyser)return;analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);if(rms>=.015)heard=true;level(rms);
    // Silence never dispatches STT. A continuous/idle recording has a bounded lifetime.
    if(performance.now()-began>=60000)onError(Error(heard?'Ucapan terlalu panjang. Akhiri kalimat dengan jeda lalu mulai kembali.':'Tidak ada ucapan terbaca. Mulai kembali saat siap.'));
   },50);
  },
  finalize(){monitorStop();recorder?.stop();},
  cancel(){monitorStop();recorder?.cancel();recorder=null;},
 };
 const playback={
  async play(url,signal,isCurrent){
   if(!url.startsWith('/kilas-translator/live/sessions/'))throw Error('Hasil audio tidak tersedia.');
   const response=await fetch(url,{credentials:'same-origin',signal,cache:'no-store'});if(!response.ok||response.redirected)throw Error('Audio belum dapat diputar. Mulai kembali.');
   const raw=await response.arrayBuffer();if(raw.byteLength>20*1024*1024)throw Error('Audio melebihi batas.');
   const buffer=await context.decodeAudioData(raw);if(signal.aborted||!isCurrent())return;
   await new Promise((resolve,reject)=>{playReject=reject;output=context.createBufferSource();output.buffer=buffer;output.connect(context.destination);output.onended=()=>{output?.disconnect();output=null;playReject=null;resolve();};output.start();});
  },
  stop(){const reject=playReject;playReject=null;if(output){output.onended=null;try{output.stop();}catch{}output.disconnect();output=null;}reject?.(new DOMException('Ended','AbortError'));if(context){context.close().catch(()=>{});context=null;}},
 };
 async function json(url,options={}){
  const response=await fetch(url,{...options,credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':csrf}});
  if(response.redirected)throw Error('Sesi akun berakhir. Masuk kembali.');
  let body;try{body=await response.json();}catch{throw Error('Layanan belum tersedia. Mulai kembali bila jaringan siap.');}
  if(!response.ok)throw Error(body.error||'Layanan belum tersedia.');return body;
 }
 const pause=signal=>new Promise((resolve,reject)=>{const cancel=()=>{clearTimeout(timer);reject(new DOMException('Ended','AbortError'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},500);signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();});
 const api={
  start:(data,signal)=>json('/kilas-translator/live/sessions',{method:'POST',body:data,signal}),
  async turn(id,key,blob,signal){
   const url='/kilas-translator/live/sessions/'+id+'/turns/'+key,data=new FormData();data.append('recording',blob,'recording');data.append('csrf_token',csrf);
   await json(url,{method:'POST',body:data,signal});const deadline=performance.now()+180000;
   while(!signal.aborted){const result=await json(url,{signal});if(result.status==='COMPLETED')return result;if(result.status==='FAILED'){const e=Error(result.error);if(result.recoverable)e.code='no_speech';throw e;}if(result.status==='CANCELLED')throw Error('Sesi sudah berakhir.');if(performance.now()>deadline)throw Error('Pemrosesan belum selesai. Sesi dihentikan; tidak diulang otomatis.');await pause(signal);}
   throw new DOMException('Ended','AbortError');
  },
  end(id){const data=new FormData();data.append('csrf_token',csrf);return json('/kilas-translator/live/sessions/'+id+'/end',{method:'POST',body:data,keepalive:true});},
 };
 const session=new TranslatorSession({api,capture,playback,key:()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join(''),onError:showError,onState:state=>{
  start.disabled=state!=='ended'||root.dataset.ready!=='true';setup.hidden=!['starting','ended'].includes(state);active.hidden=['starting','ended'].includes(state);orb.dataset.state=state;orb.setAttribute('aria-label',state==='playing'?'Memutar terjemahan':state==='listening'?'Mendengarkan':'Memproses');
 }});
 form.addEventListener('submit',event=>{event.preventDefault();if(root.dataset.ready!=='true'||session.state!=='ended')return;if(!form.reportValidity())return;
  if(form.elements.language_a.value===form.elements.language_b.value){showError('Pilih dua bahasa yang berbeda.');return;}
  error.hidden=true;const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext){showError('Browser ini belum mendukung audio sesi.');return;}
  context=new AudioContext();context.resume().catch(()=>{});session.start(new FormData(form));
 });
 document.querySelector('#live-end').addEventListener('click',()=>session.end());window.addEventListener('pagehide',()=>session.end());
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&session.state!=='ended'){showError('Sesi berakhir saat halaman ditinggalkan.');session.end();}});
}
