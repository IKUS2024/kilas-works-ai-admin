'use strict';
(() => {
const form = document.getElementById('analyst-form');
if (!form) return;
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const send = document.getElementById('send'), status = document.getElementById('status'), answer = document.getElementById('answer');
  if (send.disabled) return;
  send.disabled = true; status.textContent = 'Menganalisis laporan…'; answer.hidden = true; answer.replaceChildren();
  const line = (tag, text) => { const node = document.createElement(tag); node.textContent = text; answer.append(node); };
  try {
    const response = await fetch(form.dataset.endpoint || location.pathname, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':form.dataset.csrf}, body:JSON.stringify({question:document.getElementById('question').value, month:document.getElementById('month').value, scope:document.getElementById('scope').value})});
    const data = await response.json();
    if (!response.ok) { status.textContent = 'AI belum berhasil menganalisis laporan. Buka Laporan & Export atau coba lagi nanti. Data keuangan tidak diubah.'; return; }
    line('h2','Fakta dari catatan keuangan');
    line('p',data.context.period_start + ' — ' + data.context.period_end);
    for (const fact of data.context.facts) line('p',fact.id + ' · ' + fact.label + ': ' + fact.display);
    for (const limitation of data.context.limitations) line('p',limitation);
    for (const [key,label] of [['observations','Interpretasi AI'],['suggestions','Saran AI']]) {
      line('h2',label);
      for (const item of data.analysis[key]) line('p',item.text + (item.refs.length ? ' (Fakta: ' + item.refs.join(', ') + ')' : ''));
    }
    answer.hidden = false; status.textContent = 'Analisis selesai. Tidak ada data yang diubah.';
  } catch (_) { status.textContent = 'Analisis belum tersedia. Periksa koneksi atau buka Laporan & Export. Data keuangan tidak diubah.'; }
  finally { send.disabled = false; }
});
})();
