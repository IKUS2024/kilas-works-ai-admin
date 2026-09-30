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
const scheduleForm = document.querySelector('#auto-schedule-form');
if (scheduleForm) {
  const mode = scheduleForm.querySelector('#auto-schedule-mode');
  const date = scheduleForm.querySelector('#auto-run-date');
  const clock = scheduleForm.querySelector('#auto-run-time');
  const zone = scheduleForm.querySelector('#auto-timezone');
  const localNow = () => {
    try {
      const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: zone.value, year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
      }).formatToParts(new Date()).map(part => [part.type, part.value]));
      return {date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}`};
    } catch (_) { return null; }
  };
  const refresh = () => {
    scheduleForm.querySelectorAll('.auto-schedule-fields').forEach(group => {
      const visible = group.dataset.for === mode.value || (group.dataset.for === 'clock' && mode.value !== 'natural');
      group.hidden = !visible;
      group.querySelectorAll('input,select').forEach(input => {
        input.disabled = !visible;
        input.required = visible && (input === date || input === clock);
      });
    });
    const now = localNow();
    date.min = now?.date || '';
    clock.min = mode.value === 'once' && now && date.value === now.date ? now.time : '';
    date.setCustomValidity('');
    clock.setCustomValidity('');
  };
  mode.addEventListener('change', refresh);
  zone.addEventListener('change', refresh);
  date.addEventListener('change', refresh);
  clock.addEventListener('change', () => clock.setCustomValidity(''));
  scheduleForm.addEventListener('submit', event => {
    const now = localNow();
    if (mode.value === 'once' && now && date.value && clock.value &&
        (date.value < now.date || (date.value === now.date && clock.value <= now.time))) {
      clock.setCustomValidity('Pilih tanggal dan jam yang belum lewat.');
      clock.reportValidity();
      event.preventDefault();
    }
  });
  refresh();
  setInterval(refresh, 30000);
}
document.querySelectorAll('form[data-confirm-delete="1"]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm('Hapus Automation ini? Hasil yang sudah ada tetap tersimpan.')) event.preventDefault();
  });
});
