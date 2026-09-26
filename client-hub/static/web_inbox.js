(() => {
  const panel=document.querySelector('[data-owner-chat]'); if(!panel) return;
  const thread=panel.querySelector('[data-thread]'), status=panel.querySelector('[data-status]');
  let after=0;const labels=new Map();
  const form=panel.querySelector('[data-reply]'), input=form.querySelector('textarea'),
        sendStatus=panel.querySelector('[data-send-status]');
  const mediaForm=panel.querySelector('[data-media-form]'), templateButton=panel.querySelector('[data-template-url]'),
        windowNote=panel.querySelector('[data-window-note]');
  let pending=null,sending=false,templatePending=null;

  function friendlyError(data,httpStatus){
    const code=(data&&data.error)||'';
    if(code==='invalid_media')return 'Gunakan JPG/PNG maksimal 5 MB atau PDF maksimal 10 MB.';
    if(code==='outside_24h_window'||code==='whatsapp_suppressed')return 'Di luar jendela WhatsApp. Kirim template resmi lalu tunggu customer membalas.';
    if(code==='human_takeover_required')return 'Ambil alih percakapan dulu.';
    if(code.startsWith('whatsapp_'))return 'Pengiriman belum terkonfirmasi. Periksa status sebelum mengirim ulang.';
    if(httpStatus===409)return 'Periksa pengambilalihan dan jendela balasan WhatsApp.';
    return 'Belum berhasil. Coba lagi.';
  }

  async function post(url,payload){
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':panel.dataset.csrf},body:JSON.stringify(payload)});
    const data=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(friendlyError(data,response.status));
    return data;
  }

  for(const [selector,mode] of [['[data-takeover]','HUMAN_TAKEOVER'],['[data-return]','AI_ACTIVE']]){
    panel.querySelector(selector).addEventListener('click',async()=>{
      try{await post(panel.dataset.modeUrl,{mode});sendStatus.textContent='Status diperbarui.';}
      catch(error){sendStatus.textContent=error.message;}
    });
  }

  form.addEventListener('submit',async event=>{
    event.preventDefault();if(sending||!input.value.trim())return;sending=true;
    if(!pending||pending.message!==input.value.trim())pending={event_id:crypto.randomUUID(),message:input.value.trim()};
    try{
      const result=await post(panel.dataset.replyUrl,pending);pending=null;input.value='';
      sendStatus.textContent=result.channel==='WHATSAPP'?'Diterima Meta; menunggu status pengiriman.':'Balasan terkirim.';
    }catch(error){sendStatus.textContent=error.message;}finally{sending=false;}
  });

  mediaForm?.addEventListener('submit',async event=>{
    event.preventDefault();if(sending)return;
    const file=mediaForm.querySelector('[name=file]');
    if(!file.files||file.files.length!==1)return;
    sending=true;
    const body=new FormData(mediaForm);
    body.set('event_id',crypto.randomUUID());
    try{
      const response=await fetch(panel.dataset.mediaUrl,{method:'POST',body});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(friendlyError(data,response.status));
      file.value='';mediaForm.querySelector('[name=caption]').value='';
      sendStatus.textContent='Media diterima Meta; menunggu status pengiriman.';
    }catch(error){sendStatus.textContent=error.message;}finally{sending=false;}
  });

  templateButton?.addEventListener('click',async()=>{
    if(sending)return;sending=true;
    templatePending ||= {event_id:crypto.randomUUID()};
    try{
      await post(templateButton.dataset.templateUrl,templatePending);templatePending=null;
      sendStatus.textContent='Template diterima Meta; menunggu status pengiriman.';
    }catch(error){sendStatus.textContent=error.message;}finally{sending=false;}
  });

  function appendMedia(bubble,message){
    const media=message.media;
    if(!media){bubble.append(document.createTextNode(message.content));return;}
    let asset=null;
    if(media.message_type==='image'||media.message_type==='sticker'){
      asset=document.createElement('img');asset.loading='lazy';asset.alt=media.filename||'Gambar';
    }else if(media.message_type==='video'){
      asset=document.createElement('video');asset.controls=true;asset.preload='none';
    }else if(media.message_type==='audio'){
      asset=document.createElement('audio');asset.controls=true;asset.preload='none';
    }else{
      asset=document.createElement('a');asset.textContent='Unduh '+(media.filename||'dokumen');
      asset.target='_blank';asset.rel='noopener';asset.className='web-media-document';
    }
    asset.src=media.url; if(asset.tagName==='A')asset.href=media.url;
    if(asset.tagName!=='A')asset.className='web-media-asset';
    asset.addEventListener?.('error',()=>{asset.hidden=true;const fallback=document.createElement('span');fallback.textContent='Media tidak tersedia';bubble.append(fallback);});
    bubble.append(asset);
    const caption=media.caption||'';
    if(caption){
      const text=document.createElement('div');text.className='web-media-caption';text.textContent=caption;bubble.append(text);
    }
  }

  function setComposeState(data){
    const human=data.mode==='HUMAN_TAKEOVER';
    const free=data.channel!=='WHATSAPP'||data.freeform_allowed!==false;
    const canSend=human&&free;
    input.disabled=!canSend;form.querySelector('button').disabled=!canSend;
    if(mediaForm){
      for(const field of mediaForm.querySelectorAll('input[name=file],input[name=caption],button[type=submit]'))field.disabled=!canSend;
    }
    if(templateButton)templateButton.disabled=!human;
    panel.querySelector('[data-takeover]').hidden=human;
    panel.querySelector('[data-return]').hidden=!human;
    panel.querySelector('[data-mode]').textContent=human?'Ditangani tim':'AI aktif';
    if(windowNote){
      windowNote.textContent=human&&!free
        ?'Di luar jendela balasan WhatsApp. Gunakan Template & Lanjutkan; setelah customer membalas, teks dan media aktif lagi.'
        :'';
    }
  }

  async function refresh(){
    try {
      const response=await fetch(panel.dataset.base+'?after='+after,{cache:'no-store'});
      if(!response.ok) throw new Error('Percakapan belum dapat dimuat.');
      const data=await response.json();
      for(const message of data.messages){
        const bubble=document.createElement('div'); bubble.className='web-bubble '+message.role;
        const label=document.createElement('small');label.textContent=message.role==='user'?'Customer':(message.role==='human'?'Tim':'AI');
        if(message.delivery_status)label.textContent+=' · '+message.delivery_status;
        labels.set(String(message.id),{label,role:message.role});
        bubble.append(label);appendMedia(bubble,message);thread.append(bubble);after=message.id;
      }
      for(const [id,delivery] of Object.entries(data.delivery||{})){
        const entry=labels.get(id);if(entry&&delivery)entry.label.textContent=(entry.role==='human'?'Tim':'AI')+' · '+delivery;
      }
      if(data.messages.length) thread.scrollTop=thread.scrollHeight;
      setComposeState(data);
      status.textContent='';
    } catch(error){status.textContent='Koneksi terputus. Mencoba kembali…';}
    setTimeout(refresh,3000);
  }
  refresh();
})();
