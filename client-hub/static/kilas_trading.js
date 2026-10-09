(() => {
  if (typeof document === 'undefined') return;
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
    node.textContent = fresh ? `Diperbarui ${Math.floor(age)} detik lalu` : 'Harga perlu diperbarui — buka Detail harga';
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
    if (form.hasAttribute('data-kill') && !window.confirm('Hentikan trading? Posisi baru akan diblokir permanen untuk pilot ini. Posisi lama tetap terbuka dan dapat ditutup manual.')) return;
    const body = new FormData(form);
    pending = true;
    const buttons = [...root.querySelectorAll('button')];
    const disabledBefore = new Map(buttons.map(button => [button, button.disabled]));
    buttons.forEach(button => { button.disabled = true; });
    status.textContent = 'Memproses';
    message.textContent = 'Memproses permintaan Anda…';
    error.hidden = true;
    try {
      const response = await fetch(form.action, {method:'POST', body, headers:{Accept:'application/json'}});
      const result = await response.json();
      if (response.ok) { window.location.reload(); return; }
      status.textContent = 'Aksi gagal';
      message.textContent = 'Aksi tidak berhasil. Pesan juga tercatat jika penyimpanan tersedia.';
      error.textContent = result.message || 'Permintaan gagal. Muat ulang halaman.';
      error.hidden = false;
    } catch (_) {
      status.textContent = 'Aksi gagal';
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

// Recorded reports are local data, never a source for the MOCK engine or AI.
(() => {
  const MAX_BYTES = 131072;
  const invalid = () => { throw new Error('REPORT_REJECTED'); };
  function parseJSON(text) {
    if (typeof text !== 'string' || !text.length || new TextEncoder().encode(text).length > MAX_BYTES) invalid();
    let i = 0, nodes = 0;
    const ws = () => { while (/[\x20\t\r\n]/.test(text[i] || '\0')) i++; };
    function string() {
      const start = i++;
      while (i < text.length) {
        const c = text[i++];
        if (c === '"') return JSON.parse(text.slice(start, i));
        if (c === '\\') i++;
      }
      invalid();
    }
    function value(depth) {
      if (depth > 32 || ++nodes > 20000) invalid();
      ws(); const c = text[i];
      if (c === '"') return string();
      if (c === '{' || c === '[') {
        i++; ws(); const object = c === '{', end = object ? '}' : ']';
        const out = object ? Object.create(null) : [];
        if (text[i] === end) { i++; return out; }
        while (i < text.length) {
          ws(); let key;
          if (object) {
            if (text[i] !== '"') invalid();
            key = string(); ws();
            if (Object.hasOwn(out, key) || ['__proto__', 'constructor', 'prototype'].includes(key) || text[i++] !== ':') invalid();
          }
          const item = value(depth + 1);
          if (object) out[key] = item; else out.push(item);
          ws(); const delimiter = text[i++];
          if (delimiter === end) return out;
          if (delimiter !== ',') invalid();
        }
        invalid();
      }
      const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(text.slice(i));
      if (!match) invalid();
      i += match[0].length; const out = JSON.parse(match[0]);
      if (typeof out === 'number' && !Number.isFinite(out)) invalid();
      return out;
    }
    const result = value(0); ws(); if (i !== text.length) invalid(); return result;
  }
  const object = x => { if (!x || typeof x !== 'object' || Array.isArray(x)) invalid(); return x; };
  const list = (x, max, min = 0) => { if (!Array.isArray(x) || x.length < min || x.length > max) invalid(); return x; };
  const integer = (x, max) => { if (!Number.isSafeInteger(x) || x < 0 || x > max) invalid(); return x; };
  const number = x => {
    if (!(typeof x === 'number' || typeof x === 'string' && /^\d{1,9}(?:\.\d{1,8})?$/.test(x)) || !Number.isFinite(Number(x)) || Number(x) <= 0 || Number(x) > 1e9) invalid();
    return Number(x);
  };
  function disabled(x, keys) { object(x); for (const key of keys) if (x[key] !== false) invalid(); }
  function parseReport(text) {
    const r = object(parseJSON(text));
    if (r.status !== 'READ_ONLY_DEMO_DIAGNOSTIC_CAPTURED' || r.input_kind !== 'DEMO_OBSERVATION' || r.producer_acceptance !== 'NOT_IMPLEMENTED' || r.sdk_shutdown !== 'COMPLETED' || r.source_semantics !== 'CANDIDATE_PROFILE_NOT_BROKER_VERIFIED' || r.history_complete !== false || r.profit_after_costs !== 'NOT_EVALUATED' || r.drawdown !== 'NOT_EVALUATED') invalid();
    disabled(r, ['runtime_eligible', 'broker_execution_allowed', 'paper_execution', 'ai_analysis']);
    const timestamp = r.finished_utc;
    if (typeof timestamp !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(timestamp) || !Number.isFinite(Date.parse(timestamp))) invalid();
    const normalized = new Date(timestamp).toISOString();
    if (normalized.slice(0, 19) !== timestamp.slice(0, 19)) invalid();
    const collection = object(r.collection);
    if (collection.schema !== 'kilas-collector-diagnostic-v1' || collection.status !== 'DIAGNOSTIC_COLLECTION_VALIDATED' || collection.producer_acceptance !== 'NOT_IMPLEMENTED' || typeof collection.synthetic !== 'boolean') invalid();
    disabled(collection, ['runtime_eligible', 'broker_execution_allowed']);
    const requests = integer(collection.request_count, 16);
    if (integer(r.ntp_datagrams_sent, 16) !== requests) invalid();
    const cycles = list(collection.cycles, 4, 1);
    let replies = 0, attemptsTotal = 0;
    for (const cycle of cycles) {
      const q = object(object(cycle).qualification);
      if (q.status !== 'OFFLINE_CLOCK_BATCH_VALIDATED' || q.assurance !== 'UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY' || q.producer_acceptance !== 'NOT_IMPLEMENTED') invalid();
      disabled(q, ['runtime_eligible', 'broker_execution_allowed']);
      const attempts = integer(q.attempt_count, 16), count = integer(q.reply_count, 16);
      if (count > attempts) invalid(); replies += count; attemptsTotal += attempts;
    }
    if (replies > requests || attemptsTotal !== requests) invalid();
    const clocks = list(r.clock_results, 4, 1).map(c => {
      object(c); disabled(c, ['runtime_eligible', 'broker_execution_allowed']);
      if (c.input_kind !== 'DEMO_OBSERVATION' || c.policy_replay_only !== true || c.producer_acceptance !== 'NOT_IMPLEMENTED' || c.clock_assurance !== 'UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY' || !['WAIT', 'READ_ONLY_VALIDATED_FIXTURE'].includes(c.status)) invalid();
      for (const k of ['ai_analysis', 'paper_execution']) if (Object.hasOwn(c, k) && c[k] !== false) invalid();
      return {status: c.status, uncertaintyMs: Object.hasOwn(c, 'clock_uncertainty_ms') ? integer(c.clock_uncertainty_ms, 60000) : null};
    });
    const markets = list(r.markets, 4, 1);
    if (clocks.length !== cycles.length || markets.length !== cycles.length) invalid();
    for (const m of markets) {
      object(m); disabled(m, ['runtime_eligible', 'broker_execution_allowed', 'paper_execution', 'ai_analysis']);
      if (m.input_kind !== 'DEMO_OBSERVATION' || m.account_mode !== 'DEMO') invalid();
    }
    const risks = list(r.risk_evidence, 4).map(e => {
      object(e); disabled(e, ['runtime_eligible', 'broker_execution_allowed', 'paper_execution', 'ai_analysis']);
      if (e.status !== 'READ_ONLY_DEMO_RISK_EVIDENCE') invalid();
      const cap = number(e.notional_cap_usd);
      if (cap !== 2000) invalid();
      const costs = object(e.costs);
      if (costs.commission !== 'UNKNOWN' || costs.slippage !== 'UNKNOWN' || costs.swap_execution_cost !== 'UNKNOWN') invalid();
      const scenarios = list(e.scenarios, 2, 1).map(s => {
        object(s);
        if (!['BUY', 'SELL'].includes(s.direction) || s.hypothetical !== true || s.account_sizing_applied !== false || !['BLOCKED', 'WITHIN_CAP'].includes(s.cap_status)) invalid();
        const notional = number(s.notional_usd);
        if (s.cap_status !== (notional > cap ? 'BLOCKED' : 'WITHIN_CAP')) invalid();
        return {direction: s.direction, lots: number(s.volume_lots), notional, capStatus: s.cap_status};
      });
      if (new Set(scenarios.map(s => s.direction)).size !== scenarios.length) invalid();
      return {cap, scenarios};
    });
    // Fresh allowlisted projection: private account/history/raw packets and all
    // unknown fields are discarded. This object never enters app config/storage.
    return {timestamp, outcome: r.status, synthetic: collection.synthetic, observations: markets.length, requests, replies, clocks, risks};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {parseReport, MAX_BYTES};
  if (typeof document === 'undefined') return;
  const panel = document.querySelector('#diagnostic-details');
  if (!panel) return;
  const input = panel.querySelector('input'), output = panel.querySelector('#diagnostic-result'), status = panel.querySelector('#diagnostic-status');
  let generation = 0;
  function clear() { generation++; input.value = ''; output.replaceChildren(); status.textContent = 'Belum ada laporan lokal.'; }
  panel.querySelector('button').addEventListener('click', clear);
  window.addEventListener('pagehide', clear);
  function row(label, value) {
    const group = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = label; dd.textContent = value; group.append(dt, dd); output.append(group);
  }
  input.addEventListener('change', async () => {
    const token = ++generation, file = input.files[0];
    output.replaceChildren(); status.textContent = 'Memeriksa laporan lokal…';
    try {
      if (!file || file.size < 1 || file.size > MAX_BYTES) invalid();
      const bytes = await file.arrayBuffer();
      if (token !== generation) return;
      const report = parseReport(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
      status.textContent = 'DEMO · snapshot historis · hanya baca' + (report.synthetic ? ' · fixture sintetis' : ' · klaim sumber dari file');
      row('Capture selesai · UTC dari laporan', report.timestamp);
      row('Hasil diagnostik dalam laporan', report.outcome);
      row('Observasi / balasan NTP tercatat', `${report.observations} observasi · ${report.replies}/${report.requests} balasan`);
      row('Clock · belum terautentikasi', report.clocks.map(c => c.status + (c.uncertaintyMs === null ? '' : ` · ketidakpastian ${c.uncertaintyMs} ms`)).join('; '));
      row('Profil broker', 'Profil kandidat belum diverifikasi; offset broker/DST, usia data dan mapping GOLD belum terverifikasi.');
      row('Runtime / broker / AI / paper', 'Tidak memenuhi syarat / diblokir / nonaktif / nonaktif. Producer acceptance NOT_IMPLEMENTED; policy replay only; SDK shutdown COMPLETED.');
      for (const risk of report.risks) for (const s of risk.scenarios) row(`Risiko hipotetis ${s.direction} · ${s.capStatus}`, `${s.lots} lot · notional USD ${s.notional.toFixed(2)} · cap laporan USD ${risk.cap}. Tidak menerapkan sizing akun; bukan izin eksekusi.`);
      if (!report.risks.length) row('Risiko', 'Tidak ada bukti risiko dalam laporan; eksekusi tetap diblokir.');
      row('Biaya & evaluasi', 'Komisi, slippage dan swap tidak diketahui. Riwayat tidak lengkap; net P&L dan drawdown tidak dievaluasi.');
    } catch (_) {
      if (token === generation) { output.replaceChildren(); status.textContent = 'Laporan ditolak. Pilih JSON UTF-8 diagnostik DEMO v1 yang kompatibel, maksimal 128 KiB. File malformed, field duplikat dan flag eksekusi aktif ditolak.'; }
    } finally { if (token === generation) input.value = ''; }
  });
})();
