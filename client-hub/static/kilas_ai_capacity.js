/* Native dialog supplies focus trapping, Escape and focus restoration. */
(() => {
  const dialog = document.getElementById('capacity-dialog');
  if (!dialog) return;
  document.querySelectorAll('[data-capacity-open]').forEach(button => {
    button.addEventListener('click', () => dialog.showModal());
  });
  if (new URLSearchParams(location.search).get('capacity') === '1') dialog.showModal();
  dialog.querySelector('[data-capacity-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  });
  dialog.querySelector('[data-capacity-form]').addEventListener('submit', () => {
    const button = dialog.querySelector('[data-capacity-submit]');
    button.disabled = true;
    button.textContent = button.dataset.loadingLabel;
  });
})();
