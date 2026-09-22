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
    let items;
    try { items = JSON.parse(data.textContent || '[]'); } catch (_) { return; }
    if (!items.length || !items.some(row => row.income_minor || row.expense_minor) || items.some(row => row.income_minor === null || row.expense_minor === null)) {
      chart.replaceChildren(); return;
    }
    const currency = items[0].currency;
    const divisor = Number(chart.dataset.divisor) || 100;
    const max = Math.max(1, ...items.flatMap(row => [row.income_minor, row.expense_minor]));
    const width = 780, left = 64, bottom = 175, height = 140;
    const step = (width-left-8) / items.length;
    const barWidth = Math.min(24, step * .3);
    const svg = svgNode('svg', {viewBox:`0 0 ${width} 208`, role:'img',
      'aria-label':`Pemasukan dan pengeluaran ${items.length} bulan dalam ${currency}. Rincian tersedia pada tabel.`});
    const format = value => new Intl.NumberFormat('id-ID', {notation:'compact', maximumFractionDigits:1}).format(value/divisor);
    [0,.25,.5,.75,1].forEach(level => {
      const y = bottom - level * height;
      svg.append(svgNode('line',{x1:left,x2:width-8,y1:y,y2:y,stroke:'currentColor',opacity:'.1'}));
      svg.append(svgNode('text',{x:left-9,y:y+4,'text-anchor':'end',fill:'currentColor',opacity:'.65','font-size':11},format(max*level)));
    });
    items.forEach((row,index) => {
      const x = left + step*(index+.5);
      [{key:'income_minor',label:'Pemasukan',color:'var(--green)'},
       {key:'expense_minor',label:'Pengeluaran',color:'var(--red)'}].forEach((series,j) => {
        const value = row[series.key], h = value/max*height;
        const rect = svgNode('rect',{x:x+(j-1)*(barWidth+3),y:bottom-h,width:barWidth,height:h,rx:1,fill:series.color});
        rect.append(svgNode('title',{},`${row.month} ${series.label}: ${format(value)} ${currency}`));
        svg.append(rect);
      });
      const label = new Intl.DateTimeFormat('id-ID',{month:'short',year:items.length<=6?'numeric':undefined,timeZone:'UTC'})
        .format(new Date(`${row.month}-01T00:00:00Z`));
      svg.append(svgNode('text',{x,y:198,'text-anchor':'middle',fill:'currentColor',opacity:'.8','font-size':11},label));
    });
    chart.replaceChildren(svg);
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
    const activeController = controller;
    setLoading(true);
    try {
      const response = await fetch(url, {
        method:'GET',
        credentials:'same-origin',
        headers:{'X-Requested-With':'fetch','Accept':'text/html'},
        signal:activeController.signal
      });
      if (!response.ok) throw new Error('finance_live_http_' + response.status);
      const html = await response.text();
      const incoming = new DOMParser().parseFromString(html, 'text/html');
      if (!incoming.querySelector(homeSelector)) throw new Error('finance_live_fragment_missing');

      syncMonthNav(incoming);
      for (const selector of ['.finance-dashboard-data', '.finance-dashboard-currency', '.finance-dashboard-search-results', '.finance-dashboard-sidebar']) swap(selector, incoming);
      // Keep the live dialog's existing change listeners; update values, not script-bearing HTML.
      const currentPeriod = document.querySelector('#period-dialog form');
      const nextPeriod = incoming.querySelector('#period-dialog form');
      if (currentPeriod && nextPeriod) {
        for (const field of currentPeriod.elements) {
          const next = nextPeriod.elements.namedItem(field.name);
          if (next && field.name) field.value = next.value;
        }
        currentPeriod.querySelector('[name="period_mode"]')?.dispatchEvent(new Event('change', {bubbles:true}));
      }
      const search = document.querySelector('.finance-dashboard-search');
      const nextSearch = incoming.querySelector('.finance-dashboard-search');
      if (search && nextSearch) for (const field of search.elements) {
        const next = nextSearch.elements.namedItem(field.name);
        if (next && field.name) field.value = next.value;
      }
      for (const field of document.querySelectorAll('.finance-dashboard-context input[type="hidden"]')) {
        const next = incoming.querySelector(`.finance-dashboard-context input[name="${field.name}"]`);
        if (next) field.value = next.value;
      }
      const periodDialog = document.getElementById('period-dialog');
      if (periodDialog?.open && typeof periodDialog.close === 'function') periodDialog.close();

      if (push) history.pushState({financeLive:true}, '', url);
      renderChart();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      window.location.assign(url);
    } finally {
      if (controller === activeController) setLoading(false);
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
    const select = event.target.closest?.('[data-finance-live-currency], [data-dashboard-period]');
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
    const open = event.target.closest?.('[data-dashboard-open]');
    if (open) {
      const dialog = document.getElementById(open.dataset.dashboardOpen);
      if (dialog && !dialog.open) dialog.showModal();
    }
    const close = event.target.closest?.('[data-dashboard-close]');
    if (close) document.getElementById(close.dataset.dashboardClose)?.close();
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