(() => {
  const root = document.querySelector('.trading');
  const config = JSON.parse(document.querySelector('#trading-data').textContent);
  const status = document.querySelector('#trading-status');
  const message = document.querySelector('#trading-process');
  const error = document.querySelector('#trading-error');
  let pending = false;
  function freshness() {
    const node = document.querySelector('#trading-freshness');
    const age = (Date.now() - Date.parse(node.dataset.generated)) / 1000;
    const fresh = age >= 0 && age <= 120;
    node.textContent = fresh ? `Segar untuk simulasi · ${Math.floor(age)} detik` : 'Kedaluwarsa · perbarui snapshot replay';
    root.querySelectorAll('[data-new-position]').forEach(b => { b.disabled = pending || !fresh || !!config.paused || !!config.killed; });
  }
  freshness(); setInterval(freshness, 1000); // Local clock only; no polling or background orders.
  document.querySelector('#trading-side').addEventListener('change', event => {
    const sign = event.target.value === 'BUY' ? 1 : -1;
    document.querySelector('#trading-stop').value = (config.price_cents/100 - sign*10).toFixed(2);
    document.querySelector('#trading-target').value = (config.price_cents/100 + sign*20).toFixed(2);
  });
  root.querySelectorAll('form').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending) return;
    if (form.hasAttribute('data-kill') && !window.confirm('Kunci semua posisi baru? Kill switch tidak dapat dibuka kembali melalui dashboard. Posisi lama tetap dapat ditutup.')) return;
    const body = new FormData(form);
    pending = true;
    const buttons = [...root.querySelectorAll('button')];
    const disabledBefore = new Map(buttons.map(button => [button, button.disabled]));
    buttons.forEach(button => { button.disabled = true; });
    status.textContent = 'PROCESSING';
    message.textContent = 'Memproses permintaan simulasi Anda…';
    error.hidden = true;
    try {
      const response = await fetch(form.action, {method:'POST', body, headers:{Accept:'application/json'}});
      const result = await response.json();
      if (response.ok) { window.location.reload(); return; }
      status.textContent = 'ERROR';
      message.textContent = 'Aksi tidak berhasil. Pesan juga tercatat jika penyimpanan tersedia.';
      error.textContent = result.message || 'Permintaan gagal. Muat ulang halaman.';
      error.hidden = false;
    } catch (_) {
      status.textContent = 'ERROR';
      message.textContent = 'Koneksi terputus atau sesi berakhir.';
      error.textContent = 'Hasil belum pasti. Muat ulang untuk memeriksa jurnal sebelum mengirim order baru; permintaan ini tetap memakai kunci yang sama.';
      error.hidden = false;
    }
    pending = false;
    buttons.forEach(button => { button.disabled = disabledBefore.get(button); });
    const control = root.querySelector('form[data-kill] button');
    if (config.killed) { control.disabled = true; root.querySelector('.trading-controls form:first-child button').disabled = true; }
    freshness();
  }));
})();
