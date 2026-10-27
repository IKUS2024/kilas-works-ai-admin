import {PcmEncoder} from './kilas_live_translator_pcm.mjs';

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
      let end;while((end=pending.indexOf('\n\n'))>=0){
        const frame=pending.slice(0,end);pending=pending.slice(end+2);
        for(const line of frame.split('\n'))if(line.startsWith('data: ')){
          const event=JSON.parse(line.slice(6));receive(event);
          if(event.type==='complete')complete=true;
          if(event.type==='error')throw Error(event.code);
        }
      }
      if(done)break;
    }
    if(!complete)throw Error('incomplete_stream');
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
}

const root=globalThis.document?.querySelector('#copilot');
if(root){
  const $=id=>document.getElementById('copilot-'+id), mic=$('mic'),state=$('state'),action=$('action'),error=$('error');
  const translate=$('translate'),target=$('target'),style=$('style'),consent=$('consent'),cancel=$('cancel');
  const csrf=$('csrf').value, turns=JSON.parse($('initial').textContent);
  const resultTools=root.querySelector('.copilot-result-tools');
  const styleButtons=[...root.querySelectorAll('[data-copilot-style]')];let textSize=22;
  let phase='idle',epoch=0,capture=null,chunks=[],sessionId=root.dataset.sessionId,operation=null,controller=null,timer=null,partial=null;
  const messages={
    silence:'Tidak terdengar ucapan. Dekatkan mikrofon ke speaker, lalu rekam lagi.',
    unclear_audio:'Ucapan belum jelas. Rekam ulang bagian yang ingin dijawab.',
    consent_required:'Centang izin pemrosesan percakapan sebelum mulai.',
    permission:'Izin mikrofon ditolak. Izinkan mikrofon melalui pengaturan browser, lalu tekan lagi.',
    microphone:'Mikrofon tidak tersedia. Periksa perangkat dan izin browser, lalu coba lagi.',
    provider_unavailable:'Copilot belum tersedia. Minta pengelola memeriksa konfigurasi OpenAI.',
    capacity_unavailable:'Kapasitas akun belum tersedia atau masih ada proses aktif. Periksa Credits & Usage, lalu coba lagi.',
    cancelled:'Proses dibatalkan. Tekan mikrofon untuk memulai rekaman baru.',
    incomplete_stream:'Jawaban terputus dan belum disimpan. Tekan mikrofon untuk mencoba rekaman baru.',
    incomplete_translation:'Terjemahan terputus. Hasil belum disimpan; mulai rekaman baru untuk mencoba lagi.',
    operation_already_submitted:'Rekaman ini sudah dikirim. Buka ulang sesi untuk memeriksa hasilnya; tidak dikirim ulang otomatis.',
    operation_busy:'Masih ada proses aktif di sesi ini. Tunggu atau batalkan proses sebelumnya.',
    network:'Koneksi terputus. Hasil belum terkonfirmasi; buka ulang sesi sebelum mencoba rekaman baru.',
    server_busy:'Server masih memproses permintaan lain. Tunggu sebentar, lalu mulai rekaman baru.',
  };
  function notice(code){error.textContent=messages[code]||'Pemrosesan gagal. Periksa koneksi lalu mulai rekaman baru.';error.hidden=false;}
  function setPhase(next){
    phase=next;root.dataset.state=next;
    root.dataset.view=['stopping','processing','streaming'].includes(next)||(next==='idle'&&turns.length)?'results':'capture';
    const busy=['requesting','stopping','processing','streaming'].includes(next);
    mic.disabled=busy;mic.setAttribute('aria-pressed',String(next==='listening'));
    mic.setAttribute('aria-label',next==='listening'?'Berhenti dan proses jawaban':next==='captured'?'Proses rekaman':'Mulai mendengarkan');
    state.textContent=({idle:'Mikrofon mati',requesting:'Meminta izin mikrofon…',listening:'Mendengarkan…',stopping:'Menyiapkan rekaman…',captured:'Rekaman selesai · mikrofon mati',processing:'Memproses…',streaming:'Menyiapkan saran jawaban…'})[next];
    action.textContent=next==='listening'?'Tekan untuk menyiapkan jawaban':next==='captured'?'Proses rekaman':busy?'Mohon tunggu…':turns.length?'Dengarkan lagi':'Tekan untuk mendengarkan';
    cancel.hidden=next==='idle';
    for(const el of [translate,target,style,consent])el.disabled=next!=='idle';
    styleButtons.forEach(button=>button.disabled=next!=='idle');$('wave').hidden=next!=='listening';
  }
  function paragraph(parent,className,label,text){
    const h=document.createElement('h3');h.textContent=label;
    const p=document.createElement('p');p.className=className;p.textContent=text;parent.append(h,p);return p;
  }
  function draw(){
    const container=$('turns');container.replaceChildren();
    let previous=null;
    [...turns].reverse().forEach((turn,index)=>{
      const article=document.createElement('article');article.className='copilot-turn';
      if(translate.checked){
        const source=document.createElement('section');source.className='copilot-source-card';
        paragraph(source,'copilot-source','Ucapan yang didengar',turn.source);
        paragraph(source,'copilot-source-translation','Terjemahan ucapan',turn.source_translation||'Terjemahan belum dibuat untuk rekaman ini.');article.append(source);
      }
      const answer=document.createElement('section');answer.className='copilot-answer-card';
      paragraph(answer,'copilot-reply','Saran jawaban AI',turn.reply);
      if(translate.checked)paragraph(answer,'copilot-reply-translation','Terjemahan · '+([...target.options].find(option=>option.value===turn.target)?.textContent||''),turn.reply_translation||'Terjemahan belum dibuat untuk rekaman ini.');
      const copy=document.createElement('button');copy.type='button';copy.className='copilot-copy';copy.textContent='Salin jawaban';
      copy.addEventListener('click',async()=>{
        try{await navigator.clipboard.writeText(turn.reply);copy.textContent='Tersalin';setTimeout(()=>copy.textContent='Salin jawaban',1500);}
        catch{notice('copy_failed');error.textContent='Belum dapat menyalin. Pilih teks jawaban lalu salin secara manual.';}
      });answer.append(copy);if(!index)answer.append(resultTools);article.append(answer);
      if(!index)container.append(article);
      else{
        if(!previous){previous=document.createElement('details');previous.className='copilot-previous';const summary=document.createElement('summary');summary.textContent='Jawaban sebelumnya ('+(turns.length-1)+')';previous.append(summary);container.append(previous);}
        previous.append(article);
      }
    });
    resultTools.hidden=!turns.length;$('disclosure').hidden=!turns.length;
  }
  translate.addEventListener('change',()=>{$('target-wrap').hidden=!translate.checked;draw();});
  styleButtons.forEach(button=>button.addEventListener('click',()=>{style.value=button.dataset.copilotStyle;styleButtons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));}));
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
    old.stream?.getTracks().forEach(t=>t.stop());
    if(old.node){old.node.onaudioprocess=null;old.node.disconnect();}
    old.source?.disconnect();old.gain?.disconnect();old.context?.close().catch(()=>{});
  }
  function cancelRequest(beacon=false){
    if(!sessionId||!operation)return;
    const form=new FormData();form.set('csrf_token',csrf);
    const url=`/kilas-ai/copilot/sessions/${sessionId}/${operation}/cancel`;
    if(beacon)navigator.sendBeacon?.(url,form);
    else fetch(url,{method:'POST',headers:{'X-CSRF-Token':csrf},body:form,keepalive:true}).catch(()=>{});
  }
  function reset(code,beacon=false){
    ++epoch;cancelRequest(beacon);operation=null;controller?.abort();controller=null;
    release();chunks=[];partial?.remove();partial=null;draw();setPhase('idle');if(code)notice(code);
  }
  async function begin(){
    error.hidden=true;
    if(!consent.checked){notice('consent_required');consent.focus();return;}
    if(root.dataset.ready!=='true'){notice('provider_unavailable');return;}
    if(!navigator.mediaDevices?.getUserMedia){notice('microphone');return;}
    const mine=++epoch;setPhase('requesting');chunks=[];
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:false,noiseSuppression:true},video:false});
      if(mine!==epoch){stream.getTracks().forEach(t=>t.stop());return;}
      capture={stream};
      const Context=window.AudioContext||window.webkitAudioContext;
      const context=new Context();capture.context=context;await context.resume();
      if(mine!==epoch){stream.getTracks().forEach(t=>t.stop());await context.close();return;}
      const source=context.createMediaStreamSource(stream), node=context.createScriptProcessor(4096,1,1), gain=context.createGain();gain.gain.value=0;
      Object.assign(capture,{source,node,gain});
      const encoder=new PcmEncoder(context.sampleRate,frame=>{
        if(mine===epoch&&chunks.reduce((n,b)=>n+b.byteLength,0)+frame.bytes.byteLength<=60*32000)chunks.push(frame.bytes);
      });capture.encoder=encoder;
      node.onaudioprocess=e=>{
        if(mine!==epoch||phase!=='listening')return;
        try{const samples=e.inputBuffer.getChannelData(0);encoder.feed([samples]);waveform(samples);}catch{reset('microphone');}
      };
      source.connect(node);node.connect(gain);gain.connect(context.destination);
      stream.getAudioTracks().forEach(track=>track.addEventListener('ended',()=>{if(mine===epoch&&phase==='listening')reset('microphone');}));
      if(!sessionId){
        controller=new AbortController();
        const form=new FormData();form.set('csrf_token',csrf);
        const response=await fetch('/kilas-ai/copilot/sessions',{method:'POST',body:form,signal:controller.signal});
        if(!response.ok)throw Error('network');const created=await response.json();
        if(mine!==epoch)return;
        sessionId=String(created.id);root.dataset.sessionId=sessionId;root.dataset.threadId=sessionId;history.replaceState(null,'',created.url);controller=null;
      }
      if(mine!==epoch)return;
      setPhase('listening');
      timer=setTimeout(()=>{
        if(phase!=='listening')return;
        capture.encoder.finish();release();setPhase('captured');
        notice('limit');error.textContent='Batas 60 detik tercapai. Tekan mikrofon untuk memproses atau Batalkan untuk merekam ulang.';
      },60000);
    }catch(e){
      if(mine!==epoch)return;
      release();setPhase('idle');notice(e.name==='NotAllowedError'?'permission':e.message==='network'?'network':'microphone');
    }
  }
  async function process(){
    const mine=epoch;setPhase('stopping');error.hidden=true;
    $('turns').replaceChildren();resultTools.hidden=true;$('disclosure').hidden=true;
    capture?.encoder.finish();release();
    const blob=wav(chunks);chunks=[];
    if(blob.size<3244){draw();setPhase('idle');notice('unclear_audio');return;}
    operation=crypto.randomUUID().replaceAll('-','');controller=new AbortController();
    const form=new FormData();form.set('csrf_token',csrf);form.set('audio',blob,'recording.wav');form.set('consent','yes');
    form.set('style',style.value);form.set('translate',translate.checked?'yes':'no');if(translate.checked)form.set('target',target.value);
    setPhase('processing');
    const timeout=setTimeout(()=>reset('network'),180000);
    try{
      const response=await fetch(`/kilas-ai/copilot/sessions/${sessionId}/${operation}/process`,{method:'POST',headers:{'X-CSRF-Token':csrf},body:form,signal:controller.signal});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw Error(body.code||'network');}
      await readEvents(response,event=>{
        if(mine!==epoch)throw Error('cancelled');
        if(event.type==='status')state.textContent=event.text;
        if(event.type==='delta'){
          setPhase('streaming');
          if(!partial){partial=document.createElement('article');partial.className='copilot-turn is-partial';partial.setAttribute('aria-label','Saran AI sedang diproses');const card=document.createElement('section');card.className='copilot-answer-card';paragraph(card,'copilot-reply','Saran jawaban AI · belum selesai','');card.append(resultTools);partial.append(card);$('turns').prepend(partial);resultTools.hidden=false;}
          partial.querySelector('.copilot-reply').textContent+=event.text;
        }
        if(event.type==='complete'){
          turns.push(event.turn);partial?.remove();partial=null;draw();
          const list=document.querySelector('#kilas-chat-list');
          if(list){
            let link=list.querySelector(`a[href="/kilas-ai/threads/${sessionId}"]`);
            if(!link){link=document.createElement('a');link.href=`/kilas-ai/threads/${sessionId}`;link.className='ai-history-item';link.dataset.chatNavigation='';}
            link.textContent=event.title||event.turn.source.slice(0,68);link.title=link.textContent;link.setAttribute('aria-current','page');list.prepend(link);
            list.querySelector('.ai-sidebar-empty')?.remove();
          }
          state.textContent='Jawaban siap';
        }
      });
      if(mine===epoch){operation=null;controller=null;setPhase('idle');state.textContent='Jawaban siap';}
    }catch(e){
      if(mine===epoch){cancelRequest();operation=null;partial?.remove();partial=null;draw();setPhase('idle');notice(e.message);}
    }finally{clearTimeout(timeout);}
  }
  mic.addEventListener('click',()=>{if(phase==='idle')begin();else if(['listening','captured'].includes(phase))process();});
  cancel.addEventListener('click',()=>reset('cancelled'));
  window.addEventListener('beforeunload',()=>reset(null,true));
  window.addEventListener('pagehide',()=>reset(null,true));
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&phase!=='idle')reset('cancelled',true);});
  window.addEventListener('offline',()=>{if(phase!=='idle')reset('network',true);});
  draw();setPhase('idle');
}
