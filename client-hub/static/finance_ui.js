(() => {
  'use strict';
  document.addEventListener('change', event => {
    const input = event.target.closest?.('[data-finance-ui-submit]');
    if (!input?.form) return;
    if (input.form.matches('[data-finance-live-period]')) input.form.requestSubmit();
    else input.form.submit();
  });
  document.addEventListener('click', event => {
    const open = event.target.closest?.('[data-finance-ui-open]');
    const close = event.target.closest?.('[data-finance-ui-close]');
    if (open) {
      const dialog = document.getElementById(open.dataset.financeUiOpen);
      if (dialog && !dialog.open) dialog.showModal();
    }
    if (close) document.getElementById(close.dataset.financeUiClose)?.close();
  });
  // Preserve explicit route context for old GET forms without replacing their handlers.
  const root = document.querySelector('.finance-app');
  if (!root) return;
  for (const form of document.querySelectorAll('.finance-app-main form')) {
    if (form.method.toLowerCase() !== 'get') continue;
    const url = new URL(form.action || location.href, location.href);
    if (url.origin !== location.origin || !url.pathname.includes('/finance')) continue;
    for (const [key,value] of [['month',root.dataset.financeMonth],['display_currency',root.dataset.financeCurrency]]) {
      if (!value || form.elements.namedItem(key) || (key==='month' && form.elements.namedItem('period_month'))) continue;
      const hidden = document.createElement('input');hidden.type='hidden';hidden.name=key;hidden.value=value;form.append(hidden);
    }
  }
})();
