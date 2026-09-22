(() => {
  'use strict';

  const homeSelector = '.finance-metric-grid';
  let controller = null;

  function svgNode(tag, attrs, text) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function renderChart() {
    const data = document.getElementById('finance-trend-data');
    const chart = document.getElementById('finance-trend-chart');
    if (!data || !chart) return;
    let items = [];
    try { items = JSON.parse(data.textContent || '[]'); } catch (_) { items = []; }
    const currency = items[0]?.currency || document.querySelector('[data-finance-live-currency]')?.value || 'IDR';
    const max = Math.max(1, ...items.flatMap(row => [
      Number(row.income_minor || 0),
      Number(row.expense_minor || 0),
      Number(row.budget_minor || 0)
    ]));
    const svg = svgNode('svg', {
      viewBox:'0 0 480 200', role:'img',
      'aria-label':`Pemasukan, pengeluaran, dan anggaran enam bulan dalam ${currency}.`
    });
    const format = value => new Intl.NumberFormat('id-ID', {notation:'compact', maximumFractionDigits:1})
      .format(value / (['IDR','JPY'].includes(currency) ? 1 : 100));
    [0,.5,1].forEach(level => {
      const y = 155 - level * 120;
      svg.append(svgNode('line',{x1:55,x2:475,y1:y,y2:y,stroke:'currentColor',opacity:'.12'}));
      svg.append(svgNode('text',{x:49,y:y+4,'text-anchor':'end',fill:'currentColor',opacity:'.6','font-size':10},format(max*level)));
    });
    const series = [
      {key:'income_minor', label:'Pemasukan', fill:'var(--orange)'},
      {key:'expense_minor', label:'Pengeluaran', fill:'#969da8'},
      {key:'budget_minor', label:'Anggaran', fill:'#d8a15f'}
    ];
    items.forEach((row,index) => {
      const x = 88 + index * 70;
      series.forEach((item,j) => {
        const value = Number(row[item.key] || 0);
        const height = value / max * 120;
        const rect = svgNode('rect',{
          x:x-22+j*16,y:155-height,width:12,height,rx:3,fill:item.fill
        });
        rect.append(svgNode('title',{},`${row.month} ${item.label}: ${format(value)} ${currency}`));
        svg.append(rect);
      });
      const label = new Intl.DateTimeFormat('id-ID',{month:'short',timeZone:'UTC'})
        .format(new Date(`${row.month}-01T00:00:00Z`));
      svg.append(svgNode('text',{x,y:180,'text-anchor':'middle',fill:'currentColor',opacity:'.65','font-size':11},label));
    });
    chart.replaceChildren(svg);
    const empty = document.getElementById('finance-trend-empty');
    if (empty) empty.hidden = items.some(row =>
      Number(row.income_minor) || Number(row.expense_minor) || Number(row.budget_minor));
  }

  function setLoading(loading) {
    const page = document.querySelector('.finance-page');
    if (!page) return;
    page.classList.toggle('finance-live-loading', loading);
    page.setAttribute('aria-busy', loading ? 'true' : 'false');
  }

  function syncMonthNav(incoming) {
    const current = document.querySelector('.finance-month-nav');
    const next = incoming.querySelector('.finance-month-nav');
    if (!current || !next) return;
    current.innerHTML = next.innerHTML;
  }

  function swap(selector, incoming) {
    const current = document.querySelector(selector);
    const next = incoming.querySelector(selector);
    if (!current || !next) return;
    current.replaceWith(next);
  }

  async function loadFinance(url, {push=true}={}) {
    if (!document.querySelector(homeSelector)) {
      window.location.assign(url);
      return;
    }
    if (controller) controller.abort();
    controller = new AbortController();
    setLoading(true);
    try {
      const response = await fetch(url, {
        method:'GET',
        credentials:'same-origin',
        headers:{'X-Requested-With':'fetch','Accept':'text/html'},
        signal:controller.signal
      });
      if (!response.ok) throw new Error('finance_live_http_' + response.status);
      const html = await response.text();
      const incoming = new DOMParser().parseFromString(html, 'text/html');
      if (!incoming.querySelector(homeSelector)) throw new Error('finance_live_fragment_missing');

      syncMonthNav(incoming);
      for (const selector of [
        '.finance-metric-grid',
        '.finance-available',
        '.finance-budget-overview',
        '.finance-trend',
        '.finance-ai-home'
      ]) swap(selector, incoming);

      const currentPeriod = document.querySelector('#period-dialog .finance-sheet-body');
      const nextPeriod = incoming.querySelector('#period-dialog .finance-sheet-body');
      if (currentPeriod && nextPeriod) currentPeriod.replaceWith(nextPeriod);

      const periodDialog = document.getElementById('period-dialog');
      if (periodDialog?.open && typeof periodDialog.close === 'function') periodDialog.close();

      if (push) history.pushState({financeLive:true}, '', url);
      renderChart();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      window.location.assign(url);
    } finally {
      setLoading(false);
    }
  }

  function urlFromForm(form) {
    const url = new URL(form.getAttribute('action') || window.location.href, window.location.href);
    const data = new FormData(form);
    url.search = '';
    for (const [key, value] of data.entries()) {
      if (String(value).trim() !== '') url.searchParams.append(key, value);
    }
    return url.toString();
  }

  document.addEventListener('change', event => {
    const select = event.target.closest?.('[data-finance-live-currency]');
    if (!select || !document.querySelector(homeSelector)) return;
    const form = select.closest('form');
    if (!form) return;
    loadFinance(urlFromForm(form));
  });

  document.addEventListener('submit', event => {
    const form = event.target.closest?.('[data-finance-live-period]');
    if (!form || !document.querySelector(homeSelector)) return;
    event.preventDefault();
    loadFinance(urlFromForm(form));
  });

  document.addEventListener('click', event => {
    const monthLink = event.target.closest?.('.finance-month-nav a[href]');
    if (monthLink && document.querySelector(homeSelector)) {
      event.preventDefault();
      loadFinance(monthLink.href);
      return;
    }

    const periodButton = event.target.closest?.('.finance-month-nav [data-finance-open="period-dialog"]');
    if (periodButton) {
      const dialog = document.getElementById('period-dialog');
      if (!dialog || dialog.open) return;
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open','');
    }
  });

  window.addEventListener('popstate', () => {
    if (document.querySelector(homeSelector)) loadFinance(window.location.href, {push:false});
  });

  renderChart();
})();