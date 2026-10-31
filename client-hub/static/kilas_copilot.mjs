import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
import {CopilotCapture,PcmBuffer} from './kilas_copilot_capture.mjs';

export function wav(chunks) {
  const size=chunks.reduce((n,b)=>n+b.byteLength,0), out=new ArrayBuffer(44+size), v=new DataView(out);
  const text=(at,s)=>[...s].forEach((c,i)=>v.setUint8(at+i,c.charCodeAt(0)));
  text(0,'RIFF');v.setUint32(4,36+size,true);text(8,'WAVE');text(12,'fmt ');
  v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);
  v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);text(36,'data');v.setUint32(40,size,true);
  let at=44;for(const b of chunks){new Uint8Array(out,at,b.byteLength).set(new Uint8Array(b));at+=b.byteLength;}
  return new Blob([out],{type:'audio/wav'});
}

export async function readEvents(response, receive) {
  if(!response.ok || !response.body)throw Error('network');
  const reader=response.body.getReader(), decoder=new TextDecoder();let pending='',complete=false;
  try {
    while(true){
      const {value,done}=await reader.read();pending+=decoder.decode(value||new Uint8Array(),{stream:!done});
      if(pending.length>100000)throw Error('network');
      let separator;while((separator=/\r?\n\r?\n/.exec(pending))){
        const frame=pending.slice(0,separator.index);pending=pending.slice(separator.index+separator[0].length);
        const data=frame.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).replace(/^ /,'')).join('\n');
        if(data){
          const event=JSON.parse(data);receive(event);
          if(event.type==='complete'){complete=true;return;}
          if(event.type==='error')throw Error(event.code);
        }
      }
      if(done)break;
    }
    if(!complete)throw Error('incomplete_stream');
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
}

export async function pollOperation(url, receive, signal) {
  let version;
  while(!signal?.aborted){
    const response=await fetch(url,{signal,cache:'no-store'});
    if(!response.ok)throw Error('network');
    const view=await response.json().catch(()=>{throw Error('network');});
    if(!['processing','complete','failed'].includes(view.state))throw Error('network');
    if(view.version===undefined||view.version!==version){receive(view);version=view.version;}
    if(view.state==='complete')return;
    if(view.state==='failed')throw Error(view.code||'provider_failed');
    await new Promise((resolve,reject)=>{
      const done=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);resolve();};
      const abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);reject(Error('cancelled'));};
      const timer=setTimeout(done,view.text?200:400);signal?.addEventListener('abort',abort,{once:true});
      if(signal?.aborted)abort();
    });
  }
  throw Error('cancelled');
}

