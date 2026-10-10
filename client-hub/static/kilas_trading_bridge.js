(() => {
  const panel = document.querySelector('#trading-bridge');
  if (!panel) return;
  let enabled = panel.dataset.enabled === 'true';
  const status = panel.querySelector('[data-bridge-status]');
  const secret = panel.querySelector('[data-bridge-code]');
  const market = panel.querySelector('[data-bridge-market]');
  const history = panel.querySelector('[data-bridge-history]');
  const attempt = panel.querySelector('[data-bridge-attempt]');
  let revocable = panel.dataset.revocable === 'true';
  function controls() {
    panel.querySelectorAll('button').forEach(b => {b.disabled = pending || (b.closest('form').hasAttribute('data-bridge-revoke') ? !revocable : !enabled);});
  }
  let paired = panel.dataset.paired === 'true', pending = false, generation = 0;
  function render(data) {
    enabled = data.enabled === true;
    revocable = data.revoke_allowed === true;
    controls();
    status.textContent = `Transport: ${data.transport || 'DISCONNECTED'} · Terminal: ${data.terminal || 'UNKNOWN'} (klaim collector) · Market: ${data.market_freshness || 'UNVERIFIED'} · ${data.outcome}`;
    market.replaceChildren();
    history.textContent = `Bukti tersimpan: ${data.last_confirmed_stage || 'NONE'} · pesan diterima ${data.accepted_messages || 0} · revoked ${data.revoked === true ? 'ya' : 'tidak'} · error server terakhir: NOT_RECORDED.`;
    if (data.market) {
      const p = document.createElement('p');
      p.textContent = `${data.symbol} · bid ${data.market.tick.bid} / ask ${data.market.tick.ask} · raw time_msc ${data.market.tick.time_msc} · capture UTC ${data.market.capture.end_utc} · diterima ${data.last_received_at}. Harga observasi; profil waktu belum terverifikasi. Order diblokir.`;
      market.append(p);
    }
  }
  async function poll() {
    if (!paired || pending || document.visibilityState !== 'visible') return;
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
    if (pending || (!enabled && !form.hasAttribute('data-bridge-revoke'))) return;
    pending = true;
    generation++;
    const buttons = [...panel.querySelectorAll('button')];
    buttons.forEach(b => {b.disabled = true;});
    secret.textContent = ''; secret.hidden = true;
    try {
      const res = await fetch(form.action, {method:'POST', body:new FormData(form), headers:{Accept:'application/json'}, cache:'no-store'});
      const data = await res.json();
      attempt.textContent = `Aksi dashboard terakhir: ${form.hasAttribute('data-bridge-revoke') ? 'REVOKE' : 'PAIR'} · HTTP ${res.status}. Bukti browser saja; bukan hasil collector.`;
      if (!res.ok) {status.textContent = `Bridge belum tersedia: ${data.outcome}. Muat ulang sebelum mencoba lagi.`;return;}
      if (data.pair_code) {
        paired = true;
        revocable = true;
        secret.textContent = `Kode sekali pakai: ${data.pair_code} · kedaluwarsa ${data.expires_at}. Masukkan hanya ke collector lokal yang disetujui. Kode hilang setelah halaman dimuat ulang.`;
        secret.hidden = false;
        status.textContent = 'Menunggu collector lokal; belum terhubung.';
      } else {paired = false; revocable = false; market.replaceChildren(); status.textContent = 'Bridge dicabut. Collector tidak dapat mengirim lagi.'; history.textContent = 'REVOKED; credential dihapus. Bukti tahap terakhir tersedia setelah muat ulang.';}
    } catch (_) {status.textContent = 'Hasil aksi belum pasti. Muat ulang untuk memeriksa status; jangan mengulang otomatis.'; attempt.textContent = 'Aksi dashboard terakhir: RESPONSE_UNCONFIRMED. Tidak ada bukti respons berhasil.';}
    finally {pending = false; controls();}
  }));
  controls();
  setInterval(poll, 2000); document.addEventListener('visibilitychange', poll); poll();
})();
