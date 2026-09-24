(() => {
  const root=document.querySelector('[data-web-chat]');if(!root)return;
  const base=root.dataset.base,thread=root.querySelector('[data-thread]'),status=root.querySelector('[data-status]'),form=root.querySelector('form'),input=root.querySelector('textarea'),retry=root.querySelector('[data-retry]');
  const storageKey='kw-web-pending:'+base;
  let identity=null,after=0,pending=null,sending=false,stopped=false;
  function saved(){try{pending=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch(error){pending=null;}}
  function persist(){try{if(pending)sessionStorage.setItem(storageKey,JSON.stringify(pending));else sessionStorage.removeItem(storageKey);}catch(error){/* In-memory retry remains available. */}}
  function lock(value){input.disabled=value;form.querySelector('button').disabled=value;}
  async function json(url,options={}){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),55000);
    try{
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});
      let data;try{data=await response.json();}catch(error){data={};}
      return {response,data};
    }finally{clearTimeout(timeout);}
  }
  function postOptions(payload){return {method:'POST',headers:{'Content-Type':'application/json','X-Web-Chat':'1',...(identity?{'X-Web-CSRF':identity.csrf}:{})},body:JSON.stringify(payload)};}
  async function poll(){
    if(stopped||!identity)return;
    let delay=3000;
    try{
      const {response,data}=await json(base+'/'+identity.conversation_id+'/messages?after='+after);
      if(!response.ok){if([403,404].includes(response.status)){stopped=true;lock(true);status.textContent='Sesi berakhir atau chat tidak tersedia. Muat ulang halaman.';return;}throw new Error();}
      for(const message of data.messages){
        const bubble=document.createElement('div');bubble.className='web-bubble '+message.role;
        const label=document.createElement('small');label.textContent=message.role==='user'?'Kamu':(message.role==='human'?'Tim':'Asisten AI');
        bubble.append(label,document.createTextNode(message.content));thread.append(bubble);after=message.id;
      }
      if(data.messages.length){thread.scrollTop=thread.scrollHeight;root.querySelector('.web-welcome').hidden=true;}
      if(data.messages.length===100)delay=100;
      root.querySelector('[data-mode]').textContent=data.mode==='HUMAN_TAKEOVER'?'Tim akan membalas di sini':'Asisten AI aktif';
    }catch(error){if(!sending)status.textContent='Koneksi terputus. Mencoba kembali…';delay=6000;}
    setTimeout(poll,delay);
  }
  async function flush(){
    if(!pending||sending||stopped)return;sending=true;lock(true);retry.hidden=true;status.textContent='AI sedang menyiapkan balasan…';
    try{
      const {response,data}=await json(base+'/'+identity.conversation_id+'/messages',postOptions({message:pending.message,event_id:pending.event_id}));
      if(response.status===202){status.textContent='Pesan sedang diproses…';setTimeout(flush,5000);return;}
      if(data.status==='failed'){
        pending=null;persist();input.value='';status.textContent='Pesan tersimpan, tetapi AI belum bisa membalas. Kamu bisa mengirim pesan baru.';lock(false);return;
      }
      if(!response.ok)throw new Error(response.status===429?'Batas pesan tercapai. Tunggu sebentar lalu coba lagi.':'Pesan belum dikonfirmasi. Coba kirim lagi.');
      pending=null;persist();input.value='';status.textContent='Pesan tersimpan.';lock(false);
    }catch(error){status.textContent=error.message||'Koneksi terputus. Coba kirim lagi.';retry.hidden=false;}
    finally{sending=false;}
  }
  form.addEventListener('submit',event=>{
    event.preventDefault();if(!identity||pending||!input.value.trim())return;
    pending={event_id:crypto.randomUUID(),message:input.value.trim(),cid:identity.conversation_id};persist();flush();
  });
  retry.addEventListener('click',flush);
  (async()=>{
    try{
      const {response,data}=await json(base+'/session',postOptions({}));
      if(!response.ok)throw new Error();identity=data;saved();
      if(pending&&pending.cid!==identity.conversation_id){pending=null;persist();}
      status.textContent='';lock(false);poll();if(pending){input.value=pending.message;flush();}
    }catch(error){status.textContent='Chat belum dapat dibuka. Muat ulang halaman untuk mencoba lagi.';lock(true);}
  })();
})();
