// First Automation visit only: capture the browser's IANA timezone as the account default.
const timezoneForm = document.querySelector('#auto-timezone-form[data-detect="1"]');
if (timezoneForm) {
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (detected && /^(?:[A-Za-z_]+(?:\/[A-Za-z_+-]+)+|UTC)$/.test(detected)) {
    timezoneForm.querySelector('input[name="timezone"]').value = detected;
    timezoneForm.requestSubmit();
  }
}
const timezoneInput = document.querySelector('#auto-timezone[data-detect="1"]');
if (timezoneInput) {
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (detected && /^(?:[A-Za-z_]+(?:\/[A-Za-z_+-]+)+|UTC)$/.test(detected)) timezoneInput.value = detected;
}
document.querySelectorAll('form[data-confirm-delete="1"]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm('Hapus Automation ini? Hasil yang sudah ada tetap tersimpan.')) event.preventDefault();
  });
});
