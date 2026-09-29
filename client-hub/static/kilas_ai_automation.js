// First Automation visit only: capture the browser's IANA timezone as the account default.
const timezoneForm = document.querySelector('#auto-timezone-form[data-detect="1"]');
if (timezoneForm) {
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (detected && /^(?:[A-Za-z_]+(?:\/[A-Za-z_+-]+)+|UTC)$/.test(detected)) {
    timezoneForm.querySelector('input[name="timezone"]').value = detected;
    timezoneForm.requestSubmit();
  }
}
