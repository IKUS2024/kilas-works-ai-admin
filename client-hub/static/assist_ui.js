/* Feedback for native Assist forms. Preserve named submitters and existing AJAX handlers. */
(function () {
  const root = document.querySelector('[data-assist-ui]') || document.querySelector('.assist-auth');
  if (!root) return;
  document.addEventListener('submit', function (event) {
    const form = event.target;
    if (!root.contains(form) || event.defaultPrevented || form.method.toLowerCase() !== 'post') return;
    let status = form.querySelector('[data-assist-submit-status]');
    if (!status) {
      status = document.createElement('span');
      status.className = 'assist-submit-status';
      status.dataset.assistSubmitStatus = '';
      status.setAttribute('role', 'status');
      form.appendChild(status);
    }
    status.textContent = 'Sedang diproses…';
  });
  window.addEventListener('pageshow', function () {
    root.querySelectorAll('[data-assist-submit-status]').forEach(function (node) { node.remove(); });
  });
}());
