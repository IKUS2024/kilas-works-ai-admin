'use strict';
for (const form of document.querySelectorAll('[data-single-submit]')) {
  form.addEventListener('submit', event => {
    if (form.dataset.submitting === 'true') { event.preventDefault(); return; }
    form.dataset.submitting = 'true';
    const button = form.querySelector('button[type=submit]');
    button.dataset.originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Memproses…';
  });
}
window.addEventListener('pageshow', () => {
  for (const form of document.querySelectorAll('[data-single-submit]')) {
    delete form.dataset.submitting;
    const button = form.querySelector('button[type=submit]');
    button.disabled = false;
    if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel;
  }
});
