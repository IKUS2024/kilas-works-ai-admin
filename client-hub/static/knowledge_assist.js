(() => {
  'use strict';
  const page = document.querySelector('.knowledge-page[data-assist-url]');
  if (!page) return;
  const form = page.querySelector('form');
  const fields = {
    business: ['short_description', 'address', 'operating_hours', 'business_phone'],
    services: ['name', 'description', 'pricing', 'inclusions', 'duration', 'notes'],
    faqs: ['question', 'answer', 'category'],
    communication: ['tone', 'primary_language', 'customer_salutation']
  };
  const drafts = {...fields, business: ['short_description']};
  const labels = {short_description:'Deskripsi bisnis',name:'Nama',description:'Deskripsi',pricing:'Harga / ketentuan',
    inclusions:'Yang didapat customer',duration:'Proses / durasi',notes:'Catatan',question:'Pertanyaan',answer:'Jawaban',
    category:'Topik',tone:'Gaya bicara',primary_language:'Bahasa',customer_salutation:'Sapaan'};
  const element = (tag, text) => { const el = document.createElement(tag); el.textContent = text; return el; };
  page.addEventListener('click', event => {
    const trigger = event.target.closest('[data-assist-scope]');
    if (!trigger || trigger.disabled) return;
    const scope = trigger.dataset.assistScope;
    if (!fields[scope]) return;
    const target = trigger.closest('fieldset') || trigger.closest('section');
    if (target.querySelector('.knowledge-assist-panel')) return;
    const panel = element('div', ''); panel.className = 'knowledge-assist-panel';
    panel.setAttribute('aria-live', 'polite');
    target.appendChild(panel);
    const control = key => target.querySelector(`[name="${scope === 'services' || scope === 'faqs' ? scope + '_' : ''}${key}"]`);
    let controller, closed = false;
    function cancel() { closed = true; if (controller) controller.abort(); trigger.disabled = false; panel.remove(); }
    function button(text, action) { const b = element('button', text); b.type = 'button'; b.className = 'btn secondary'; b.addEventListener('click', action); return b; }
    async function run(clarifications = '') {
      trigger.disabled = true; panel.replaceChildren(element('p', 'Menyiapkan draft…'), button('Batal', cancel));
      panel.setAttribute('aria-busy', 'true');
      const current = Object.fromEntries(fields[scope].map(key => [key, control(key)?.value || '']));
      const context = {category: (form.elements.namedItem('category')?.value || '').slice(0,160)};
      if (scope !== 'business') context.short_description = (form.elements.namedItem('short_description')?.value || '').slice(0,400);
      const payloadFields = {...current};
      if (scope === 'services' || scope === 'faqs') payloadFields.raw = target.querySelector('.knowledge-old')?.textContent || '';
      controller = new AbortController();
      try {
        const response = await fetch(page.dataset.assistUrl, {method:'POST', credentials:'same-origin', signal:controller.signal,
          headers:{'Content-Type':'application/json','X-CSRF-Token':form.elements.namedItem('csrf_token').value},
          body:JSON.stringify({scope, context, fields:payloadFields, clarifications})});
        const data = await response.json();
        if (closed) return;
        if (!response.ok) throw new Error(data.error || 'Bantuan AI belum tersedia. Coba lagi sebentar.');
        if (!data.draft_fields || !Array.isArray(data.questions) || !Array.isArray(data.warnings)) throw new Error('Draft belum dapat ditampilkan. Coba lagi.');
        panel.replaceChildren(element('strong','Draft AI — belum tersimpan'));
        for (const key of drafts[scope]) {
          if (typeof data.draft_fields[key] === 'string') {
            panel.append(element('p',labels[key]),element('pre',data.draft_fields[key]));
          }
        }
        data.warnings.forEach(warning => panel.append(element('p', warning)));
        const answers = [];
        if (data.questions.length) {
          panel.append(element('p','Informasi yang perlu kamu jelaskan:'));
          data.questions.slice(0,3).forEach(question => {
            const label = element('label',question), input = document.createElement('textarea');
            input.rows = 2; input.maxLength = 600; label.append(input); panel.append(label); answers.push({question,input});
          });
          panel.append(button('Bantu lagi', () => {
            const added = answers.map(({question,input}) => input.value.trim() ? question + '\nJawaban: ' + input.value.trim() : '').filter(Boolean).join('\n');
            if (!added) { answers[0].input.focus(); return; }
            const combined = [clarifications, added].filter(Boolean).join('\n');
            if (combined.length > 1000) { panel.append(element('p','Ringkas jawaban tambahan hingga 1.000 karakter.')); return; }
            run(combined);
          }));
        }
        if (Object.keys(data.draft_fields).length) panel.append(button('Terapkan ke form', () => {
          if (fields[scope].some(key => (control(key)?.value || '') !== current[key])) {
            panel.append(element('p','Isian kartu sudah berubah. Batalkan draft ini dan minta bantuan lagi agar perubahanmu tetap aman.')); return;
          }
          for (const key of drafts[scope]) {
            if (typeof data.draft_fields[key] === 'string' && control(key)) control(key).value = data.draft_fields[key];
          }
          panel.replaceChildren(element('p','Draft diterapkan ke form, belum tersimpan. Periksa lalu tekan “Simpan pengetahuan bisnis”.'),button('Tutup',cancel));
        }));
        panel.append(button('Batal', cancel));
      } catch (error) {
        if (!closed) panel.replaceChildren(element('p',error.name === 'AbortError' ? 'Permintaan dibatalkan.' :
          (error instanceof SyntaxError || error instanceof TypeError ? 'Bantuan AI belum tersedia. Isianmu tetap aman.' : error.message)),button('Tutup',cancel));
      } finally { panel.removeAttribute('aria-busy'); if (!closed) trigger.disabled = false; }
    }
    run(); // Only reached by an explicit scoped button click.
  });
})();
