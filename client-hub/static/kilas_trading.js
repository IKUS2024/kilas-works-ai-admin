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
  root.querySelectorAll('form:not([data-bridge-form])').forEach(form => form.addEventListener('submit', async event => {
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
  const decimal = x => {
    // Diagnostic quantities/money are decimal strings, not JSON floats. Keep
    // all eight supported fractional places through comparison and display.
    if (typeof x !== 'string' || !/^\d{1,9}(?:\.\d{1,8})?$/.test(x)) invalid();
    const [whole, fraction = ''] = x.split('.');
    const units = BigInt(whole) * 100000000n + BigInt(fraction.padEnd(8, '0'));
    if (units <= 0n) invalid();
    const normalizedFraction = fraction.replace(/0+$/, '');
    return {units, text: BigInt(whole).toString() + (normalizedFraction ? '.' + normalizedFraction : '')};
  };
  const exact = (x, fields) => {
    object(x);
    if (Object.keys(x).length !== fields.length || fields.some(k => !Object.hasOwn(x, k))) invalid();
    return x;
  };
  const notionalGates = () => ({source_verification: 'NOT_INDEPENDENTLY_VERIFIED',
    freshness: 'NOT_EVALUATED', producer_acceptance: 'NOT_IMPLEMENTED', policy_replay_only: true,
    runtime_eligible: false, broker_execution_allowed: false, ai_analysis: false, paper_execution: false});
  function checkNotionalFacts(raw) {
    exact(raw, ['schema', 'input_kind', 'units', 'specs', 'quote', 'scenarios', 'notional_cap_usd']);
    if (raw.schema !== 'kilas-offline-notional-facts-v1' || !['SYNTHETIC_TEST_FACTS', 'HISTORICAL_DECLARED_FACTS'].includes(raw.input_kind)) invalid();
    const units = exact(raw.units, ['quote_currency', 'price_unit', 'contract_unit', 'volume_step_origin']);
    if (units.quote_currency !== 'USD' || units.price_unit !== 'USD_PER_TROY_OUNCE' || units.contract_unit !== 'TROY_OUNCES_PER_LOT' || units.volume_step_origin !== 'ZERO_MULTIPLES') invalid();
    const specs = exact(raw.specs, ['currency_profit', 'trade_contract_size', 'volume_min', 'volume_step', 'volume_max']);
    if (specs.currency_profit !== 'USD') invalid();
    const size = decimal(specs.trade_contract_size), minimum = decimal(specs.volume_min);
    const step = decimal(specs.volume_step), maximum = decimal(specs.volume_max);
    if (minimum.units > maximum.units || minimum.units % step.units !== 0n || maximum.units % step.units !== 0n) invalid();
    const quote = exact(raw.quote, ['bid', 'ask']);
    const bid = decimal(quote.bid), ask = decimal(quote.ask);
    if (ask.units < bid.units) invalid();
    const cap = decimal(raw.notional_cap_usd);
    if (cap.units !== 200000000000n) invalid();
    function derive(volume, price) {
      const product = volume.units * size.units * price.units;
      // Three eight-place factors -> one eight-place notional, with no rounding.
      if (product % 10000000000000000n !== 0n) invalid();
      const amount = product / 10000000000000000n;
      if (amount <= 0n || amount > 99999999999999999n) invalid();
      const fraction = (amount % 100000000n).toString().padStart(8, '0').replace(/0+$/, '');
      return {notional_usd: (amount / 100000000n).toString() + (fraction ? '.' + fraction : ''),
        cap_status: amount > cap.units ? 'BLOCKED' : 'WITHIN_CAP', units: amount};
    }
    const scenarios = list(raw.scenarios, 2, 1).map(s => {
      exact(s, ['direction', 'volume_lots', 'notional_usd', 'cap_status', 'hypothetical', 'account_sizing_applied']);
      if (!['BUY', 'SELL'].includes(s.direction) || s.hypothetical !== true || s.account_sizing_applied !== false) invalid();
      const volume = decimal(s.volume_lots), reported = decimal(s.notional_usd);
      if (volume.units < minimum.units || volume.units > maximum.units || volume.units % step.units !== 0n) invalid();
      const derived = derive(volume, s.direction === 'BUY' ? ask : bid);
      if (derived.units !== reported.units || derived.cap_status !== s.cap_status) invalid();
      return {direction: s.direction, volume_lots: volume.text, derived_notional_usd: derived.notional_usd, cap_status: derived.cap_status};
    });
    if (new Set(scenarios.map(s => s.direction)).size !== scenarios.length) invalid();
    const minimumNotional = ['BUY', 'SELL'].map(direction => {
      const result = derive(minimum, direction === 'BUY' ? ask : bid);
      return {direction, notional_usd: result.notional_usd, cap_status: result.cap_status};
    });
    return {outcome: 'ARITHMETIC_CONSISTENT_ONLY', input_kind: raw.input_kind,
      minimum_volume_lots: minimum.text, minimum_notional: minimumNotional, scenarios, ...notionalGates()};
  }
  const parseNotionalFacts = text => checkNotionalFacts(parseJSON(text));
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
      const cap = decimal(e.notional_cap_usd);
      if (cap.units !== 200000000000n) invalid();
      const costs = object(e.costs);
      if (costs.commission !== 'UNKNOWN' || costs.slippage !== 'UNKNOWN' || costs.swap_execution_cost !== 'UNKNOWN') invalid();
      const scenarios = list(e.scenarios, 2, 1).map(s => {
        object(s);
        if (!['BUY', 'SELL'].includes(s.direction) || s.hypothetical !== true || s.account_sizing_applied !== false || !['BLOCKED', 'WITHIN_CAP'].includes(s.cap_status)) invalid();
        const notional = decimal(s.notional_usd);
        if (s.cap_status !== (notional.units > cap.units ? 'BLOCKED' : 'WITHIN_CAP')) invalid();
        return {direction: s.direction, lots: decimal(s.volume_lots).text, notional: notional.text, capStatus: s.cap_status};
      });
      if (new Set(scenarios.map(s => s.direction)).size !== scenarios.length) invalid();
      let consistency = {outcome: 'NOT_EVALUATED_MISSING_UNITS', ...notionalGates()};
      if (Object.hasOwn(e, 'notional_units')) {
        // Explicit adapter metadata is required. Never infer units from GOLD,
        // contract size, profit currency, or any synthetic engine assumptions.
        const specs = object(e.specs), quote = object(e.quote);
        consistency = checkNotionalFacts({schema: 'kilas-offline-notional-facts-v1',
          input_kind: collection.synthetic ? 'SYNTHETIC_TEST_FACTS' : 'HISTORICAL_DECLARED_FACTS',
          units: e.notional_units, notional_cap_usd: e.notional_cap_usd,
          specs: Object.fromEntries(['currency_profit', 'trade_contract_size', 'volume_min', 'volume_step', 'volume_max'].map(k => [k, specs[k]])),
          quote: {bid: quote.bid, ask: quote.ask},
          scenarios: e.scenarios.map(s => Object.fromEntries(['direction', 'volume_lots', 'notional_usd', 'cap_status', 'hypothetical', 'account_sizing_applied'].map(k => [k, s[k]])))});
      }
      return {cap: cap.text, scenarios, consistency};
    });
    // Fresh allowlisted projection: private account/history/raw packets and all
    // unknown fields are discarded. This object never enters app config/storage.
    return {timestamp, outcome: r.status, synthetic: collection.synthetic, observations: markets.length, requests, replies, clocks, risks};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {parseReport, parseNotionalFacts, MAX_BYTES};
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
      row('Koneksi read-only dalam laporan', 'Klaim capture historis dari file; aplikasi belum terhubung ke broker.');
      row('Market fresh', 'Belum diverifikasi. Replay clock dan status koneksi tidak membuktikan quote/candle terbaru.');
      row('Observasi / balasan NTP tercatat', `${report.observations} observasi · ${report.replies}/${report.requests} balasan`);
      row('Clock · belum terautentikasi', report.clocks.map(c => c.status + (c.uncertaintyMs === null ? '' : ` · ketidakpastian ${c.uncertaintyMs} ms`)).join('; '));
      row('Profil broker', 'Profil kandidat belum diverifikasi; offset broker/DST, usia data dan mapping GOLD belum terverifikasi.');
      row('Runtime / broker / AI / paper', 'Tidak memenuhi syarat / diblokir / nonaktif / nonaktif. Producer acceptance NOT_IMPLEMENTED; policy replay only; SDK shutdown COMPLETED.');
      for (const risk of report.risks) {
        for (const s of risk.scenarios) {
          const [whole, fraction = ''] = s.notional.split('.');
          row(`Risiko hipotetis ${s.direction} · ${s.capStatus}`, `${s.lots} lot · notional USD ${whole}.${fraction.padEnd(2, '0')} · cap laporan USD ${risk.cap}. Tidak menerapkan sizing akun; bukan izin eksekusi.`);
        }
        row('Konsistensi notional · aritmetika saja', risk.consistency.outcome === 'ARITHMETIC_CONSISTENT_ONLY'
          ? 'ARITHMETIC_CONSISTENT_ONLY · volume minimum ' + risk.consistency.minimum_volume_lots + ' lot; ' + risk.consistency.minimum_notional.map(s => `${s.direction} USD ${s.notional_usd} · ${s.cap_status}`).join('; ') + '. Fakta dari file belum diverifikasi; tidak memberi izin eksekusi.'
          : 'NOT_EVALUATED_MISSING_UNITS · unit harga/kontrak dan aturan lot belum dinyatakan lengkap. Angka risiko adalah klaim historis dari file, bukan sizing broker terverifikasi.');
      }
      if (!report.risks.length) row('Risiko', 'Tidak ada bukti risiko dalam laporan; eksekusi tetap diblokir.');
      row('Biaya & evaluasi', 'Komisi, slippage dan swap tidak diketahui. Riwayat tidak lengkap; net P&L dan drawdown tidak dievaluasi.');
    } catch (_) {
      if (token === generation) { output.replaceChildren(); status.textContent = 'Laporan ditolak. Pilih JSON UTF-8 diagnostik DEMO v1 yang kompatibel, maksimal 128 KiB. File malformed, field duplikat dan flag eksekusi aktif ditolak.'; }
    } finally { if (token === generation) input.value = ''; }
  });
})();
