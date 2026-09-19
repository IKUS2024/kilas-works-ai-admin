'use strict';
(() => {
  const el = id => document.getElementById(id);
  const composer = el('assistant-composer');
  if (!composer) return;
  const files = el('assistant-files'), mode = el('assistant-mode'), text = el('assistant-text');
  const status = el('assistant-status');
  let busy = false, proposed = null;
  const workflows = new Set(['READ_ONLY_ANALYSIS','TEXT_OPERATOR','RECEIPT','BANK_STATEMENT','HANDWRITTEN_NOTE','RECURRING_DRAFT','NEEDS_CLARIFICATION','UNSUPPORTED']);
  const activeDraft = () => el('operator-fields')?.disabled || (el('op-preview') && !el('op-preview').hidden)
    || el('recurring-fields')?.disabled || (el('rec-preview') && !el('rec-preview').hidden);
  const receiptReady = () => mode.value === 'receipt' && files.files.length === 1;
  const buttonLabel = () => { el('assistant-send').textContent = busy ? 'Memproses…' : receiptReady() ? 'Baca Struk' : 'Lanjut'; };
  const state = value => {
    busy = value;
    buttonLabel();
    composer.setAttribute('aria-busy', String(value));
    if (el('assistant-camera')) el('assistant-camera').disabled = value;
    for (const id of ['assistant-send','assistant-clear','assistant-receipt-continue','assistant-bank-continue']) el(id).disabled = value;
    for (const node of [files,mode,text]) node.disabled = value;
    document.querySelectorAll('[data-assistant-choice]').forEach(node => { node.disabled = value; });
  };
  const hide = () => {
    proposed = null;
    for (const id of ['assistant-clarification','assistant-receipt','assistant-bank','assistant-analysis','assistant-operator','assistant-recurring']) if (el(id)) el(id).hidden = true;
  };
  const show = id => { el(id).hidden = false; el(id).focus(); };
  const reset = () => {
    if (busy || activeDraft()) {
      status.textContent = 'Selesaikan atau batalkan draft yang sedang ditinjau terlebih dahulu.';
      return;
    }
    hide(); text.value = ''; files.value = ''; mode.value = 'auto';
    if (el('assistant-camera')) el('assistant-camera').value = '';
    el('assistant-file-list').replaceChildren(); el('assistant-message').hidden = true;
    el('assistant-message-text').textContent = '';
    if (el('question')) el('question').value = '';
    if (el('answer')) { el('answer').replaceChildren(); el('answer').hidden = true; }
    if (el('op-request')) el('op-request').value = '';
    if (el('op-details')) el('op-details').replaceChildren();
    if (el('op-interpretation')) el('op-interpretation').textContent = '';
    for (const id of ['rec-name','rec-amount','rec-cadence','rec-start','rec-end','rec-account','rec-category']) if (el(id)) el(id).value = '';
    if (el('rec-details')) el('rec-details').replaceChildren();
    buttonLabel();
    status.textContent = 'Pesan dan lampiran dihapus dari halaman ini. Tidak ada pencatatan.';
  };
  const display = (workflow, action = '', suggestions = {}) => {
    hide(); proposed = workflow;
    const attached = files.files.length > 0;
    if (['READ_ONLY_ANALYSIS','TEXT_OPERATOR','RECURRING_DRAFT'].includes(workflow) && attached) {
      status.textContent = 'Pilihan ini memakai teks saja. Hapus lampiran atau pilih alur struk/mutasi; file belum diproses.';
      return;
    }
    if (workflow === 'NEEDS_CLARIFICATION') {
      el('assistant-clarification-title').textContent = attached ? 'File ini mau diproses sebagai apa?' : 'Kamu ingin dibantu dengan apa?';
      document.querySelectorAll('[data-assistant-choice]').forEach(node => {
        node.hidden = attached ? ['ask','record','recurring'].includes(node.dataset.assistantChoice) : ['receipt','bank','notes'].includes(node.dataset.assistantChoice);
      });
      show('assistant-clarification'); status.textContent = 'Pilih alur secara manual. Belum ada ekstraksi atau pencatatan.';
    } else if (workflow === 'UNSUPPORTED') {
      status.textContent = 'Permintaan atau tipe file belum didukung. Pilih alur yang tersedia; tidak ada tindakan dilakukan.';
    } else if (workflow === 'RECEIPT' || workflow === 'BANK_STATEMENT' || workflow === 'HANDWRITTEN_NOTE') {
      if (!attached || (workflow === 'RECEIPT' && files.files.length !== 1)) {
        status.textContent = workflow === 'RECEIPT' ? 'Pilih tepat satu file struk sebelum melanjutkan.' : 'Pilih file mutasi sebelum melanjutkan.';
        return;
      }
      if (workflow === 'RECEIPT' && receiptReady()) {
        el('assistant-receipt').hidden = false;
        el('assistant-send').focus();
      } else { show(workflow === 'RECEIPT' ? 'assistant-receipt' : 'assistant-bank'); }
      el('assistant-receipt-continue').hidden = receiptReady();
      if (el('assistant-bank-title')) el('assistant-bank-title').textContent = workflow === 'HANDWRITTEN_NOTE' ? 'Review catatan keuangan' : 'Import mutasi bank';
      buttonLabel();
      status.textContent = workflow === 'RECEIPT' ? 'Tekan Baca Struk untuk membaca file, lalu Review Hasil. Belum ada pencatatan.' : 'Periksa alur yang dipilih lalu lanjutkan. File belum diekstrak.';
    } else if (workflow === 'READ_ONLY_ANALYSIS') {
      if (text.value.length > 1000) { status.textContent = 'Ringkas pesan menjadi maksimal 1.000 karakter, lalu lanjutkan.'; return; }
      if (el('question')) {
        el('question').value = text.value;
        el('answer').replaceChildren(); el('answer').hidden = true;
        el('scope').value = /kategori|terbesar/i.test(text.value) ? 'categories' : /banding|bulan lalu/i.test(text.value) ? 'comparison' : /piutang/i.test(text.value) ? 'receivables' : 'summary';
      }
      show('assistant-analysis'); status.textContent = 'Periksa pertanyaan, bulan dan fokus lalu tekan Analisis. Tidak ada pencatatan.';
    } else if (workflow === 'TEXT_OPERATOR') {
      if (text.value.length > 1000) { status.textContent = 'Ringkas pesan menjadi maksimal 1.000 karakter, lalu lanjutkan.'; return; }
      if (el('op-action')) {
        el('op-request').value = text.value;
        el('op-action').value = ['create_expense','create_income','record_invoice_payment'].includes(action) ? action : '';
        el('op-action').dispatchEvent(new Event('change'));
        el('op-account').value = '';
      }
      show('assistant-operator'); status.textContent = 'Periksa tindakan, tanggal dan pilih akun/kategori/invoice sebelum menyiapkan draft. Belum ada pencatatan.';
    } else if (workflow === 'RECURRING_DRAFT') {
      if (el('rec-name')) {
        el('rec-name').value = suggestions.name || text.value.slice(0,160);
        el('rec-amount').value = suggestions.amount_text || '';
        el('rec-cadence').value = suggestions.cadence || '';
        for (const id of ['rec-start','rec-end','rec-account','rec-category']) el(id).value = '';
      }
      show('assistant-recurring'); status.textContent = 'Lengkapi dan review jadwal. Konfirmasi menyimpan jadwal saja; belum mencatat pengeluaran.';
    }
  };
  const route = async explicitMode => {
    if (busy) return;
    if (activeDraft()) {
      status.textContent = 'Selesaikan atau batalkan draft yang sedang ditinjau terlebih dahulu.';
      return;
    }
    if (text.value.length > 2000 || files.files.length > 10) {
      status.textContent = 'Maksimal 2.000 karakter dan 10 file.'; return;
    }
    state(true); hide(); status.textContent = 'Menentukan alur… Belum memproses file atau mencatat transaksi.';
    el('assistant-message-text').textContent = text.value;
    el('assistant-message').hidden = !text.value;
    try {
      const response = await fetch(composer.dataset.route, {method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{'Content-Type':'application/json','X-CSRF-Token':composer.dataset.csrf},
        body:JSON.stringify({text:text.value,mode:explicitMode || mode.value,files:Array.from(files.files, file => ({name:file.name}))})});
      if (!response.ok) {
        status.textContent = 'Permintaan belum dapat diproses. Periksa isian atau muat ulang halaman.'; return;
      }
      const result = await response.json();
      if (result.workflow === 'NEEDS_CLARIFICATION' && files.files.length &&
          (explicitMode || mode.value) === 'auto' && composer.dataset.recognize) {
        status.textContent = 'Mengenali jenis dokumen… Belum ada pencatatan.';
        const body = new FormData();
        for (const file of files.files) body.append('sources',file);
        body.append('csrf_token',composer.dataset.csrf);
        body.append('text',text.value);
        const recognized = await fetch(composer.dataset.recognize, {method:'POST', credentials:'same-origin', cache:'no-store',
          headers:{'X-CSRF-Token':composer.dataset.csrf}, body});
        if (!recognized.ok) { display('NEEDS_CLARIFICATION'); status.textContent = 'Dokumen belum dapat dikenali. Periksa format/ukuran file atau pilih alur secara manual.'; return; }
        result.workflow = (await recognized.json()).workflow;
      }
      display(workflows.has(result.workflow) ? result.workflow : 'NEEDS_CLARIFICATION', result.suggested_action, result.suggestions);
    } catch (_) { display('NEEDS_CLARIFICATION'); }
    finally { state(false); }
  };
  const handoff = workflow => {
    if (busy || proposed !== workflow || activeDraft()) return;
    if (!files.files.length || (workflow === 'RECEIPT' && files.files.length !== 1)) return;
    composer.querySelector('[name="account_id"]')?.remove();
    composer.querySelector('[name="document_kind"]')?.remove();
    if (workflow === 'BANK_STATEMENT' || workflow === 'HANDWRITTEN_NOTE') {
      const account = el('assistant-bank-account');
      if (!account.value) { status.textContent = 'Pilih akun Finance untuk mutasi ini.'; account.focus(); return; }
      const field = document.createElement('input');
      field.type = 'hidden'; field.name = 'account_id'; field.value = account.value; composer.append(field);
      const kind = document.createElement('input'); kind.type = 'hidden'; kind.name = 'document_kind';
      kind.value = workflow === 'HANDWRITTEN_NOTE' ? 'notes' : 'bank'; composer.append(kind);
    }
    files.name = workflow === 'RECEIPT' ? 'receipt' : 'sources';
    composer.action = workflow === 'RECEIPT' ? composer.dataset.receipt : composer.dataset.bank;
    state(true);
    // Native multipart navigation uses the original validator/review endpoint. No
    // prompt, file bytes or token is placed in a URL, session or browser storage.
    files.disabled = false;
    status.textContent = workflow === 'RECEIPT' ? 'Membaca struk… Berikutnya Review Hasil. Belum ada transaksi dibuat.' : 'Mengirim untuk ekstraksi dan review… Belum ada transaksi dibuat.';
    HTMLFormElement.prototype.submit.call(composer);
  };
  composer.addEventListener('submit', event => {
    event.preventDefault();
    if (!busy && !activeDraft() && receiptReady()) {
      display('RECEIPT'); handoff('RECEIPT');
    } else { route(); }
  });
  files.addEventListener('change', () => {
    if (!activeDraft()) hide();
    el('assistant-file-list').replaceChildren();
    if (!busy && !activeDraft() && receiptReady()) display('RECEIPT');
    buttonLabel();
    for (const file of files.files) {
      const item = document.createElement('li'); item.textContent = file.name; el('assistant-file-list').append(item);
    }
    if (!busy && files.files.length && mode.value === 'auto') {
      status.textContent = 'Dokumen siap. Tambahkan instruksi bila perlu, lalu tekan Lanjut. Belum ada pencatatan.';
    }
  });
  for (const node of [mode,text]) node.addEventListener('input', () => {
    if (!activeDraft()) {
      hide();
      if (node === mode && receiptReady()) display('RECEIPT');
    }
    buttonLabel();
  });
  el('assistant-clear').addEventListener('click', reset);
  el('assistant-cancel').addEventListener('click', reset);
  document.querySelectorAll('[data-assistant-choice]').forEach(button => button.addEventListener('click', () => {
    mode.value = button.dataset.assistantChoice; route(mode.value);
  }));
  el('assistant-receipt-continue').addEventListener('click', () => handoff('RECEIPT'));
  el('assistant-bank-continue').addEventListener('click', () => handoff(proposed === 'HANDWRITTEN_NOTE' ? 'HANDWRITTEN_NOTE' : 'BANK_STATEMENT'));
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  const camera = el('assistant-camera');
  if (camera) camera.addEventListener('change', () => {
    if (busy || activeDraft()) { camera.value = ''; return; }
    if (!camera.files.length) return;
    try {
      if (typeof DataTransfer === 'function') {
        const transfer = new DataTransfer();
        for (const file of camera.files) transfer.items.add(file);
        files.files = transfer.files;
      } else {
        files.files = camera.files;
      }
    } catch (_) {
      status.textContent = 'Foto belum dapat dipindahkan ke lampiran. Gunakan Pilih File untuk foto ini.';
      return;
    }
    // Kamera sekarang mengikuti mode yang dipilih; Auto tidak lagi memaksa semua foto menjadi struk.
    files.dispatchEvent(new Event('change'));
  });
  state(false);
})();
