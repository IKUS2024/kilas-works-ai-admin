'use strict';
(() => {
  const el = id => document.getElementById(id);
  const form = el('operator-form');
  if (!form) return;
  let token = null, busy = false, confirmationAttempted = false;
  const clear = () => { token = null; el('op-preview').hidden = true; el('operator-fields').disabled = false; };
  const state = value => { busy = value; el('operator-fields').disabled = value || !!token; el('op-confirm').disabled = value; el('op-cancel').disabled = value; };
  const request = async (url, payload) => {
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':form.dataset.csrf},body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Permintaan belum dapat diproses.');
    return result;
  };
  const choices = () => {
    const payment = el('op-action').value === 'record_invoice_payment';
    const direction = el('op-action').value === 'create_expense' ? 'EXPENSE' : 'INCOME';
    for (const option of el('op-category').options) {
      option.hidden = !!option.dataset.direction && option.dataset.direction !== direction;
      option.disabled = option.hidden;
    }
    el('op-category').value = ''; el('op-invoice').value = '';
    el('op-invoice-wrap').hidden = !payment; el('op-invoice').required = payment;
  };
  el('op-action').addEventListener('change', choices); choices();
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || token) return;
    state(true); el('op-status').textContent = 'Menyiapkan usulan, belum menyimpan data…';
    try {
      const result = await request(form.dataset.draft, {action:el('op-action').value, request:el('op-request').value,date:el('op-date').value,account_id:Number(el('op-account').value),category_id:Number(el('op-category').value),invoice_id:el('op-invoice').value ? Number(el('op-invoice').value) : null});
      token = result.token; confirmationAttempted = false; el('op-interpretation').textContent = result.interpretation;
      el('op-details').replaceChildren();
      for (const [label, value] of result.preview) {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = label; dd.textContent = value; el('op-details').append(dt,dd);
      }
      el('op-preview').hidden = false; el('op-status').textContent = 'Draft siap ditinjau. Belum ada pencatatan.';
    } catch (error) { el('op-status').textContent = error instanceof SyntaxError ? 'Draft belum tersedia. Tidak ada pencatatan.' : error.message; }
    finally { state(false); }
  });
  el('op-cancel').addEventListener('click', () => {
    if (busy) return;
    clear(); el('op-status').textContent = confirmationAttempted
      ? 'Draft ditutup. Konfirmasi sebelumnya mungkin sudah diproses. Periksa riwayat sebelum membuat draft baru.'
      : 'Draft dibatalkan di halaman ini. Tidak ada pencatatan.';
  });
  el('op-confirm').addEventListener('click', async () => {
    if (busy || !token) return;
    confirmationAttempted = true; state(true); el('op-status').textContent = 'Memproses konfirmasi… Jangan tutup halaman.';
    try {
      const result = await request(form.dataset.confirm, {token,confirm:true});
      clear(); el('op-status').textContent = result.message + ' Referensi catatan: ' + result.record_id;
    } catch (error) {
      el('op-status').textContent = 'Konfirmasi belum dapat dipastikan. Periksa riwayat atau ulangi konfirmasi draft yang sama; jangan membuat draft baru. ' + (error instanceof SyntaxError ? '' : error.message);
    } finally { state(false); }
  });
})();
