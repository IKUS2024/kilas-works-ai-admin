/* Drawer interaction keeps drafts in place; leaving is always explicit. */
(()=>{
  const rail=document.querySelector('[data-chat-sidebar]');if(!rail)return;
  const sidebar=rail.closest('#premium-sidebar');let leaving=false,carrying=false;
  const t=message=>window.KilasUI?window.KilasUI.t(message):message;
  function chatDirty(){
    const input=document.querySelector('#ai-input,#agent-message');
    if(input?.value.trim()||document.querySelector('#ai-pending,#work-pending-files')?.children.length)return true;
    if(document.querySelector('#ai-stop,[data-unified-stop]')?.hidden===false)return true;
    return false;
  }
  function dirty(){
    return chatDirty()||Boolean(document.querySelector('#audio-script')?.value.trim());
  }
  function allow(event){
    if(dirty()&&!window.confirm(t('Draf atau lampiran belum dikirim. Tinggalkan halaman ini?'))){event.preventDefault();event.stopImmediatePropagation();return;}
    leaving=true;
  }
  document.addEventListener('click',event=>{
    if(event.defaultPrevented)return;
    const link=event.target.closest('a');
    const href=link?.getAttribute('href');
    if(link&&href&&!href.startsWith('#')&&/^https?:$/.test(link.protocol)&&sidebar.contains(link)&&link.target!=='_blank'&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0)allow(event);
    // Existing task handoff carries the brief to its native form.
    if(event.target.closest('[data-home-task],[data-kilas-feature]')){carrying=true;setTimeout(()=>carrying=false,0);}
  },true);
  document.addEventListener('submit',event=>{if(sidebar.contains(event.target))allow(event);else{carrying=true;setTimeout(()=>carrying=false,0);}},true);
  // Voice Over has an asynchronous Generate -> result redirect. Only chat gets
  // the unload guard; explicit sidebar navigation still protects its script.
  window.addEventListener('beforeunload',event=>{if(!leaving&&!carrying&&chatDirty()){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pageshow',()=>{leaving=false;carrying=false;});
})();
