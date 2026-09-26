(() => {
  const panel=document.querySelector('[data-owner-chat]'); if(!panel) return;
  const thread=panel.querySelector('[data-thread]'), status=panel.querySelector('[data-status]');
  let after=0;const labels=new Map();
  const form=panel.querySelector('[data-reply]'), input=form.querySelector('textarea'), sendStatus=panel.querySelector('[data-send-status]');
  const mediaForm=panel.querySelector('[data-media-form]'), mediaPanel=panel.querySelector('[data-media-panel]');
  const windowState=panel.querySelector('[data-window-state]'), windowNote=panel.querySelector('[data-window-note]');
  let pending=null,sending=false;
  async function post(url,payload){
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':panel.dataset.csrf},body:JSON.stringify(payload)});
    const data=await response.json();
    if(!response.ok) throw new Error(data.error?.startsWith('whatsapp_')?'Pengiriman belum terkonfirmasi. Periksa status sebelum membuat pesan baru.':(response.status===409?'Periksa pengambilalihan dan jendela balasan WhatsApp.':'Belum berhasil. Coba lagi.'));
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
    try{const result=await post(panel.dataset.replyUrl,pending);pending=null;input.value='';sendStatus.textContent=result.channel==='WHATSAPP'?'Diterima Meta; menunggu status pengiriman.':'Balasan terkirim.';}
    catch(error){sendStatus.textContent=error.message;}finally{sending=false;}
  });
  const templateButton=panel.querySelector('[data-template-url]');let templatePending=null;
  templateButton?.addEventListener('click',async()=>{
    if(sending)return;sending=true;
    templatePending ||= {event_id:crypto.randomUUID()};
    try{await post(templateButton.dataset.templateUrl,templatePending);templatePending=null;sendStatus.textContent='Template diterima Meta; menunggu status pengiriman.';}
    catch(error){sendStatus.textContent=error.message;}finally{sending=false;}
  });
  if(mediaForm){
    mediaForm.addEventListener('submit',async event=>{
      event.preventDefault();
      if(sending)return;
      const file=mediaForm.querySelector('input[type="file"]');
      if(!file||!file.files||!file.files.length)return;
      sending=true;
      sendStatus.textContent='Mengirim media…';
      const body=new FormData(mediaForm);
      try{
        const response=await fetch(mediaForm.action,{
          method:'POST',body,credentials:'same-origin',
          headers:{'X-CSRF-Token':panel.dataset.csrf}
        });
        const data=await response.json();
        if(!response.ok)throw new Error(response.status===409
          ?'Media tidak dapat dikirim sekarang. Periksa Human Takeover dan jendela WhatsApp.'
          :'Media belum berhasil dikirim.');
        mediaForm.reset();
        sendStatus.textContent=data.history==='unavailable'
          ?'Media diterima Meta; history lokal akan disinkronkan.'
          :'Media diterima Meta; menunggu status pengiriman.';
        await refresh();
      }catch(error){
        sendStatus.textContent=error.message;
      }finally{sending=false;}
    });
  }

  async function refresh(){
    try {
      const response=await fetch(panel.dataset.base+'?after='+after,{cache:'no-store'});
      if(!response.ok) throw new Error('Percakapan belum dapat dimuat.');
      const data=await response.json();
      for(const message of data.messages){
        const bubble=document.createElement('div'); bubble.className='web-bubble '+message.role;
        const label=document.createElement('small');label.textContent=message.role==='user'?'Pengunjung':(message.role==='human'?'Tim':'AI');
        if(message.delivery_status)label.textContent+=' · '+message.delivery_status;
        labels.set(String(message.id),{label,role:message.role});
        bubble.append(label);
        if(message.media){
          let node;
          if(message.media.message_type==='image'||message.media.message_type==='sticker'){
            node=document.createElement('img');node.className='web-media';node.src=message.media.url;
            node.alt=message.media.filename||'Media WhatsApp';node.loading='lazy';
          }else if(message.media.message_type==='video'){
            node=document.createElement('video');node.className='web-media';node.src=message.media.url;
            node.controls=true;node.preload='none';
          }else if(message.media.message_type==='audio'){
            node=document.createElement('audio');node.src=message.media.url;node.controls=true;node.preload='none';
          }else{
            node=document.createElement('a');node.className='web-media-link';node.href=message.media.url;
            node.target='_blank';node.rel='noopener';node.textContent='Unduh '+(message.media.filename||'dokumen');
          }
          bubble.append(node);
          if(message.media.caption){
            const caption=document.createElement('div');caption.textContent=message.media.caption;caption.style.whiteSpace='pre-wrap';
            bubble.append(caption);
          }
        }else{
          bubble.append(document.createTextNode(message.content));
        }
        thread.append(bubble);after=message.id;
      }
      for(const [id,delivery] of Object.entries(data.delivery||{})){
        const entry=labels.get(id);if(entry&&delivery)entry.label.textContent=(entry.role==='human'?'Tim':'AI')+' · '+delivery;
      }
      if(data.messages.length) thread.scrollTop=thread.scrollHeight;
      const human=data.mode==='HUMAN_TAKEOVER';
      const wa=data.channel==='WHATSAPP';
      const freeform=human&&(!wa||Boolean(data.window&&data.window.allowed));
      panel.querySelector('[data-mode]').textContent=human?'Ditangani tim':'AI aktif';
      input.disabled=!freeform;form.querySelector('button').disabled=!freeform;
      panel.querySelector('[data-takeover]').hidden=human;
      panel.querySelector('[data-return]').hidden=!human;
      if(templateButton){
        const needsTemplate=wa&&human&&!freeform;
        templateButton.hidden=!needsTemplate;
        templateButton.disabled=!needsTemplate||!data.template_ready;
      }
      if(mediaPanel)mediaPanel.hidden=!freeform;
      if(mediaForm){
        for(const field of mediaForm.querySelectorAll('input,button'))field.disabled=!freeform;
      }
      if(windowState&&wa){
        windowState.textContent=freeform?'WhatsApp siap dibalas':'Human tetap aktif · perlu template';
      }
      if(windowNote&&wa){
        windowNote.textContent=freeform
          ?'Human Takeover tetap aktif sampai kamu klik Kembalikan ke AI. Free-text dan media bisa dikirim sekarang.'
          :'Human Takeover tetap aktif. Karena jendela WhatsApp sudah lewat, kirim template resmi dulu; setelah customer membalas, free-text dan media aktif lagi.';
      }
      status.textContent='';
    } catch(error){status.textContent='Koneksi terputus. Mencoba kembali…';}
    setTimeout(refresh,3000);
  }
  refresh();
})();
