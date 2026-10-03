'use strict';
const t=(message, values)=>window.KilasUI ? window.KilasUI.t(message, values) : message;
document.querySelectorAll('[data-copy-target]').forEach(button => {
  button.addEventListener('click', async () => {
    const input=document.getElementById(button.dataset.copyTarget);
    const status=document.getElementById('copy-status');
    try {
      if (!navigator.clipboard) throw new Error('unavailable');
      await navigator.clipboard.writeText(input.value);
      status.textContent=t('Teks disalin. Belum dikirim ke customer.');
    } catch (_) {
      input.focus(); input.select();
      status.textContent=t('Pilih dan salin teks di atas secara manual. Belum ada pengiriman.');
    }
  });
});
