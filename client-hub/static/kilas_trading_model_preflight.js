(() => {
  'use strict';
  const form = document.getElementById('model-preflight-form');
  if (!form) return;
  const button = form.querySelector('button');
  const status = document.getElementById('model-preflight-status');
  const result = document.getElementById('model-preflight-result');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    result.hidden = true;
    status.textContent = 'Checking model catalog access…';
    try {
      const response = await fetch(form.action, {
        method: 'POST', credentials: 'same-origin', redirect: 'error',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': form.elements.csrf_token.value},
        body: '{}'
      });
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      const keys = Object.keys(data).sort().join(',');
      if (keys !== 'checked_at,credential,http_status,model_id_match' ||
          !['PRESENT', 'MISSING'].includes(data.credential) ||
          (data.http_status !== null && (!Number.isInteger(data.http_status) || data.http_status < 100 || data.http_status > 599)) ||
          typeof data.model_id_match !== 'boolean' || typeof data.checked_at !== 'string' ||
          !/^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|\+00:00)$/.test(data.checked_at) || data.checked_at.length > 40)
        throw new Error('invalid');
      document.getElementById('model-credential').textContent = data.credential;
      document.getElementById('model-http').textContent = data.http_status === null ? 'Unavailable' : String(data.http_status);
      document.getElementById('model-match').textContent = data.model_id_match ? 'Yes' : 'No';
      document.getElementById('model-checked').textContent = data.checked_at;
      result.hidden = false;
      status.textContent = 'Catalog check complete. The DEMO robot remains OFF.';
    } catch (_) {
      status.textContent = 'Check unavailable. Reload this page before trying again.';
    } finally {
      button.disabled = false;
    }
  });
})();
