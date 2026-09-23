"use strict";
for (const form of document.querySelectorAll('form')) {
  if (form.method.toLowerCase() !== 'post') continue;
  let submitting = false;
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    submitting = true;
    form.setAttribute('aria-busy','true');
  });
}
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
