/* Chat owns only conversation UI. Tasks continue independently on the existing runner. */
(() => {
  const form = document.querySelector('#agent-chat-form');
  const menu = document.querySelector('.agent-menu-button');
  const sidebar = document.querySelector('#agent-sidebar');
  const backdrop = document.querySelector('.agent-drawer-backdrop');
  const close = document.querySelector('.agent-drawer-close');
  function drawer(open) {
    menu?.setAttribute('aria-expanded', String(open));
    sidebar?.classList.toggle('is-open', open);
    if (backdrop) backdrop.hidden = !open;
    if (open) close?.focus(); else menu?.focus();
  }
  menu?.addEventListener('click', () => drawer(true));
  close?.addEventListener('click', () => drawer(false));
  backdrop?.addEventListener('click', () => drawer(false));
  document.addEventListener('keydown', event => {
    if (menu?.getAttribute('aria-expanded') !== 'true') return;
    if (event.key === 'Escape') drawer(false);
    if (event.key === 'Tab') {
      const items = [...sidebar.querySelectorAll('a,button,input')].filter(item => item.getClientRects().length);
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
    }
  });
  if (!form) {
    // The account-wide view uses the same bounded, read-only task cards.
    const tasks = document.querySelector('[data-task-cards]');
    if (tasks) {
      const update = async () => {
        if (document.hidden) return;
        try {
          const response = await fetch('/kilas-ai/agent?view=tasks', {cache:'no-store'});
          if (!response.ok) return;
          const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
          const current = doc.querySelector('[data-task-cards]');
          if (current) document.querySelector('[data-task-cards]')?.replaceWith(current);
        } catch (_) { /* Retain the last verified state. */ }
      };
      setInterval(update, 10000);
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
  function message(role, text) {
    const article = document.createElement('article');
    article.className = `agent-message agent-message-${role}`;
    const speaker = document.createElement('div'); speaker.className = 'agent-speaker';
    speaker.textContent = role === 'user' ? 'Kamu' : 'Kilas';
    const content = document.createElement('p'); content.textContent = text;
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
    const chats = doc.querySelector('.agent-chats');
    if (chats) document.querySelector('.agent-chats')?.replaceChildren(...chats.childNodes);
    const heading = doc.querySelector('.agent-section-head h2');
    if (heading) document.querySelector('.agent-section-head h2').textContent = heading.textContent;
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
    busy = true; send.disabled = true; input.readOnly = true;
    error.hidden = true; chat.querySelector('.agent-welcome')?.remove();
    message('user', input.value.trim());
    thinking.hidden = false;
    thinking.lastElementChild.textContent = /\b(riset|research)\b/i.test(input.value) ? 'Mencari informasi…' : /\b(kerjain|kerjakan|pantau|perbaiki|setiap|besok)\b/i.test(input.value) ? 'Menyiapkan pekerjaan…' : 'Thinking…';
    chat.setAttribute('aria-busy', 'true');
    let accepted = false;
    try {
      const response = await fetch(form.action, {method:'POST',body:data,headers:{'X-Agent-Chat':'1'}});
      if (!response.ok) throw new Error('request');
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
            else if (update.type === 'done') complete = true;
          }
          if (done) break;
        }
        if (!complete) throw new Error('interrupted');
      }
      await refresh(); input.value = '';
      form.elements.operation_key.value = crypto.randomUUID();
    } catch (_) {
      error.textContent = 'Jawaban belum dapat dipastikan. Buka kembali chat untuk melihat pesan yang sudah diterima sebelum mencoba lagi.';
      error.hidden = false;
      // Same key is retained after an uncertain outcome: retry cannot create duplicate work.
      if (accepted) { try { await refresh(); } catch (_) { /* Keep visible local messages. */ } }
    } finally {
      busy = false; send.disabled = false; input.readOnly = false;
      thinking.hidden = true; chat.removeAttribute('aria-busy');
      input.focus({preventScroll:true});
    }
  });
  // Read-only refresh of task cards; no new planner/model request and no hidden-tab polling.
  async function refreshTasks() {
    if (document.hidden || busy || !chat.querySelector('[data-job-id]')) return;
    const position = chat.scrollTop;
    try {
      const response = await fetch(`/kilas-ai/agent?conversation=${encodeURIComponent(form.elements.conversation_id.value)}`, {cache:'no-store'});
      if (!response.ok) return;
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const cards = doc.querySelector('[data-task-cards]');
      if (cards) chat.querySelector('[data-task-cards]')?.replaceWith(cards);
      chat.scrollTop = position;
    } catch (_) { /* Existing progress stays visible until the next read. */ }
  }
  setInterval(refreshTasks, 10000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshTasks(); });
  window.addEventListener('focus', refreshTasks);
})();
