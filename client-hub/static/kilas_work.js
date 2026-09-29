document.querySelectorAll('.work-browser-shot').forEach((image) => {
  image.addEventListener('click', (event) => {
    const box = image.getBoundingClientRect();
    const card = image.closest('.work-job');
    const form = card && card.querySelector('.work-manual-click');
    if (!form || !box.width || !box.height) return;
    const x = Math.max(0, Math.min(1279, Math.round((event.clientX - box.left) * 1280 / box.width)));
    const y = Math.max(0, Math.min(799, Math.round((event.clientY - box.top) * 800 / box.height)));
    form.elements.x.value = String(x);
    form.elements.y.value = String(y);
    image.title = 'Posisi dipilih. Tekan “Klik posisi yang dipilih”.';
  });
});
const menuButton = document.querySelector('.work-menu');
const mobileNav = document.querySelector('#work-mobile-nav');
if (menuButton && mobileNav) menuButton.addEventListener('click', () => {
  const open = menuButton.getAttribute('aria-expanded') !== 'true';
  menuButton.setAttribute('aria-expanded', String(open));
  mobileNav.hidden = !open;
});
const labels = {RUNNING:'Mengerjakan…',PAUSED_USER:'Menunggu tindakan kamu',PAUSED_CONFIRM:'Menunggu konfirmasi kamu',PAUSED_QUOTA:'Kuota perlu ditambah',COMPLETED:'Selesai',FAILED:'Belum berhasil',CANCELLED:'Dibatalkan'};
const activeJobs = [...document.querySelectorAll('.work-job[data-status="RUNNING"]')];
if (activeJobs.length) {
  const poll = async () => {
    if (document.hidden) return;
    for (const card of activeJobs) {
      try {
        const response = await fetch(card.dataset.statusUrl, {credentials:'same-origin', cache:'no-store'});
        if (!response.ok) continue;
        const result = await response.json();
        if (result.status && result.status !== card.dataset.status) {
          card.dataset.status = result.status;
          card.querySelector('.work-job-status').textContent = labels[result.status] || result.status;
          if (result.status !== 'RUNNING' && document.activeElement?.id !== 'work-message') location.reload();
        }
      } catch (_) { /* Temporary network loss: leave the last known status visible. */ }
    }
  };
  setInterval(poll, 4000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
}
