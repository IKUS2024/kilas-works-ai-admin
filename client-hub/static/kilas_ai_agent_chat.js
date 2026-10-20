/* Chat owns only conversation UI. Tasks continue independently on the existing runner. */
(() => {
  const t=(message, values)=>window.KilasUI ? window.KilasUI.t(message, values) : message;
  function refreshCounts(doc) {
    const history=doc.querySelector('[data-chat-sidebar] .ai-history');if(history)window.KilasChatHistory?.replaceRecent(history);
    for (const selector of ['[data-active-count]','[data-notification-count]']) {
      const incoming=doc.querySelector(selector), current=document.querySelector(selector);
      if(incoming && current) current.textContent=incoming.textContent;
    }
  }
  document.addEventListener('submit', event => {
    if (event.target.matches('[data-confirm-delete]') && !window.confirm(t('Hapus tugas ini? Riwayat hasilnya tetap tersimpan.'))) event.preventDefault();
  });
  window.KilasMarkdown.hydrate();
  const form = document.querySelector('#agent-chat-form');
  if (!form) {
    if (document.querySelector('[data-work-detail-updates]')) {
      let updating=false;
      const updateDetail=async (force=false) => {
        if(document.hidden || updating || (!force && !document.querySelector('[data-work-detail-updates][data-live="true"]'))) return;
        updating=true;
        try {
          const response=await fetch(location.href,{cache:'no-store'});
          if(!response.ok) return;
          const doc=new DOMParser().parseFromString(await response.text(),'text/html');
          refreshCounts(doc);
          const current=doc.querySelector('[data-work-detail-updates]');
          if(current) {document.querySelector('[data-work-detail-updates]').replaceWith(current);window.KilasMarkdown.hydrate(current);}
        } catch (_) { /* Retain persisted progress and untouched feedback input. */ }
        finally {updating=false;}
      };
      setInterval(updateDetail,3000);
      document.addEventListener('visibilitychange',()=>{if(!document.hidden) updateDetail(true);});
      window.addEventListener('focus',()=>updateDetail(true));
    }
    // The account-wide view uses the same bounded, read-only task cards.
    const tasks = document.querySelector('[data-task-cards]');
    if (tasks) {
      const update = async (force=false) => {
        if (document.hidden || (!force && !document.querySelector('[data-live="true"]'))) return;
        try {
          const response = await fetch('/kilas-ai/agent?view=tasks', {cache:'no-store'});
          if (!response.ok) return;
          const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
          refreshCounts(doc);
          const current = doc.querySelector('[data-task-cards]');
          if (current) document.querySelector('[data-task-cards]')?.replaceWith(current);
        } catch (_) { /* Retain the last verified state. */ }
      };
      setInterval(update, 3000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) update(true); });
      window.addEventListener('focus', () => update(true));
    }
    return;
  }
  const input = form.querySelector('textarea');
  const send = form.querySelector('button[type="submit"]');
  const chat = document.querySelector('#agent-conversation');
  const thinking = document.querySelector('#agent-thinking');
  const error = document.querySelector('#agent-chat-error');
  const copyIcon=document.querySelector('#ai-copy-icon');
  function copyButton(article){
    if(!copyIcon||article.querySelector('.ai-copy'))return;
    const button=document.createElement('button');button.type='button';button.className='ai-copy';
    const state=copied=>{button.replaceChildren(copyIcon.content.cloneNode(true));button.setAttribute('aria-label',t(copied?'Tersalin':'Salin'));button.title=t(copied?'Tersalin':'Salin');if(copied)button.querySelector('path').setAttribute('d','m5 12 4 4L19 6');};state(false);
    button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(window.KilasMarkdown.source(article.querySelector('.agent-message-text')));state(true);setTimeout(()=>state(false),1500);}catch(_){error.textContent=t('Tidak dapat menyalin. Pilih teks lalu salin.');error.hidden=false;}});article.append(button);
  }
  const copyAnswers=()=>chat.querySelectorAll('.agent-message-assistant').forEach(copyButton);copyAnswers();
  let busy = false;
  let controller;
  let activeStream=null,lastEvent=0;
  const stop=form.querySelector('[data-unified-stop]');
  stop?.addEventListener('click',async()=>{
    if(activeStream){try{await fetch(`/kilas-ai/work/streams/${activeStream}/cancel`,{method:'POST',headers:{'X-CSRF-Token':form.elements.csrf_token.value,'Content-Type':'application/json'},body:'{}'});}catch(_){} }
    controller?.abort();
  });
  const canAutoFocus = () => Boolean(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
  function message(role, text) {
    const article = document.createElement('article');
    article.className = `agent-message agent-message-${role}`;
    const speaker = document.createElement('div'); speaker.className = 'agent-speaker';
    speaker.textContent = role === 'user' ? t('Kamu') : t('Kilas');
    const content = document.createElement('div'); content.className = 'agent-message-text'; content.textContent = text;
    article.append(speaker, content); if(role==='assistant')content.addEventListener('kilas:rendered',()=>{chat.scrollTop=chat.scrollHeight;});chat.append(article);
    chat.scrollTop = chat.scrollHeight;
    return content;
  }
  async function refresh() {
    const id = form.elements.conversation_id.value;
    const response = await fetch(`/kilas-ai/agent?conversation=${encodeURIComponent(id)}`, {cache:'no-store'});
    if (!response.ok || !response.url.includes('/kilas-ai/agent')) throw new Error('refresh');
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    refreshCounts(doc);
    const current = doc.querySelector('#agent-conversation');
    if (!current) throw new Error('refresh');
    chat.replaceChildren(...current.childNodes);
    window.KilasAttachmentPreview?.clear();
    window.KilasMarkdown.hydrate(chat);copyAnswers();
    const chats = doc.querySelector('.agent-chats');
    if (chats) document.querySelector('.agent-chats')?.replaceChildren(...chats.childNodes);
    const heading = doc.querySelector('.agent-section-head h2');
    if (heading) document.querySelector('.agent-section-head h2')?.replaceChildren(document.createTextNode(heading.textContent));
    const permission=doc.querySelector('.work-context-permission');
    const currentPermission=form.querySelector('.work-context-permission');
    if(permission) { if(currentPermission) currentPermission.replaceWith(permission);else form.prepend(permission); }
    else currentPermission?.remove();
    chat.scrollTop = chat.scrollHeight;
  }
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); if (!busy) form.requestSubmit();
    }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !input.value.trim()) return;
    const draft=input.value;
    const data = new FormData(form);
    if (!canAutoFocus()) input.blur();
    busy = true;document.dispatchEvent(new Event('kilas:request-started')); send.disabled = true; input.readOnly = true;
    controller=new AbortController();if(stop) stop.hidden=false;
    error.hidden = true; chat.querySelector('.agent-welcome')?.remove();
    const userMessage=message('user', input.value.trim());
    const selected=data.getAll('source_files').filter(file=>file instanceof File && file.name);
    if(selected.length && window.KilasAttachmentPreview) userMessage.parentElement.append(window.KilasAttachmentPreview(selected));
    thinking.hidden = false;
    thinking.lastElementChild.textContent = t('Berpikir…');
    chat.setAttribute('aria-busy', 'true');
    let accepted = false, draftCleared = false, answer;
    try {
      const response = await fetch(form.action, {method:'POST',body:data,headers:{'X-Agent-Chat':'1','X-Workspace-Stream':'1'},signal:controller.signal});
      if (!response.ok) {
        const failure=new Error('request');
        try { const payload=await response.json(); if(typeof payload.error==='string') failure.publicMessage=payload.error; } catch (_) { /* Preserve a safe fallback. */ }
        throw failure;
      }
      accepted = true;
      if(selected.length)form.dispatchEvent(new Event('work:accepted'));
      if(input.value===draft){input.value='';draftCleared=true;input.dispatchEvent(new Event('input'));}
      if (response.headers.get('content-type')?.includes('text/event-stream')) {
        activeStream=response.headers.get('X-Workspace-Stream');lastEvent=0;
        let streamResponse=response,reconnections=0;
        const decoder = new TextDecoder();
        let pending = '', complete = false;
        while(!complete){
        const reader=streamResponse.body.getReader();
        while (true) {
          const {value,done} = await reader.read();
          pending += decoder.decode(value || new Uint8Array(), {stream: !done});
          let end;
          while ((end = pending.indexOf('\n\n')) >= 0) {
            const block = pending.slice(0,end); pending = pending.slice(end+2);
            const lines=block.split('\n'),payload=lines.find(line=>line.startsWith('data: '));
            const eventId=lines.find(line=>line.startsWith('id: '));if(eventId)lastEvent=Number(eventId.slice(4));
            if(!payload)continue;
            const update = JSON.parse(payload.slice(6));
            if (update.type === 'delta') {
              answer ||= message('assistant', ''); window.KilasMarkdown.stream(answer,update.text);
              chat.scrollTop = chat.scrollHeight;
            } else if (update.type === 'model_metadata') { answer ||= message('assistant','');window.KilasChatModels?.badge(answer,update); } else if (update.type === 'activity') thinking.lastElementChild.textContent = t(update.label);
            else if (update.type === 'reset') { if(answer) window.KilasMarkdown.render(answer,''); }
            else if (update.type === 'error') throw new Error('provider');
            else if (update.type === 'done') { complete = true; if (answer) { answer.classList.add('ai-markdown'); window.KilasMarkdown.finish(answer); } }
          }
          if (done) break;
        }
        if(complete)break;
        if(!activeStream||++reconnections>16)throw Error('interrupted');
        pending='';streamResponse=await fetch(`/kilas-ai/work/streams/${activeStream}?after=${lastEvent}`,{cache:'no-store',signal:controller.signal});
        if(!streamResponse.ok)throw Error('reconnect');
        }
        if (!complete || !answer?.textContent.trim()) throw new Error('interrupted');
      }
      await refresh();
      form.dispatchEvent(new Event('work:accepted'));
      startDue();
      const sources=form.querySelector('#work-source-files'); if(sources) sources.value='';
      form.elements.operation_key.value = Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
    } catch (failure) {
      if(answer)window.KilasMarkdown.finish(answer);
      if(draftCleared&&!input.value&&!(accepted&&selected.length)){input.value=draft;input.dispatchEvent(new Event('input'));}
      error.textContent = failure.publicMessage || t('Jawaban belum dapat dipastikan. Buka kembali chat untuk melihat pesan yang sudah diterima sebelum mencoba lagi.');
      error.hidden = false;
      // Same key is retained after an uncertain outcome: retry cannot create duplicate work.
      if(!accepted){const group=userMessage.parentElement.querySelector('.chat-user-attachments');if(group)window.KilasChatAttachments?.release(group);userMessage.closest('.agent-message').remove();}
      if (accepted) { try { await refresh(); } catch (_) { /* Keep visible local messages. */ } }
    } finally {
      document.dispatchEvent(new Event('kilas:request-finished'));
      if(stop) stop.hidden=true;controller=null;activeStream=null;
      busy = false; send.disabled = false; input.readOnly = false;
      thinking.hidden = true; chat.removeAttribute('aria-busy');
      if (canAutoFocus()) input.focus({preventScroll:true});
      else input.blur();
    }
  });
  // Read-only refresh of task cards; no new planner/model request and no hidden-tab polling.
  let polling=false;
  async function refreshTasks(force=false) {
    if (document.hidden || busy || (!force && !chat.querySelector('[data-live="true"]'))) return;
    if (polling) return;
    polling=true;
    const position = chat.scrollTop;
    try {
      const query = new URLSearchParams(window.location.search);
      query.set('conversation',form.elements.conversation_id.value);
      const response = await fetch(`/kilas-ai/agent?${query}`, {cache:'no-store'});
      if (!response.ok) return;
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      refreshCounts(doc);
      // Preserve each result's position in the durable message timeline.
      const incoming=doc.querySelector('#agent-conversation');
      if(incoming && incoming.querySelectorAll('.agent-message').length!==chat.querySelectorAll('.agent-message').length) {
        chat.replaceChildren(...incoming.childNodes);window.KilasMarkdown.hydrate(chat);copyAnswers();
      } else if(incoming) {
        for(const card of incoming.querySelectorAll('[data-job-id]')) {
          const previous=chat.querySelector(`[data-job-id="${card.dataset.jobId}"]`);
          if(previous && previous.outerHTML!==card.outerHTML) previous.replaceWith(card);
        }
      }
      chat.scrollTop = position;
    } catch (_) { /* Existing progress stays visible until the next read. */ }
    finally {polling=false;if(!starting)startDue();}
  }
  let starting=false;
  async function startDue() {
    if(starting || document.hidden) return;
    const job=chat.querySelector('[data-due="true"]');
    if(!job) return;
    starting=true;
    try {
      // Bounded, persisted owner-scoped execution; cron remains the recovery path.
      for(let pass=0;pass<3;pass++) {
        const response=await fetch(`/kilas-ai/work/jobs/${job.dataset.jobId}/start`,{method:'POST',headers:{'X-CSRF-Token':form.elements.csrf_token.value,'Content-Type':'application/json','X-Workspace-Async':'1'},body:'{}'});
        if(!response.ok) break;
        const result=await response.json();if(!result.started) break;
        await refreshTasks();
        if(!chat.querySelector(`[data-job-id="${job.dataset.jobId}"][data-due="true"]`)) break;
      }
    } catch (_) { /* Persisted jobs continue through the existing cron. */ }
    finally {starting=false;}
  }
  startDue();
  // Refresh reattaches to the existing stream; this GET never dispatches inference.
  async function resumeStream(){
    if(busy)return;
    try{
      const response=await fetch(`/kilas-ai/work/streams?conversation_id=${encodeURIComponent(form.elements.conversation_id.value)}`,{cache:'no-store'});
      if(!response.ok)return;const result=await response.json();if(!result.streams.length)return;
      activeStream=result.streams[0].id;busy=true;send.disabled=true;input.readOnly=true;controller=new AbortController();if(stop)stop.hidden=false;
      thinking.hidden=false;thinking.lastElementChild.textContent=t('Berpikir…');chat.setAttribute('aria-busy','true');
      document.dispatchEvent(new Event('kilas:request-started'));
      let after=0,complete=false,answer,pending='';const decoder=new TextDecoder();
      for(let attempt=0;attempt<16&&!complete;attempt++){
        const stream=await fetch(`/kilas-ai/work/streams/${activeStream}?after=${after}`,{cache:'no-store',signal:controller.signal});if(!stream.ok)throw Error('reattach');
        const reader=stream.body.getReader();
        while(true){
          const part=await reader.read();pending+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});let end;
          while((end=pending.indexOf('\n\n'))>=0){const block=pending.slice(0,end);pending=pending.slice(end+2);const lines=block.split('\n'),id=lines.find(s=>s.startsWith('id: ')),data=lines.find(s=>s.startsWith('data: '));if(id)after=Number(id.slice(4));if(!data)continue;const item=JSON.parse(data.slice(6));
            if(item.type==='delta'){answer||=message('assistant','');window.KilasMarkdown.stream(answer,item.text);}
            else if(item.type==='reset'&&answer)window.KilasMarkdown.render(answer,'');
            else if(item.type==='activity')thinking.lastElementChild.textContent=t(item.label);
            else if(item.type==='model_metadata'){answer||=message('assistant','');window.KilasChatModels?.badge(answer,item);}
            else if(item.type==='error'){error.textContent=t(item.message);error.hidden=false;}
            else if(item.type==='done')complete=true;
          }if(part.done)break;
        }
      }
      if(answer)window.KilasMarkdown.finish(answer);await refresh();
    }catch(_){error.textContent=t('Jawaban terhenti. Buka riwayat; permintaan tidak diulang otomatis.');error.hidden=false;}
    finally{if(activeStream){busy=false;send.disabled=false;input.readOnly=false;thinking.hidden=true;chat.removeAttribute('aria-busy');if(stop)stop.hidden=true;activeStream=null;controller=null;document.dispatchEvent(new Event('kilas:request-finished'));}}
  }
  resumeStream();
  setInterval(refreshTasks, 3000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshTasks(true); });
  window.addEventListener('focus', () => refreshTasks(true));
})();
