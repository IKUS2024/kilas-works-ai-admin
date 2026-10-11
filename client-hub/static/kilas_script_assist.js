/* Text assistance reuses authorized chat; applying text never submits an audio job. */
(() => {
  const root=document.querySelector('#voice-script-assist');if(!root)return;
  const el=name=>document.querySelector('#voice-assist-'+name);
  const prompt=el('prompt'),script=document.querySelector('#audio-script'),status=el('status'),generate=el('generate'),stop=el('stop'),mic=el('mic'),micStop=el('mic-stop');
  let thread=null,controller=null,recognition=null,dictating=false,version=0,undo=null;
  const mode=el('mode');
  const changed=()=>{version++;undo=null;el('undo').hidden=true;usable();};
  const apply=value=>{script.value=value;script.dispatchEvent(new Event('input',{bubbles:true}));};
  mode.addEventListener('change',()=>{haltDictation();el('idea').hidden=mode.value!=='generate';});
  const usable=()=>{el('copy').disabled=!script.value.trim();};
  const haltDictation=()=>{if(recognition)recognition.abort();dictating=false;micStop.hidden=true;mic.disabled=!!controller||!Recognition;};
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){mic.disabled=true;el('mic-note').textContent='Dikte belum didukung browser ini. Ketik arahan naskah di atas.';}
  else {
    mic.addEventListener('click',()=>{
      if(dictating||controller)return;
      mode.value='generate';el('idea').hidden=false;
      const initial=prompt.value.trim();recognition=new Recognition();recognition.lang=document.documentElement.lang||'id-ID';recognition.continuous=false;recognition.interimResults=false;
      recognition.onresult=event=>{if(document.hidden||!root.open)return;let text=initial;for(let i=event.resultIndex;i<event.results.length;i++)if(event.results[i].isFinal)text+=' '+event.results[i][0].transcript;prompt.value=text.trim().slice(0,4000);status.textContent='Dikte masuk ke arahan. Periksa teks, lalu tekan Bantu naskah.';};
      recognition.onerror=event=>{status.textContent=event.error==='not-allowed'?'Izin mic tidak diberikan. Kamu tetap bisa mengetik arahan.':event.error==='aborted'?'Dikte dihentikan. Arahan tetap bisa diedit.':'Dikte belum berhasil. Ketik arahan atau coba mic lagi.';};
      recognition.onend=()=>{dictating=false;micStop.hidden=true;mic.disabled=!!controller||!Recognition;};
      try{recognition.start();dictating=true;mic.disabled=true;micStop.hidden=false;status.textContent='Mendengarkan arahan. Tekan Stop dikte untuk berhenti.';}catch(_){haltDictation();status.textContent='Mic belum dapat dimulai. Ketik arahan atau coba lagi.';}
    });
  }
  micStop.addEventListener('click',()=>{recognition?.stop();status.textContent='Menghentikan dikte…';});
  function leave(){haltDictation();controller?.abort();}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)leave();});window.addEventListener('pagehide',leave);
  document.querySelector('#translate-tab')?.addEventListener('click',leave);root.addEventListener('toggle',()=>{if(!root.open)leave();});
  stop.addEventListener('click',()=>controller?.abort());
  async function checked(response){if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');if(!response.ok){let body;try{body=await response.json();}catch(_){}throw Error(body?.error||'Naskah belum berhasil dibuat. Coba lagi.');}return response;}
  generate.addEventListener('click',async()=>{
    if(controller||dictating)return;
    if(document.querySelector('#voice-video-script')?.dataset.busy==='true'){status.textContent='Selesaikan pengambilan naskah video terlebih dahulu.';return;}
    const content=(mode.value==='tidy'?script.value:prompt.value).trim(),before=script.value,startVersion=version;
    if(!content){status.textContent=mode.value==='tidy'?'Tulis naskah terlebih dahulu, atau pilih Buat naskah dari ide.':'Tulis atau dikte ide terlebih dahulu.';(mode.value==='tidy'?script:prompt).focus();return;}
    if(content.length>4000){status.textContent='Naskah atau ide maksimal 4.000 karakter. Teks tetap aman.';return;}
    controller=new AbortController();root.dataset.busy='true';generate.disabled=true;prompt.disabled=true;mode.disabled=true;mic.disabled=true;stop.hidden=false;status.textContent='Menulis naskah…';
    const csrf=document.querySelector('#voiceover-panel [name=csrf_token]').value;
    const headers={'Content-Type':'application/json','X-CSRF-Token':csrf};
    try {
      if(!thread){const response=await checked(await fetch('/kilas-ai/threads',{method:'POST',headers,body:JSON.stringify({first_message:content}),signal:controller.signal,credentials:'same-origin'}));const body=await response.json();thread=body.thread_id;el('history').href=body.url;el('history').hidden=false;}
      const response=await checked(await fetch(`/kilas-ai/threads/${thread}/voice-script`,{method:'POST',headers,body:JSON.stringify({content,script_mode:mode.value,operation_key:Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('')}),signal:controller.signal,credentials:'same-origin'}));
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',draft='',done=false,error=null;
      while(true){const packet=await reader.read();if(packet.done)break;buffer+=decoder.decode(packet.value,{stream:true});let cut;while((cut=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,cut);buffer=buffer.slice(cut+2);const lines=frame.split('\n'),event=lines.find(l=>l.startsWith('event: '))?.slice(7),data=lines.find(l=>l.startsWith('data: '))?.slice(6);if(!data)continue;const body=JSON.parse(data);if(event==='reset')draft='';if(event==='delta'){draft+=body.text||'';if(draft.length>12000)throw Error('Naskah terlalu panjang. Pendekkan arahan lalu coba lagi.');}if(event==='error'||event==='busy')error=body.message||'Naskah belum selesai.';if(event==='done')done=true;}}
      if(error||!done||!draft.trim())throw Error(error||'Naskah terputus. Teks semula tetap aman; coba lagi.');
      if(draft.length>4000)throw Error('Hasil melebihi 4.000 karakter. Teks semula tetap aman; pendekkan arahan lalu coba lagi.');
      if(version!==startVersion||script.value!==before){status.textContent='Naskah sudah kamu edit. Hasil AI tidak menimpa edit tersebut; lihat percakapan atau coba lagi.';return;}
      apply(draft);undo={before,applied:draft,version};el('undo').hidden=false;status.textContent='Naskah masuk ke kolom dan siap diperiksa. Belum ada audio yang dibuat.';
    }catch(error){status.textContent=error.name==='AbortError'?'AI dihentikan. Naskah semula tetap aman; belum ada audio yang dibuat.':error instanceof TypeError?'Koneksi terputus. Periksa naskah atau coba lagi.':error.message;}
    finally{controller=null;root.dataset.busy='false';generate.disabled=false;prompt.disabled=false;mode.disabled=false;mic.disabled=!Recognition;stop.hidden=true;usable();}
  });
  script.addEventListener('input',changed);
  el('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(script.value);status.textContent='Naskah disalin.';}catch(_){status.textContent='Salin otomatis belum tersedia. Pilih teks naskah untuk menyalin.';script.focus();script.select();}});
  el('undo').addEventListener('click',()=>{if(!undo||controller)return;if(script.value!==undo.applied||version!==undo.version){undo=null;el('undo').hidden=true;return;}const before=undo.before;apply(before);status.textContent='Naskah sebelum bantuan AI dikembalikan.';});usable();
})();
