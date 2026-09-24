(() => {
  const panel=document.querySelector('[data-owner-chat]'); if(!panel) return;
  const thread=panel.querySelector('[data-thread]'), status=panel.querySelector('[data-status]');
  let after=0;
  const form=panel.querySelector('[data-reply]'), input=form.querySelector('textarea'), sendStatus=panel.querySelector('[data-send-status]');
  let pending=null,sending=false;
  async function post(url,payload){
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':panel.dataset.csrf},body:JSON.stringify(payload)});
    if(!response.ok) throw new Error(response.status===409?'Ambil alih chat sebelum membalas.':'Belum berhasil. Coba lagi.');
    return response.json();
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
    try{await post(panel.dataset.replyUrl,pending);pending=null;input.value='';sendStatus.textContent='Balasan terkirim.';}
    catch(error){sendStatus.textContent=error.message;}finally{sending=false;}
  });
  async function refresh(){
    try {
      const response=await fetch(panel.dataset.base+'?after='+after,{cache:'no-store'});
      if(!response.ok) throw new Error('Percakapan belum dapat dimuat.');
      const data=await response.json();
      for(const message of data.messages){
        const bubble=document.createElement('div'); bubble.className='web-bubble '+message.role;
        const label=document.createElement('small');label.textContent=message.role==='user'?'Pengunjung':(message.role==='human'?'Tim':'AI');
        bubble.append(label,document.createTextNode(message.content));thread.append(bubble);after=message.id;
      }
      if(data.messages.length) thread.scrollTop=thread.scrollHeight;
      panel.querySelector('[data-mode]').textContent=data.mode==='HUMAN_TAKEOVER'?'Ditangani tim':'AI aktif';
      input.disabled=data.mode!=='HUMAN_TAKEOVER';form.querySelector('button').disabled=input.disabled;
      panel.querySelector('[data-takeover]').hidden=data.mode==='HUMAN_TAKEOVER';
      panel.querySelector('[data-return]').hidden=data.mode!=='HUMAN_TAKEOVER';
      status.textContent='';
    } catch(error){status.textContent='Koneksi terputus. Mencoba kembali…';}
    setTimeout(refresh,3000);
  }
  refresh();
})();
