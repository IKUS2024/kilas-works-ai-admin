(() => {
  const panel = document.querySelector('#trading-bridge');
  if (!panel) return;
  const enabled = panel.dataset.enabled === 'true';
  const status = panel.querySelector('[data-bridge-status]');
  const secret = panel.querySelector('[data-bridge-code]');
  const market = panel.querySelector('[data-bridge-market]');
  let paired = panel.dataset.paired === 'true', pending = false, generation = 0;
  function render(data) {
    status.textContent = `Transport: ${data.transport || 'DISCONNECTED'} · Terminal: ${data.terminal || 'UNKNOWN'} (klaim collector) · Market: ${data.market_freshness || 'UNVERIFIED'} · ${data.outcome}`;
    market.replaceChildren();
    if (data.market) {
      const p = document.createElement('p');
      p.textContent = `${data.symbol} · bid ${data.market.tick.bid} / ask ${data.market.tick.ask} · raw time_msc ${data.market.tick.time_msc} · capture UTC ${data.market.capture.end_utc} · diterima ${data.last_received_at}. Harga observasi; profil waktu belum terverifikasi. Order diblokir.`;
      market.append(p);
    }
  }
  async function poll() {
    if (!enabled || !paired || pending || document.visibilityState !== 'visible') return;
    const token = generation;
    try {
      const res = await fetch(panel.dataset.statusUrl, {headers: {Accept:'application/json'}, cache:'no-store'});
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (token === generation && !pending && paired) render(data);
    } catch (_) {
      if (token !== generation || pending || !paired) return;
      market.replaceChildren();
      status.textContent = 'Status bridge tidak tersedia; koneksi/freshness tidak dapat dikonfirmasi. Order diblokir.';
    }
  }
  panel.querySelectorAll('form').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!enabled || pending) return;
    pending = true;
    generation++;
    const buttons = [...panel.querySelectorAll('button')];
    buttons.forEach(b => {b.disabled = true;});
    secret.textContent = ''; secret.hidden = true;
    try {
      const res = await fetch(form.action, {method:'POST', body:new FormData(form), headers:{Accept:'application/json'}, cache:'no-store'});
      const data = await res.json();
      if (!res.ok) {status.textContent = `Bridge belum tersedia: ${data.outcome}. Muat ulang sebelum mencoba lagi.`;return;}
      if (data.pair_code) {
        paired = true;
        secret.textContent = `Kode sekali pakai: ${data.pair_code} · kedaluwarsa ${data.expires_at}. Masukkan hanya ke collector lokal yang disetujui. Kode hilang setelah halaman dimuat ulang.`;
        secret.hidden = false;
        status.textContent = 'Menunggu collector lokal; belum terhubung.';
      } else {paired = false; market.replaceChildren(); status.textContent = 'Bridge dicabut. Collector tidak dapat mengirim lagi.';}
    } catch (_) {status.textContent = 'Hasil pairing belum pasti. Muat ulang untuk memeriksa status; jangan mengulang otomatis.';}
    finally {pending = false; buttons.forEach(b => {b.disabled = false;});}
  }));
  if (enabled) {setInterval(poll, 2000); document.addEventListener('visibilitychange', poll); poll();}
})();
