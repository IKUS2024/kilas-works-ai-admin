/* Chat owns only conversation UI. Tasks continue independently on the existing runner. */
(() => {
  document.addEventListener('submit', event => {
    if (event.target.matches('[data-confirm-delete]') && !window.confirm('Hapus tugas ini? Riwayat hasilnya tetap tersimpan.')) event.preventDefault();
  });
  window.KilasMarkdown.hydrate();
  const form = document.querySelector('#agent-chat-form');
  if (!form) {
    // The account-wide view uses the same bounded, read-only task cards.
    const tasks = document.querySelector('[data-task-cards]');
    if (tasks) {
      const update = async () => {
        if (document.hidden || !document.querySelector('[data-live="true"]')) return;
        try {
          const response = await fetch('/kilas-ai/agent?view=tasks', {cache:'no-store'});
          if (!response.ok) return;
          const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
          const current = doc.querySelector('[data-task-cards]');
          if (current) document.querySelector('[data-task-cards]')?.replaceWith(current);
        } catch (_) { /* Retain the last verified state. */ }
      };
      setInterval(update, 3000);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) update(); });
      window.addEventListener('focus', update);
    }
    return;
  }
  const input = form.querySelector('textarea');
  const send = form.querySelector('button[type="submit"]');
  const chat = document.querySelector('#agent-conversation');
  const thinking = document.querySelector('#agent-thinking');
  const error = document.querySelector('#agent-chat-error');
  let busy = false;
  const canAutoFocus = () => Boolean(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
  function message(role, text) {
    const article = document.createElement('article');
    article.className = `agent-message agent-message-${role}`;
    const speaker = document.createElement('div'); speaker.className = 'agent-speaker';
    speaker.textContent = role === 'user' ? 'Kamu' : 'Kilas';
    const content = document.createElement('div'); content.className = 'agent-message-text'; content.textContent = text;
    article.append(speaker, content); chat.append(article);
    chat.scrollTop = chat.scrollHeight;
    return content;
  }
  async function refresh() {
    const id = form.elements.conversation_id.value;
    const response = await fetch(`/kilas-ai/agent?conversation=${encodeURIComponent(id)}`, {cache:'no-store'});
    if (!response.ok || !response.url.includes('/kilas-ai/agent')) throw new Error('refresh');
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    const current = doc.querySelector('#agent-conversation');
    if (!current) throw new Error('refresh');
    chat.replaceChildren(...current.childNodes);
    window.KilasMarkdown.hydrate(chat);
    const chats = doc.querySelector('.agent-chats');
    if (chats) document.querySelector('.agent-chats')?.replaceChildren(...chats.childNodes);
    const heading = doc.querySelector('.agent-section-head h2');
    if (heading) document.querySelector('.agent-section-head h2').textContent = heading.textContent;
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
    const data = new FormData(form);
    if (!canAutoFocus()) input.blur();
    busy = true; send.disabled = true; input.readOnly = true;
    error.hidden = true; chat.querySelector('.agent-welcome')?.remove();
    message('user', input.value.trim());
    thinking.hidden = false;
    thinking.lastElementChild.textContent = /\b(riset|research)\b/i.test(input.value) ? 'Menyiapkan riset…' : /\b(kerjain|kerjakan|pantau|perbaiki|setiap|besok)\b/i.test(input.value) ? 'Menyiapkan pekerjaan…' : 'Menyiapkan jawaban…';
    chat.setAttribute('aria-busy', 'true');
    let accepted = false;
    try {
      const response = await fetch(form.action, {method:'POST',body:data,headers:{'X-Agent-Chat':'1'}});
      if (!response.ok) {
        const failure=new Error('request');
        try { const payload=await response.json(); if(typeof payload.error==='string') failure.publicMessage=payload.error; } catch (_) { /* Preserve a safe fallback. */ }
        throw failure;
      }
      accepted = true;
      if (response.headers.get('content-type')?.includes('text/event-stream')) {
        const reader = response.body.getReader(), decoder = new TextDecoder();
        let pending = '', answer, complete = false;
        while (true) {
          const {value,done} = await reader.read();
          pending += decoder.decode(value || new Uint8Array(), {stream: !done});
          let end;
          while ((end = pending.indexOf('\n\n')) >= 0) {
            const block = pending.slice(0,end); pending = pending.slice(end+2);
            if (!block.startsWith('data: ')) continue;
            const update = JSON.parse(block.slice(6));
            if (update.type === 'delta') {
              answer ||= message('assistant', ''); answer.textContent += update.text;
              chat.scrollTop = chat.scrollHeight;
            } else if (update.type === 'activity') thinking.lastElementChild.textContent = update.label;
            else if (update.type === 'error') throw new Error('provider');
            else if (update.type === 'done') { complete = true; if (answer) { answer.classList.add('ai-markdown'); window.KilasMarkdown.render(answer,answer.textContent); } }
          }
          if (done) break;
        }
        if (!complete) throw new Error('interrupted');
      }
      await refresh(); input.value = '';
      form.dispatchEvent(new Event('work:accepted'));
      startDue();
      const sources=form.querySelector('#work-source-files'); if(sources) sources.value='';
      form.elements.operation_key.value = crypto.randomUUID();
    } catch (failure) {
      error.textContent = failure.publicMessage || 'Jawaban belum dapat dipastikan. Buka kembali chat untuk melihat pesan yang sudah diterima sebelum mencoba lagi.';
      error.hidden = false;
      // Same key is retained after an uncertain outcome: retry cannot create duplicate work.
      if (accepted) { try { await refresh(); } catch (_) { /* Keep visible local messages. */ } }
    } finally {
      busy = false; send.disabled = false; input.readOnly = false;
      thinking.hidden = true; chat.removeAttribute('aria-busy');
      if (canAutoFocus()) input.focus({preventScroll:true});
      else input.blur();
    }
  });
  // Read-only refresh of task cards; no new planner/model request and no hidden-tab polling.
  let polling=false;
  async function refreshTasks() {
    if (document.hidden || busy || !chat.querySelector('[data-live="true"]')) return;
    if (polling) return;
    polling=true;
    const position = chat.scrollTop;
    try {
      const response = await fetch(`/kilas-ai/agent?conversation=${encodeURIComponent(form.elements.conversation_id.value)}`, {cache:'no-store'});
      if (!response.ok) return;
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const cards = doc.querySelector('[data-task-cards]');
      if (cards) chat.querySelector('[data-task-cards]')?.replaceWith(cards);
      const active=doc.querySelector('[data-active-count]');
      if(active) document.querySelector('[data-active-count]').textContent=active.textContent;
      // Reminder/clarification messages arrive through the same durable conversation.
      const incoming=doc.querySelector('#agent-conversation');
      if(incoming && incoming.querySelectorAll('.agent-message').length!==chat.querySelectorAll('.agent-message').length) {chat.replaceChildren(...incoming.childNodes);window.KilasMarkdown.hydrate(chat);}
      chat.scrollTop = position;
    } catch (_) { /* Existing progress stays visible until the next read. */ }
    finally {polling=false;}
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
        const response=await fetch(`/kilas-ai/work/jobs/${job.dataset.jobId}/start`,{method:'POST',headers:{'X-CSRF-Token':form.elements.csrf_token.value,'Content-Type':'application/json'},body:'{}'});
        if(!response.ok) break;
        const result=await response.json();if(!result.started) break;
        await refreshTasks();
        if(!chat.querySelector(`[data-job-id="${job.dataset.jobId}"][data-due="true"]`)) break;
      }
    } catch (_) { /* Persisted jobs continue through the existing cron. */ }
    finally {starting=false;}
  }
  startDue();
  setInterval(refreshTasks, 3000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshTasks(); });
  window.addEventListener('focus', refreshTasks);
})();
