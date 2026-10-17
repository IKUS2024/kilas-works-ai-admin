/* Drawer interaction keeps drafts in place; leaving is always explicit. */
(()=>{
  const rail=document.querySelector('[data-chat-sidebar]');if(!rail)return;
  const toggle=rail.querySelector('[data-chat-history-toggle]'),history=rail.querySelector('[data-chat-history-content]');
  if(toggle&&history)toggle.addEventListener('click',()=>{
    const expanded=toggle.getAttribute('aria-expanded')!=='true';
    if(!expanded&&history.contains(document.activeElement))toggle.focus();
    history.hidden=!expanded;toggle.setAttribute('aria-expanded',String(expanded));
  });
  const list=rail.querySelector('.ai-history'),all=rail.querySelector('[data-chat-history-expand]'),more=rail.querySelector('[data-chat-history-more]'),status=rail.querySelector('[data-chat-history-status]');
  if(list&&all&&more&&status){
    const rows=source=>[...source.children].filter(node=>node.matches('a,.ai-sidebar-empty')).map(node=>node.cloneNode(true));
    const address=node=>new URL(node.getAttribute('href'),location.origin).href;
    let recent=rows(list),full=[],cursor=null,loaded=false,cacheValid=true,expanded=false,busy=false,version=0,request=null,scroll=0;
    const initialCurrent=list.querySelector('[aria-current=page]')?.getAttribute('href');
    function markCurrent(){
      const agent=document.querySelector('#agent-chat-form [name=conversation_id]')?.value;
      const thread=document.querySelector('[data-ai-shell]')?.dataset.threadId;
      for(const link of list.querySelectorAll('a')){
        const url=new URL(link.href,location.origin);
        const current=agent?url.pathname==='/kilas-ai/agent'&&url.searchParams.get('conversation')===agent:
          thread?url.pathname==='/kilas-ai/threads/'+thread:link.getAttribute('href')===initialCurrent;
        if(current)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
        link.classList.toggle('is-current',link.classList.contains('ai-history-item')&&current);
      }
    }
    const message=text=>{status.textContent=text;status.hidden=!text;};
    function stop(){version++;request?.abort();request=null;busy=false;list.setAttribute('aria-busy','false');more.disabled=false;}
    function recentView(){
      if(list.contains(document.activeElement))all.focus();
      more.hidden=true;list.replaceChildren(...recent.map(node=>node.cloneNode(true)),more);list.scrollTop=0;markCurrent();message('');
    }
    function savedView(){
      more.hidden=!cursor;more.textContent=all.dataset.more;
      list.replaceChildren(...full.map(node=>node.cloneNode(true)),more);list.scrollTop=scroll;markCurrent();
    }
    function anchor(item){
      if(!item||!Number.isSafeInteger(item.id)||item.id<=0||typeof item.title!=='string'||!['conversation','thread'].includes(item.kind)||typeof item.href!=='string')throw Error('history');
      const url=new URL(item.href,location.origin);
      if(url.origin!==location.origin||(item.kind==='conversation'?(url.pathname!=='/kilas-ai/agent'||url.searchParams.get('conversation')!==String(item.id)):url.pathname!=='/kilas-ai/threads/'+item.id))throw Error('history');
      const node=document.createElement('a');node.href=item.href;node.title=item.title;node.textContent=item.title;node.dataset.chatNavigation='';
      if(item.kind==='thread')node.className='ai-history-item';return node;
    }
    async function load(){
      if(!expanded||busy)return;
      const first=!loaded,id=version,focusMore=document.activeElement===more,controller=new AbortController();request=controller;busy=true;more.disabled=true;let focusNext=null;
      list.setAttribute('aria-busy','true');message(all.dataset.loading);
      const timeout=setTimeout(()=>controller.abort(),10000);
      try{
        const url=new URL(all.dataset.historyUrl,location.origin);if(cursor)url.searchParams.set('cursor',cursor);
        const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if(!response.ok||response.redirected)throw Error('history');
        const data=await response.json();
        if(!Array.isArray(data.items)||data.items.length>20||!(data.next_cursor===null||(typeof data.next_cursor==='string'&&data.next_cursor.length>0&&data.next_cursor.length<=2048)))throw Error('history');
        const incoming=data.items.map(anchor);
        if(!expanded||id!==version)return;
        if(first){list.replaceChildren(more);full=[];loaded=true;}
        const seen=new Set([...list.querySelectorAll('a')].map(node=>node.href));
        const added=[];
        for(const node of incoming)if(!seen.has(node.href)){seen.add(node.href);list.insertBefore(node,more);added.push(node);focusNext=focusNext||node;}
        if(!list.querySelector('a')){const empty=document.createElement('p');empty.className='ai-sidebar-empty';empty.textContent=all.dataset.empty;list.insertBefore(empty,more);added.push(empty);}
        cursor=data.next_cursor;more.hidden=!cursor;more.textContent=all.dataset.more;markCurrent();full.push(...added.map(node=>node.cloneNode(true)));message('');
      }catch(error){
        if(expanded&&id===version){message(all.dataset.error);more.hidden=false;more.textContent=all.dataset.retry;}
      }finally{
        clearTimeout(timeout);
        if(id===version){busy=false;request=null;more.disabled=false;list.setAttribute('aria-busy','false');}
        if(expanded&&id===version&&focusMore&&!history.hidden&&(document.activeElement===more||document.activeElement===document.body))(focusNext||more).focus();
      }
    }
    all.addEventListener('click',()=>{
      if(expanded){scroll=list.scrollTop;stop();expanded=false;all.textContent=all.dataset.seeAll;all.setAttribute('aria-expanded','false');recentView();}
      else{recent=rows(list);expanded=true;all.textContent=all.dataset.seeLess;all.setAttribute('aria-expanded','true');
        if(loaded&&cacheValid)savedView();else{stop();loaded=false;cursor=null;full=[];cacheValid=true;load();}}
    });
    more.addEventListener('click',load);
    window.KilasChatHistory={
      async refreshRecent(){
        try{const response=await fetch(all.dataset.historyUrl,{cache:'no-store',credentials:'same-origin'});if(!response.ok||response.redirected)return;const data=await response.json();if(!Array.isArray(data.items))return;const source=document.createElement('nav');source.append(...data.items.slice(0,12).map(anchor));this.replaceRecent(source);}catch(_){}
      },
      rename(href,title){
        const update=nodes=>{for(const node of nodes)if(node.matches('a')&&address(node)===href){node.textContent=title;node.title=title;}};
        update(recent);update(full);update([...list.children]);cacheValid=false;
      },
      remove(href){
        stop();recent=recent.filter(n=>!n.matches('a')||address(n)!==href);full=full.filter(n=>!n.matches('a')||address(n)!==href);for(const node of list.querySelectorAll('a'))if(node.href===href)node.remove();cacheValid=false;
        if(!list.querySelector('a')){const empty=document.createElement('p');empty.className='ai-sidebar-empty';empty.textContent=all.dataset.empty;list.insertBefore(empty,more);}
      },
      replaceRecent(source){
        recent=rows(source);cacheValid=false;
        if(!expanded)recentView();else{
          const top=list.getBoundingClientRect().top,visible=[...list.querySelectorAll('a')].find(n=>n.getBoundingClientRect().bottom>top),offset=visible?visible.getBoundingClientRect().top-top:0;
          for(const incoming of [...recent].reverse())if(incoming.matches('a')){const node=[...list.querySelectorAll('a')].find(n=>n.href===address(incoming))||incoming.cloneNode(true);node.textContent=incoming.textContent;node.title=incoming.title;list.prepend(node);}
          full=rows(list);if(visible?.isConnected)list.scrollTop+=visible.getBoundingClientRect().top-top-offset;
          markCurrent();
        }
      },
      upsert(link){
        if(!expanded)recent=rows(list);else{
          const old=recent.findIndex(node=>node.matches('a')&&address(node)===link.href);
          if(old>=0)recent[old]=link.cloneNode(true);else recent.unshift(link.cloneNode(true));
          recent=recent.filter(node=>!node.matches('.ai-sidebar-empty'));cacheValid=false;
        }
      }
    };
  }
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
  document.addEventListener('kilas:conversation-deleted',()=>{leaving=true;});
  window.addEventListener('pageshow',()=>{leaving=false;carrying=false;});
})();
