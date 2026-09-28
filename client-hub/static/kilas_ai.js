(()=>{
  const shell=document.querySelector('.ai-shell');if(!shell)return;
  const menu=document.querySelector('#ai-open-menu'),close=document.querySelector('#ai-close-menu'),backdrop=document.querySelector('#ai-backdrop');
  const toggle=opened=>{shell.classList.toggle('menu-open',opened);if(menu)menu.setAttribute('aria-expanded',String(opened));};
  menu?.addEventListener('click',()=>toggle(true));close?.addEventListener('click',()=>toggle(false));backdrop?.addEventListener('click',()=>toggle(false));
  const form=document.querySelector('#ai-composer');if(!form)return;
  const input=document.querySelector('#ai-input'),mode=document.querySelector('#ai-mode'),send=document.querySelector('#ai-send'),stop=document.querySelector('#ai-stop'),messages=document.querySelector('#ai-messages'),notice=document.querySelector('#ai-notice');
  let controller=null;
  const append=(role,text)=>{const article=document.createElement('article');article.className='ai-message ai-'+role;const name=document.createElement('div');name.className='ai-message-name';name.textContent=role==='user'?'Kamu':'Kilas AI';const body=document.createElement('div');body.className='ai-message-text';body.textContent=text;article.append(name,body);messages.append(article);messages.scrollTop=messages.scrollHeight;return body;};
  const busy=value=>{send.disabled=value;input.disabled=value;mode.disabled=value;stop.hidden=!value;};
  const handle=(type,payload,body)=>{if(type==='delta'){body.textContent+=payload.text||'';messages.scrollTop=messages.scrollHeight;}else if(type==='error'||type==='busy'){notice.textContent=payload.message||'AI sedang tidak tersedia. Coba lagi.';}else if(type==='done'){notice.textContent='';}};
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(controller)return;const content=input.value.trim();if(!content)return;
    controller=new AbortController();busy(true);notice.textContent='Kilas AI sedang menjawab…';input.value='';append('user',content);const answer=append('assistant','');
    const key=crypto.randomUUID().replaceAll('-','');
    try{
      const response=await fetch(`/kilas-ai/threads/${shell.dataset.threadId}/send`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({content,mode:mode.value,operation_key:key}),signal:controller.signal});
      if(!response.ok)throw new Error('request_failed');
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let cut;while((cut=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,cut);buffer=buffer.slice(cut+2);const eventLine=frame.split('\n').find(line=>line.startsWith('event: '));const dataLine=frame.split('\n').find(line=>line.startsWith('data: '));if(eventLine&&dataLine){try{handle(eventLine.slice(7),JSON.parse(dataLine.slice(6)),answer);}catch(_){notice.textContent='Jawaban tidak dapat dibaca. Coba lagi.';}}}}
      if(!answer.textContent)answer.closest('.ai-message').remove();
    }catch(error){notice.textContent=error.name==='AbortError'?'Jawaban dihentikan.':'AI sedang tidak tersedia. Coba lagi.';if(!answer.textContent)answer.closest('.ai-message').remove();}
    finally{controller=null;busy(false);input.focus();}
  });
  stop.addEventListener('click',()=>controller?.abort());
  document.querySelectorAll('.ai-copy').forEach(button=>button.addEventListener('click',async()=>{const text=button.closest('.ai-message').querySelector('.ai-message-text').textContent;await navigator.clipboard.writeText(text);button.textContent='Tersalin';setTimeout(()=>button.textContent='Salin',1500);}));
})();