const root=globalThis.document?.querySelector('#copilot');
if(root){
  const $=id=>document.getElementById('copilot-'+id), mic=$('mic'),trigger=$('trigger'),state=$('state'),action=$('action'),error=$('error');
  const translate=$('translate'),target=$('target'),style=$('style'),cancel=$('cancel');
  const csrf=$('csrf').value, turns=JSON.parse($('initial').textContent);
  const resultTools=root.querySelector('.copilot-result-tools');
  const styleButtons=[...root.querySelectorAll('[data-copilot-style]')];let textSize=22;
  let phase='idle',epoch=0,capture=null,chunks=[],sessionId=root.dataset.sessionId,operation=null,controller=null,timer=null,partial=null;
  const messages={
    clipped_audio:t('Rekaman terlalu terdistorsi. Kurangi volume speaker lalu rekam lagi.'),
    processing_timeout:t('Batas waktu proses tercapai. Periksa riwayat sebelum merekam lagi.'),
    interrupted_operation:t('Proses terhenti. Buka ulang sesi untuk memeriksa jawaban yang tersimpan.'),
    silence:t('Tidak terdengar ucapan. Dekatkan mikrofon ke speaker, lalu rekam lagi.'),
    unclear_audio:t('Ucapan belum jelas. Rekam ulang bagian yang ingin dijawab.'),
    permission:t('Izin mikrofon ditolak. Izinkan mikrofon melalui pengaturan browser, lalu tekan lagi.'),
    microphone:t('Mikrofon tidak tersedia. Periksa perangkat dan izin browser, lalu coba lagi.'),
    provider_unavailable:t('Copilot belum tersedia. Minta pengelola memeriksa konfigurasi OpenAI.'),
    capacity_unavailable:t('Kapasitas akun belum tersedia atau masih ada proses aktif. Periksa Credits & Usage, lalu coba lagi.'),
    cancelled:t('Proses dibatalkan. Tekan mikrofon untuk memulai rekaman baru.'),
    incomplete_stream:t('Jawaban terputus dan belum disimpan. Tekan mikrofon untuk mencoba rekaman baru.'),
    incomplete_translation:t('Terjemahan terputus. Hasil belum disimpan; mulai rekaman baru untuk mencoba lagi.'),
    operation_already_submitted:t('Rekaman ini sudah dikirim. Buka ulang sesi untuk memeriksa hasilnya; tidak dikirim ulang otomatis.'),
    operation_busy:t('Masih ada proses aktif di sesi ini. Tunggu atau batalkan proses sebelumnya.'),
    network:t('Koneksi terputus. Hasil belum terkonfirmasi; buka ulang sesi sebelum mencoba rekaman baru.'),
    server_busy:t('Server masih memproses permintaan lain. Tunggu sebentar, lalu mulai rekaman baru.'),
  };
  function notice(code){error.textContent=messages[code]||t('Pemrosesan gagal. Periksa koneksi lalu mulai rekaman baru.');error.hidden=false;}
  function setPhase(next){
    phase=next;root.dataset.state=next;
    root.dataset.view=['stopping','processing','streaming'].includes(next)||(next==='idle'&&turns.length)?'results':'capture';
    const busy=['requesting','stopping','processing','streaming'].includes(next);
    const label=next==='requesting'?t('Menghubungkan mikrofon'):busy?t('Memproses rekaman'):next==='listening'?t('Berhenti dan proses jawaban'):next==='captured'?t('Proses rekaman'):t('Mulai mendengarkan');
    for(const button of [mic,trigger]){button.disabled=busy;button.setAttribute('aria-pressed',String(next==='listening'));button.setAttribute('aria-label',label);}
    state.textContent=({idle:t('Mikrofon mati'),requesting:t('Menghubungkan mikrofon…'),listening:t('Mendengarkan…'),stopping:t('Menyiapkan rekaman…'),captured:t('Rekaman selesai · mikrofon mati'),processing:t('Memproses…'),streaming:t('Menyiapkan saran jawaban…')})[next];
    action.textContent=next==='listening'?t('Ketuk untuk proses'):next==='captured'?t('Proses rekaman'):busy?t('Mohon tunggu…'):turns.length?t('Dengarkan lagi'):t('Dengarkan');
    trigger.textContent=next==='listening'?t('Berhenti & proses'):next==='captured'?t('Proses rekaman'):busy?t('Mohon tunggu…'):turns.length?t('Dengarkan lagi'):t('Dengarkan');
    cancel.hidden=next==='idle';
    for(const el of [translate,target,style])el.disabled=next!=='idle';
    styleButtons.forEach(button=>button.disabled=next!=='idle');$('wave').hidden=next!=='listening';
  }
  function paragraph(parent,className,label,text){
    const h=document.createElement('h3');h.textContent=label;
    const p=document.createElement('p');p.className=className;p.dir='auto';p.textContent=text;parent.append(h,p);return p;
  }
  function draw(){
    const container=$('turns');container.replaceChildren();
    let previous=null;
    [...turns].reverse().forEach((turn,index)=>{
      const article=document.createElement('article');article.className='copilot-turn';
      if(translate.checked){
        const source=document.createElement('section');source.className='copilot-source-card';
        paragraph(source,'copilot-source',t('Ucapan yang didengar'),turn.source);
        paragraph(source,'copilot-source-translation',t('Terjemahan ucapan'),turn.source_translation||t('Terjemahan belum dibuat untuk rekaman ini.'));article.append(source);
      }
      const answer=document.createElement('section');answer.className='copilot-answer-card';
      paragraph(answer,'copilot-reply',t('Saran jawaban AI'),turn.reply);
      if(translate.checked){
        paragraph(answer,'copilot-reply-translation',t('Terjemahan · {language}',{language:([...target.options].find(option=>option.value===turn.target)?.textContent||'')}),turn.reply_translation||t(turn.translation_status==='pending'?'Menerjemahkan…':turn.translation_error?'Terjemahan gagal. Jawaban tersimpan.':'Terjemahan belum dibuat untuk rekaman ini.'));
        if(turn.translation_error&&turn.operation_key){
          const retry=document.createElement('button');retry.type='button';retry.className='copilot-translation-retry';retry.textContent=t('Coba terjemahan lagi');retry.disabled=phase!=='idle';retry.addEventListener('click',()=>retryTranslation(turn));answer.append(retry);
        }
      }
      const copy=document.createElement('button');copy.type='button';copy.className='copilot-copy';copy.textContent=t('Salin jawaban');
      copy.addEventListener('click',async()=>{
        try{await navigator.clipboard.writeText(turn.reply);copy.textContent=t('Tersalin');setTimeout(()=>copy.textContent=t('Salin jawaban'),1500);}
        catch{notice('copy_failed');error.textContent=t('Belum dapat menyalin. Pilih teks jawaban lalu salin secara manual.');}
      });answer.append(copy);if(!index)answer.append(resultTools);article.append(answer);
      if(!index)container.append(article);
      else{
        if(!previous){previous=document.createElement('details');previous.className='copilot-previous';const summary=document.createElement('summary');summary.textContent=t('Jawaban sebelumnya ({count})',{count:turns.length-1});previous.append(summary);container.append(previous);}
        previous.append(article);
      }
    });
    resultTools.hidden=!turns.length;$('disclosure').hidden=!turns.length;
  }
  let preferenceQueue=Promise.resolve();
  function savePreferences(){
    if(!sessionId)return;
    const body=new FormData();body.set('csrf_token',csrf);body.set('style',style.value);body.set('target',target.value);body.set('translate',translate.checked?'yes':'no');
    const url=`/kilas-ai/copilot/sessions/${sessionId}/preferences`;
    preferenceQueue=preferenceQueue.catch(()=>{}).then(()=>fetch(url,{method:'POST',body,keepalive:true})).then(response=>{if(!response.ok)throw Error('network');}).catch(()=>notice('network'));
  }
  translate.addEventListener('change',()=>{$('target-wrap').hidden=!translate.checked;draw();savePreferences();});
  target.addEventListener('change',savePreferences);
  styleButtons.forEach(button=>button.addEventListener('click',()=>{style.value=button.dataset.copilotStyle;styleButtons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));savePreferences();}));
  function size(delta){textSize=Math.max(18,Math.min(30,textSize+delta));root.style.setProperty('--copilot-text-size',textSize+'px');$('smaller').disabled=textSize===18;$('larger').disabled=textSize===30;}
  $('smaller').addEventListener('click',()=>size(-2));$('larger').addEventListener('click',()=>size(2));
  function waveform(samples){
    const canvas=$('wave'),context=canvas.getContext('2d');if(!context)return;
    context.clearRect(0,0,320,48);context.fillStyle='#ed651b';
    for(let bar=0;bar<40;bar++){
      const from=Math.floor(bar*samples.length/40),to=Math.floor((bar+1)*samples.length/40);let sum=0;
      for(let at=from;at<to;at++)sum+=samples[at]**2;
      const height=Math.min(46,Math.sqrt(sum/Math.max(1,to-from))*160);
      if(height>0.2)context.fillRect(bar*8+2,(48-height)/2,4,height);
    }
  }
  function release(){
    clearTimeout(timer);timer=null;
    if(!capture)return;
    const old=capture;capture=null;
    if(old.close)old.close();else old.stream?.getTracks().forEach(t=>t.stop());
  }
  function cancelRequest(beacon=false){
    if(!sessionId||!operation)return;
    const form=new FormData();form.set('csrf_token',csrf);
    const url=`/kilas-ai/copilot/sessions/${sessionId}/${operation}/cancel`;
    if(beacon)navigator.sendBeacon?.(url,form);
    else{
      const mine=epoch;
      fetch(url,{method:'POST',headers:{'X-CSRF-Token':csrf},body:form,keepalive:true}).then(response=>response.ok?response.json():{}).then(result=>{if(mine===epoch&&phase==='idle'&&root.isConnected&&result.turn){mergeTurn(result.turn);draw();}}).catch(()=>{});
    }
  }
  function reset(code,beacon=false){
    ++epoch;cancelRequest(beacon);operation=null;controller?.abort();controller=null;
    release();chunks=[];partial?.remove();partial=null;draw();setPhase('idle');if(code)notice(code);
  }
  async function begin(){
    error.hidden=true;
    if(root.dataset.ready!=='true'){notice('provider_unavailable');return;}
    if(!navigator.mediaDevices?.getUserMedia){notice('microphone');return;}
    const mine=++epoch;setPhase('requesting');chunks=[];
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:false,noiseSuppression:true},video:false});
      if(mine!==epoch){stream.getTracks().forEach(t=>t.stop());return;}
      capture={stream};
      const Context=window.AudioContext||window.webkitAudioContext;
      const context=new Context(), buffer=new PcmBuffer();chunks=buffer.chunks;
      const recorder=new CopilotCapture(stream,context,frame=>{
        if(mine!==epoch)return;buffer.append(frame.bytes);
        const values=new Float32Array(40).fill(frame.rms);waveform(values);
      });capture=recorder;
      recorder.failed=()=>{if(mine===epoch)reset('microphone');};
      await recorder.start();
      if(mine!==epoch){recorder.close();return;}
      stream.getAudioTracks().forEach(track=>track.addEventListener('ended',()=>{if(mine===epoch&&phase==='listening')reset('microphone');}));
      if(mine!==epoch)return;
      setPhase('listening');
      timer=setTimeout(async()=>{
        if(phase!=='listening')return;setPhase('stopping');
        try{await capture.finish();if(mine!==epoch)return;release();setPhase('captured');
          notice('limit');error.textContent=t('Batas 60 detik tercapai. Tekan mikrofon untuk memproses atau Batalkan untuk merekam ulang.');
        }catch{if(mine===epoch)reset('microphone');}
      },60000);
    }catch(e){
      if(mine!==epoch)return;
      release();setPhase('idle');notice(e.name==='NotAllowedError'?'permission':e.message==='network'?'network':'microphone');
    }
  }
  async function process(){
    const mine=epoch;setPhase('stopping');error.hidden=true;
    $('turns').replaceChildren();resultTools.hidden=true;$('disclosure').hidden=true;
    clearTimeout(timer);
    try{if(capture)await capture.finish();}catch{if(mine===epoch)reset('microphone');return;}
    if(mine!==epoch)return;release();
    const blob=wav(chunks);chunks=[];
    if(blob.size<3244){draw();setPhase('idle');notice('unclear_audio');return;}
    controller=new AbortController();
    // The deliberate stop/process action submits only this stopped recording.
    // Keep the server's explicit consent and CSRF contract; no checkbox gate.
    const form=new FormData();form.set('csrf_token',csrf);form.set('audio',blob,'recording.wav');form.set('consent','yes');
    form.set('style',style.value);form.set('translate',translate.checked?'yes':'no');form.set('target',target.value);
    setPhase('processing');
    const timeout=setTimeout(()=>reset('network'),180000);
    try{
      if(!sessionId){
        const sessionForm=new FormData();sessionForm.set('csrf_token',csrf);
        const createdResponse=await fetch('/kilas-ai/copilot/sessions',{method:'POST',body:sessionForm,signal:controller.signal});
        if(!createdResponse.ok)throw Error('network');const created=await createdResponse.json();
        if(mine!==epoch)return;
        sessionId=String(created.id);root.dataset.sessionId=sessionId;root.dataset.threadId=sessionId;history.replaceState(null,'',created.url);
      }
      if(mine!==epoch)return;
      operation=crypto.randomUUID().replaceAll('-','');
      const response=await fetch(`/kilas-ai/copilot/sessions/${sessionId}/${operation}/process`,{method:'POST',headers:{'X-CSRF-Token':csrf},body:form,signal:controller.signal});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw Error(body.code||'network');}
      const accepted=await response.json();
      await pollOperation(accepted.status_url,view=>applySnapshot(view,mine),controller.signal);
      if(mine===epoch){operation=null;controller=null;setPhase('idle');draw();state.textContent=t('Jawaban siap');}
    }catch(e){
      if(mine===epoch){cancelRequest();operation=null;partial?.remove();partial=null;draw();setPhase('idle');notice(e.message);}
    }finally{clearTimeout(timeout);}
  }
  function mergeTurn(turn){
    const index=turns.findIndex(previous=>previous.id===turn.id||previous.operation_key&&previous.operation_key===turn.operation_key);
    if(index<0)turns.push(turn);else turns[index]=turn;
  }
  function applySnapshot(view,mine){
    if(mine!==epoch)throw Error('cancelled');
    if(view.primary){mergeTurn(view.primary);partial?.remove();partial=null;draw();}
    else if(view.text){
      setPhase('streaming');
      if(!partial){partial=document.createElement('article');partial.className='copilot-turn is-partial';partial.setAttribute('aria-label',t('Saran AI sedang diproses'));const card=document.createElement('section');card.className='copilot-answer-card';paragraph(card,'copilot-reply',t('Saran jawaban AI · belum selesai'),'');card.append(resultTools);partial.append(card);$('turns').prepend(partial);resultTools.hidden=false;}
      partial.querySelector('.copilot-reply').textContent=view.text;
    }
    if(view.status_text)state.textContent=view.status_text;
    if(view.state==='complete'){
      mergeTurn(view.result.turn);partial?.remove();partial=null;draw();
      const list=document.querySelector('#kilas-chat-list');
      if(list){
        let link=list.querySelector(`a[href="/kilas-ai/threads/${sessionId}"]`);
        if(!link){link=document.createElement('a');link.href=`/kilas-ai/threads/${sessionId}`;link.className='ai-history-item';link.dataset.chatNavigation='';}
        link.textContent=view.result.title||view.result.turn.source.slice(0,68);link.title=link.textContent;link.setAttribute('aria-current','page');list.prepend(link);list.querySelector('.ai-sidebar-empty')?.remove();
      }
    }
  }
  async function retryTranslation(turn){
    if(phase!=='idle')return;
    const mine=++epoch;operation=crypto.randomUUID().replaceAll('-','');controller=new AbortController();error.hidden=true;setPhase('processing');draw();
    const timeout=setTimeout(()=>reset('network'),150000);
    try{
      const body=new FormData();body.set('csrf_token',csrf);
      const response=await fetch(`/kilas-ai/copilot/sessions/${sessionId}/${turn.operation_key}/translation/${operation}`,{method:'POST',body,signal:controller.signal});
      if(!response.ok){const result=await response.json().catch(()=>({}));throw Error(result.code||'network');}
      const accepted=await response.json();await pollOperation(accepted.status_url,view=>applySnapshot(view,mine),controller.signal);
      if(mine===epoch){operation=null;controller=null;setPhase('idle');draw();state.textContent=t('Jawaban siap');}
    }catch(e){if(mine===epoch)reset(e.message);}
    finally{clearTimeout(timeout);}
  }
  // Both reference controls share one state guard and recording operation.
  function captureAction(){if(phase==='idle')begin();else if(['listening','captured'].includes(phase))process();}
  mic.addEventListener('click',captureAction);trigger.addEventListener('click',captureAction);
  cancel.addEventListener('click',()=>reset('cancelled'));
  window.addEventListener('beforeunload',()=>reset(null,true));
  window.addEventListener('pagehide',()=>reset(null,true));
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&phase!=='idle')reset('cancelled',true);});
  window.addEventListener('offline',()=>{if(phase!=='idle')reset('network',true);});
  styleButtons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.copilotStyle===style.value)));
  draw();setPhase('idle');
}
