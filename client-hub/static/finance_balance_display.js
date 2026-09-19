
'use strict';
for (const card of document.querySelectorAll('[data-cash-position-card]')) {
  const select=card.querySelector('[data-cash-display-currency]');
  const value=card.querySelector('[data-cash-display-value]');
  const label=card.querySelector('[data-cash-display-label]');
  const warning=card.querySelector('[data-cash-display-warning]');
  const rates=card.querySelector('[data-cash-display-rates]');
  const source=card.querySelector('[data-cash-display-data]');
  if(!select||!value||!label||!warning||!source)continue;
  let displays;
  try{displays=JSON.parse(source.textContent);}catch(_){continue;}
  const refresh=()=>{
    const view=displays[select.value];
    if(!view)return;
    value.textContent=(view.estimated&&view.complete?'≈ ':'')+view.value;
    label.textContent=view.label;
    warning.hidden=!!view.complete;
    if(rates)rates.textContent=view.rates||'';
    for(const field of document.querySelectorAll('[name="display_currency"]'))field.value=select.value;
    try{
      const url=new URL(window.location.href);
      url.searchParams.set('display_currency',select.value);
      window.history.replaceState(null,'',url);
    }catch(_){}
  };
  select.addEventListener('change',refresh);
  refresh();
}
