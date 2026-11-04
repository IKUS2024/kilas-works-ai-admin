(() => {
  const currency = value => 'Rp' + Number(value).toLocaleString('id-ID');
  const addon = document.querySelector('#addon');
  function updateSummary() {
    const option = addon.selectedOptions[0], amount = Number(option.dataset.amount);
    document.querySelector('#addon-summary').hidden = !amount;
    document.querySelector('.total').hidden = !amount;
    document.querySelector('#addon-name').textContent = option.textContent.split(' · ')[0];
    document.querySelector('#addon-price').textContent = currency(amount);
    document.querySelector('#total').textContent = currency(Number(addon.dataset.base) + amount);
    document.querySelectorAll('[data-signin]').forEach(link => {const url = new URL(link.href);url.searchParams.set('addon', addon.value);link.href = url.href;});
  }
  if (addon) { addon.addEventListener('change', updateSummary); updateSummary(); }
  const copy = document.querySelector('[data-account]');
  if (copy) copy.addEventListener('click', async () => {
    const status = document.querySelector('#copy-status');
    try { await navigator.clipboard.writeText(copy.dataset.account); status.textContent = 'Nomor rekening disalin.'; }
    catch (_) {
      const selection = window.getSelection(), range = document.createRange();
      range.selectNodeContents(document.querySelector('#account-number'));
      selection.removeAllRanges(); selection.addRange(range);
      status.textContent = 'Nomor rekening dipilih. Gunakan menu Salin perangkat Anda.';
    }
  });
  const file = document.querySelector('#proof'), status = document.querySelector('#file-status');
  if (file) file.addEventListener('change', () => {
    const chosen = file.files[0]; file.setCustomValidity('');
    if (!chosen) { status.textContent = ''; return; }
    const error = chosen.size > 5 * 1024 * 1024 ? 'Ukuran foto maksimal 5 MB.' : !['image/jpeg', 'image/png'].includes(chosen.type) ? 'Pilih foto PNG atau JPEG.' : '';
    file.setCustomValidity(error); status.textContent = error || chosen.name;
  });
  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', () => {
    if (!form.checkValidity()) return;
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.disabled = true; button.dataset.label = button.innerHTML; button.textContent = 'Menyimpan…'; }
  }));
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('button[data-label]').forEach(button => {button.disabled = false; button.innerHTML = button.dataset.label;});
  });
  document.querySelector('.error')?.focus();
})();
