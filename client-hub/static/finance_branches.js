'use strict';
for (const category of document.querySelectorAll('[data-other-category]')) {
  const form = category.closest('form');
  const kind = form.querySelector('[name="direction"]');
  const other = form.querySelector('[data-other-field]');
  function refresh() {
    for (const option of category.options) {
      if (kind && option.dataset.direction) {
        option.disabled = option.dataset.direction !== kind.value;
        option.hidden = option.disabled;
      }
    }
    if (!category.selectedOptions.length || category.selectedOptions[0].disabled) {
      const available = [...category.options].find(option => !option.disabled);
      if (available) category.value = available.value;
    }
    const visible = category.selectedOptions[0]?.dataset.other === 'true';
    other.hidden = !visible;
    if (other.style) other.style.display = visible ? '' : 'none';
    const otherInput = other.querySelector('input');
    otherInput.required = visible;
    otherInput.disabled = !visible;
  }
  category.addEventListener('change', refresh);
  if (kind) kind.addEventListener('change', refresh);
  refresh();
}

for (const amount of document.querySelectorAll('[data-idr-input]')) {
  function formatAmount() {
    const signed = amount.dataset?.idrSigned === 'true';
    const negative = signed && /^\s*-/.test(String(amount.value || ''));
    let digits = String(amount.value || '').replace(/\D/g, '').slice(0, 19);
    digits = digits.replace(/^0+(?=\d)/, '');
    if (!digits) {
      amount.value = negative ? '-' : '';
      return;
    }
    amount.value = (negative ? '-' : '') + digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }
  amount.addEventListener('input', formatAmount);
  amount.addEventListener('blur', formatAmount);
  formatAmount();
}


// Compact Finance mobile UI: open forms/settings as bottom-sheet dialogs instead of
// keeping every form expanded in the page flow. No financial state is stored client-side.
for (const trigger of document.querySelectorAll('[data-finance-open]')) {
  const id = trigger.dataset && trigger.dataset.financeOpen;
  if (!id) continue;
  trigger.addEventListener('click', () => {
    const dialog = document.getElementById && document.getElementById(id);
    if (!dialog) return;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    const focusable = dialog.querySelector && dialog.querySelector('input:not([type="hidden"]),select,textarea,button');
    if (focusable && typeof focusable.focus === 'function') focusable.focus({preventScroll:true});
  });
}
for (const trigger of document.querySelectorAll('[data-finance-close]')) {
  const id = trigger.dataset && trigger.dataset.financeClose;
  if (!id) continue;
  trigger.addEventListener('click', () => {
    const dialog = document.getElementById && document.getElementById(id);
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  });
}
for (const dialog of document.querySelectorAll('dialog.finance-sheet')) {
  if (typeof dialog.showModal !== 'function') continue;
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
}
