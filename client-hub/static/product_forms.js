"use strict";
for (const form of document.querySelectorAll('form')) {
  if (form.method.toLowerCase() !== 'post') continue;
  let submitting = false;
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    submitting = true;
    form.setAttribute('aria-busy','true');
    const status = document.createElement('p');
    status.setAttribute('role','status');
    status.textContent = 'Memproses. Jika koneksi terputus, periksa status sebelum mengulang tindakan yang sama.';
    form.append(status);
  });
}
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
