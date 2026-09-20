'use strict';
(() => {
  document.querySelectorAll('[data-cashflow-card]').forEach(card => {
    const buttons=Array.from(card.querySelectorAll('[data-cashflow-currency]'));
    const blocks=Array.from(card.querySelectorAll('[data-cashflow-block]'));
    if(!buttons.length)return;
    const apply=currency=>{
      buttons.forEach(button=>{
        const active=button.dataset.cashflowCurrency===currency;
        button.classList.toggle('active',active);
        button.setAttribute('aria-selected',String(active));
      });
      blocks.forEach(block=>{block.hidden=block.dataset.cashflowBlock!==currency;});
      for(const field of document.querySelectorAll('[name="display_currency"]'))field.value=currency;
      try{
        const url=new URL(window.location.href);
        url.searchParams.set('display_currency',currency);
        window.history.replaceState(null,'',url);
      }catch(_){}
    };
    buttons.forEach(button=>button.addEventListener('click',()=>apply(button.dataset.cashflowCurrency)));
    const current=buttons.find(button=>button.classList.contains('active'))||buttons[0];
    apply(current.dataset.cashflowCurrency);
  });
})();
