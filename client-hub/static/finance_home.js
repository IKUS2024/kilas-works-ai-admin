(() => {
  'use strict';
  const data = document.getElementById('finance-trend-data');
  const chart = document.getElementById('finance-trend-chart');
  if (!data || !chart) return;
  const items = JSON.parse(data.textContent);
  const ns = 'http://www.w3.org/2000/svg';
  function node(tag, attrs, text) {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    if (text !== undefined) el.textContent = text;
    return el;
  }
  const currency = items[0]?.currency || 'IDR';
  const max = Math.max(1, ...items.flatMap(row => [row.income_minor, row.expense_minor]));
  const svg = node('svg', {viewBox:'0 0 480 200', role:'img',
    'aria-label':`Pemasukan dan pengeluaran enam bulan dalam ${currency}, dikonversi memakai kurs referensi terbaru.`});
  const format = value => new Intl.NumberFormat('id-ID', {notation:'compact', maximumFractionDigits:1})
    .format(value / (['IDR','JPY'].includes(currency) ? 1 : 100));
  [0,.5,1].forEach(level => {
    const y = 155 - level * 120;
    svg.append(node('line',{x1:55,x2:475,y1:y,y2:y,stroke:'currentColor',opacity:'.12'}));
    svg.append(node('text',{x:49,y:y+4,'text-anchor':'end',fill:'currentColor',opacity:'.6','font-size':10},format(max*level)));
  });
  items.forEach((row,index) => {
    const x = 88 + index * 70;
    ['income_minor','expense_minor'].forEach((key,j) => {
      const height = row[key] / max * 120;
      const rect = node('rect',{x:x-18+j*19,y:155-height,width:14,height,rx:3,fill:j ? '#969da8' : 'var(--orange)'});
      rect.append(node('title',{},`${row.month} ${j ? 'Pengeluaran' : 'Pemasukan'}: ${format(row[key])} ${currency}`));
      svg.append(rect);
    });
    const label = new Intl.DateTimeFormat('id-ID',{month:'short',timeZone:'UTC'}).format(new Date(`${row.month}-01T00:00:00Z`));
    svg.append(node('text',{x,y:180,'text-anchor':'middle',fill:'currentColor',opacity:'.65','font-size':11},label));
  });
  chart.replaceChildren(svg);
  const empty=document.getElementById('finance-trend-empty');
  if(empty) empty.hidden=items.some(row=>row.income_minor||row.expense_minor);
})();