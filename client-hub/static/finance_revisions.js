(() => {
  'use strict';
  const t = value => window.KilasUI ? window.KilasUI.t(value) : value;
  const navigation = document.querySelector('.finance-primary-navigation');
  const activeNavigation = navigation?.querySelector('[aria-current="page"]');
  if (activeNavigation && window.matchMedia('(max-width:760px)').matches) {
    navigation.scrollLeft += activeNavigation.getBoundingClientRect().left - navigation.getBoundingClientRect().left - 8;
  }
  const form = document.querySelector('[data-finance-entry]');
  if (form) {
    const direction = form.elements.namedItem('direction');
    const refresh = () => {
      const income = direction.value === 'INCOME';
      const personalIncome = form.dataset.personal === 'true' && income;
      const categories = form.querySelector('[data-entry-categories]');
      if (categories) {
        categories.hidden = personalIncome;
        for (const control of categories.querySelectorAll('select,input,button')) control.disabled = personalIncome;
        const category = form.elements.namedItem('category_id');
        if (category) category.required = !personalIncome;
      }
      const description = form.elements.namedItem('description');
      if (description) description.required = personalIncome;
      const dateLabel = form.querySelector('[data-entry-date-label]');
      if (dateLabel) dateLabel.textContent = t(income ? 'Tanggal pemasukan' : 'Tanggal pengeluaran');
      const accountLabel = form.querySelector('label[for="transaction-account"]');
      if (accountLabel) accountLabel.textContent = t(income ? 'Akun penerima' : 'Akun');
      const title = document.querySelector('#add-transaction-dialog h2');
      if (title) title.textContent = t(income ? 'Tambah Pemasukan' : 'Tambah Pengeluaran');
      for (const button of form.querySelectorAll('[data-entry-direction]')) {
        button.setAttribute('aria-pressed', String(button.dataset.entryDirection === direction.value));
      }
    };
    direction.addEventListener('change', refresh);
    for (const button of form.querySelectorAll('[data-entry-direction]')) button.addEventListener('click', () => {
      direction.value = button.dataset.entryDirection;
      direction.dispatchEvent(new Event('change', {bubbles:true}));
    });
    refresh();
  }
  for (const transfer of document.querySelectorAll('[data-internal-transfer]')) {
    const source = transfer.elements.namedItem('from_account_id');
    const target = transfer.elements.namedItem('to_account_id');
    const feedback = transfer.querySelector('[data-transfer-feedback]');
    source.addEventListener('change', () => {
      const currency = source.selectedOptions[0]?.dataset.currency;
      for (const option of target.options) if (option.value) {
        option.disabled = option.value === source.value || (currency && option.dataset.currency !== currency);
      }
      if (target.selectedOptions[0]?.disabled) target.value = '';
      if (feedback) feedback.textContent = currency ? `${t('Nominal')} · ${currency}` : '';
    });
  }
  document.addEventListener('submit', event => {
    const target = event.target.closest?.('[data-finance-once]');
    if (!target) return;
    if (target.dataset.pending === 'true') {
      event.preventDefault();
      return;
    }
    target.dataset.pending = 'true';
    target.setAttribute('aria-busy', 'true');
    for (const button of target.querySelectorAll('button[type="submit"],button:not([type])')) button.disabled = true;
  });
  window.addEventListener('pageshow', () => {
    for (const target of document.querySelectorAll('[data-finance-once]')) {
      delete target.dataset.pending;
      target.removeAttribute('aria-busy');
      for (const button of target.querySelectorAll('button[type="submit"],button:not([type])')) button.disabled = false;
    }
  });
})();
