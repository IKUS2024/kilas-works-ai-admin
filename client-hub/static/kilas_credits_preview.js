/* Design interactions only. No fetch, persistence, pricing or payment submission. */
(() => {
  'use strict';
  const root = document.querySelector('.credits-design-preview');
  if (!root) return;
  const tabs = [...root.querySelectorAll('[data-credits-tab]')];
  function selectTab(tab) {
    tabs.forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
    });
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
      if (event.key === 'ArrowLeft') next = tabs[(index + tabs.length - 1) % tabs.length];
      if (event.key === 'Home') next = tabs[0];
      if (event.key === 'End') next = tabs[tabs.length - 1];
      if (next) { event.preventDefault(); selectTab(next); next.focus(); }
    });
  });
  const currency = root.querySelector('#credits-currency');
  const amount = root.querySelector('#credits-amount');
  const error = root.querySelector('#credits-amount-error');
  const symbol = root.querySelector('[data-credits-currency-symbol]');
  function validate() {
    const value = amount.value.trim();
    const valid = !value || (/^\d+(?:\.\d+)?$/.test(value) && Number(value) > 0);
    amount.setAttribute('aria-invalid', String(!valid));
    error.hidden = valid;
    error.textContent = valid ? '' : amount.dataset.invalidCopy;
    return valid;
  }
  amount.addEventListener('blur', validate);
  amount.addEventListener('input', () => {
    if (amount.getAttribute('aria-invalid') === 'true') validate();
  });
  currency.addEventListener('change', () => {
    symbol.textContent = currency.value === 'IDR' ? 'Rp' : '$';
    // Changing currency never converts or reinterprets the entered amount.
    amount.value = '';
    validate();
  });
})();
