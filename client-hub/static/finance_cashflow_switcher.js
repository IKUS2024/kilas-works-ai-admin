'use strict';
(() => {
  document.querySelectorAll('[data-cashflow-card]').forEach(card => {
    const select = card.querySelector('[data-cashflow-currency]');
    if (!select) return;
    const blocks = Array.from(card.querySelectorAll('[data-cashflow-block]'));
    const apply = () => {
      blocks.forEach(block => {
        block.hidden = block.dataset.cashflowBlock !== select.value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });
})();
