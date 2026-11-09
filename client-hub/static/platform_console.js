// Presentation-only repeat-click guard. Billing service locks remain authoritative.
document.querySelectorAll('[data-payment-review]').forEach(function (form) {
  form.addEventListener('submit', function (event) {
    if (form.dataset.submitting === 'true') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    form.setAttribute('aria-busy', 'true');
    if (event.submitter) event.submitter.textContent = 'Memproses…';
    // Keep submitter enabled while the browser serializes its decision value.
    form.querySelectorAll('button').forEach(function (button) {
      button.setAttribute('aria-disabled', 'true');
    });
  });
});
// A browser back/forward cache restore must not leave a form visually locked.
window.addEventListener('pageshow', function (event) {
  if (event.persisted) window.location.reload();
});
