/* Text assistance reuses authorized chat; applying text never submits an audio job. */
(() => {
  const t=(message,values)=>window.KilasUI ? window.KilasUI.t(message,values) : Object.entries(values||{}).reduce((text,[key,value])=>text.replaceAll('{'+key+'}',String(value)),message);
  const root=document.querySelector('#voice-script-assist');if(!root)return;
  const el=name=>document.querySelector('#voice-assist-'+name);
  const prompt=el('prompt'),script=document.querySelector('#audio-script'),status=el('status'),generate=el('generate'),stop=el('stop');
  let thread=null,controller=null,version=0,undo=null;
  const mode=el('mode');
  const changed=()=>{version++;undo=null;el('undo').hidden=true;};
  const apply=value=>{script.value=value;script.dispatchEvent(new Event('input',{bubbles:true}));};
  mode.addEventListener('change',()=>{el('idea').hidden=mode.value!=='generate';});
  function leave(){controller?.abort();}
  document.addEventListener('visibilitychange',()=>{if(document.hidden)leave();});window.addEventListener('pagehide',leave);
  document.querySelector('#translate-tab')?.addEventListener('click',leave);root.addEventListener('toggle',()=>{if(!root.open)leave();});
  stop.addEventListener('click',()=>controller?.abort());
  async function checked(response){if(response.redirected)throw Error(t('Sesi berakhir. Masuk kembali untuk melanjutkan.'));if(!response.ok){let body;try{body=await response.json();}catch(_){}throw Error(body?.error||t('Naskah belum berhasil dibuat. Coba lagi.'));}return response;}
  generate.addEventListener('click',async()=>{
    if(controller)return;
    if(document.querySelector('#voice-video-script')?.dataset.busy==='true'){status.textContent=t('Selesaikan pengambilan naskah video terlebih dahulu.');return;}
    const content=(mode.value==='tidy'?script.value:prompt.value).trim(),before=script.value,startVersion=version;
    if(!content){status.textContent=mode.value==='tidy'?t('Tulis naskah terlebih dahulu, atau pilih Buat naskah dari ide.'):t('Tulis atau dikte ide terlebih dahulu.');(mode.value==='tidy'?script:prompt).focus();return;}
    if(content.length>4000){status.textContent=t('Naskah atau ide maksimal 4.000 karakter. Teks tetap aman.');return;}
    controller=new AbortController();root.dataset.busy='true';generate.disabled=true;prompt.disabled=true;mode.disabled=true;stop.hidden=false;status.textContent=t('Menulis naskah…');
    const csrf=document.querySelector('#voiceover-panel [name=csrf_token]').value;
    const headers={'Content-Type':'application/json','X-CSRF-Token':csrf};
    try {
      if(!thread){const response=await checked(await fetch('/kilas-ai/threads',{method:'POST',headers,body:JSON.stringify({first_message:content}),signal:controller.signal,credentials:'same-origin'}));const body=await response.json();thread=body.thread_id;el('history').href=body.url;el('history').hidden=false;}
      const response=await checked(await fetch(`/kilas-ai/threads/${thread}/voice-script`,{method:'POST',headers,body:JSON.stringify({content,script_mode:mode.value,operation_key:Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('')}),signal:controller.signal,credentials:'same-origin'}));
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',draft='',done=false,error=null;
      while(true){const packet=await reader.read();if(packet.done)break;buffer+=decoder.decode(packet.value,{stream:true});let cut;while((cut=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,cut);buffer=buffer.slice(cut+2);const lines=frame.split('\n'),event=lines.find(l=>l.startsWith('event: '))?.slice(7),data=lines.find(l=>l.startsWith('data: '))?.slice(6);if(!data)continue;const body=JSON.parse(data);if(event==='reset')draft='';if(event==='delta'){draft+=body.text||'';if(draft.length>12000)throw Error(t('Naskah terlalu panjang. Pendekkan arahan lalu coba lagi.'));}if(event==='error'||event==='busy')error=body.message||t('Naskah belum selesai.');if(event==='done')done=true;}}
      if(error||!done||!draft.trim())throw Error(error||t('Naskah terputus. Teks semula tetap aman; coba lagi.'));
      if(draft.length>4000)throw Error(t('Hasil melebihi 4.000 karakter. Teks semula tetap aman; pendekkan arahan lalu coba lagi.'));
      if(version!==startVersion||script.value!==before){status.textContent=t('Naskah sudah kamu edit. Hasil AI tidak menimpa edit tersebut; lihat percakapan atau coba lagi.');return;}
      apply(draft);undo={before,applied:draft,version};el('undo').hidden=false;status.textContent=t('Naskah masuk ke kolom dan siap diperiksa. Belum ada audio yang dibuat.');
    }catch(error){status.textContent=error.name==='AbortError'?t('AI dihentikan. Naskah semula tetap aman; belum ada audio yang dibuat.'):error instanceof TypeError?t('Koneksi terputus. Periksa naskah atau coba lagi.'):error.message;}
    finally{controller=null;root.dataset.busy='false';generate.disabled=false;prompt.disabled=false;mode.disabled=false;stop.hidden=true;}
  });
  script.addEventListener('input',changed);
  el('undo').addEventListener('click',()=>{if(!undo||controller)return;if(script.value!==undo.applied||version!==undo.version){undo=null;el('undo').hidden=true;return;}const before=undo.before;apply(before);status.textContent=t('Naskah sebelum bantuan AI dikembalikan.');});
})();
