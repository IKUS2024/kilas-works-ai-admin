'use strict';
(() => {
  const el = id => document.getElementById(id), form = el('recurring-form');
  if (!form) return;
  let token = null, busy = false, attempted = false;
  const state = value => {
    busy = value; el('recurring-fields').disabled = value || !!token;
    el('rec-confirm').disabled = value; el('rec-cancel').disabled = value;
  };
  const clear = () => { token = null; el('rec-preview').hidden = true; state(false); };
  const send = async (url, body) => {
    const response = await fetch(url, {method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/json','X-CSRF-Token':form.dataset.csrf}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error('request_failed');
    return result;
  };
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || token) return;
    state(true); el('rec-status').textContent = 'Menyiapkan review. Belum menyimpan…';
    try {
      const result = await send(form.dataset.draft, {name:el('rec-name').value, amount_text:el('rec-amount').value,
        cadence:el('rec-cadence').value, next_due_on:el('rec-start').value, end_on:el('rec-end').value || null,
        account_id:Number(el('rec-account').value), category_id:Number(el('rec-category').value)});
      token = result.token; attempted = false; el('rec-details').replaceChildren();
      for (const [label, value] of result.preview) {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = label; dd.textContent = value; el('rec-details').append(dt, dd);
      }
      el('rec-preview').hidden = false; el('rec-status').textContent = 'Periksa jadwal lalu konfirmasi. Belum ada pencatatan.';
    } catch (_) { el('rec-status').textContent = 'Draft belum tersedia. Periksa isian dan akses bisnis, lalu coba lagi.'; }
    finally { state(false); }
  });
  el('rec-cancel').addEventListener('click', () => {
    if (busy) return;
    clear(); el('rec-status').textContent = attempted ? 'Periksa Biaya Rutin; konfirmasi sebelumnya mungkin sudah diproses.' : 'Draft dibatalkan. Isian dapat diedit.';
  });
  el('rec-confirm').addEventListener('click', async () => {
    if (busy || !token) return;
    attempted = true; state(true);
    try {
      const result = await send(form.dataset.confirm, {token, confirm:true});
      clear(); el('rec-status').textContent = result.message;
    } catch (_) { el('rec-status').textContent = 'Konfirmasi belum dapat dipastikan. Ulangi konfirmasi draft yang sama atau periksa Biaya Rutin sebelum membuat draft baru.'; }
    finally { state(false); }
  });
})();
