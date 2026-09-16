'use strict';
(() => {
  const print = document.getElementById('invoice-print');
  if (print) print.addEventListener('click', () => window.print());
  const copy = document.getElementById('invoice-copy');
  if (copy) copy.addEventListener('click', async () => {
    const input = document.getElementById('invoice-link'), status = document.getElementById('invoice-copy-status');
    try {
      if (!navigator.clipboard) throw new Error('unavailable');
      await navigator.clipboard.writeText(input.value); status.textContent = 'Tautan disalin.';
    } catch (_) { input.focus(); input.select(); status.textContent = 'Pilih dan salin tautan di atas secara manual.'; }
  });
})();
