/* Signup results stay in memory, never localStorage/logs/URLs. Applying Meta result is server-only. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('wa-config').textContent);
  const button = document.getElementById('wa-signup');
  const status = document.getElementById('wa-status');
  let code = null, assets = null, started = false, sent = false;
  const failed = () => {
    started = false;
    code = assets = null;
    button.disabled = true;
    status.textContent = 'Koneksi belum selesai. Muat ulang untuk mencoba lagi atau hubungi Kilas Works.';
  };
  async function complete() {
    if (!started || sent || !code || !assets || !assets.waba_id ||
        (!assets.coexistence && !assets.phone_number_id)) return;
    sent = true;
    status.textContent = 'Menghubungkan WhatsApp…';
    try {
      const response = await fetch(config.endpoint, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.getElementById('wa-csrf').value},
        body: JSON.stringify({
          state: config.state,
          code,
          waba_id: assets.waba_id,
          phone_number_id: assets.phone_number_id || null,
          coexistence: Boolean(assets.coexistence)
        })
      });
      code = assets = null;
      const result = await response.json();
      status.textContent = response.ok ? result.message : (result.error || 'Koneksi belum selesai. Muat ulang untuk mencoba lagi.');
    } catch (_) { failed(); }
  }
  window.addEventListener('message', event => {
    if (!started || sent || !['https://www.facebook.com', 'https://web.facebook.com'].includes(event.origin)) return;
    try {
      const result = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      if (!result || result.type !== 'WA_EMBEDDED_SIGNUP') return;
      const eventName = String(result.event || '');
      const coexistence = eventName === 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING' ||
        (eventName === 'FINISH' && result.data && result.data.is_wa_login_user === true);
      if ((eventName === 'FINISH' || eventName === 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING') &&
          result.data && result.data.waba_id &&
          (coexistence || result.data.phone_number_id)) {
        assets = {
          waba_id: String(result.data.waba_id),
          phone_number_id: result.data.phone_number_id ? String(result.data.phone_number_id) : null,
          coexistence
        };
        complete();
      } else if (eventName === 'CANCEL' || eventName === 'ERROR' || eventName.startsWith('FINISH')) failed();
    } catch (_) { /* Ignore unrelated postMessages; never log their contents. */ }
  });
  window.fbAsyncInit = () => {
    FB.init({appId: config.appId, version: config.version, cookie: false, xfbml: false});
    button.disabled = false;
    status.textContent = 'Siap hubungkan WhatsApp.';
  };
  button.addEventListener('click', () => {
    if (started || sent) return;
    started = true;
    button.disabled = true;
    status.textContent = 'Selesaikan langkah di jendela Meta.';
    FB.login(response => {
      if (!started) return;
      if (!response.authResponse || !response.authResponse.code) { failed(); return; }
      code = response.authResponse.code;
      complete();
    }, {config_id: config.configId, response_type: 'code', override_default_response_type: true,
        extras: {
          setup: {},
          featureType: 'whatsapp_business_app_onboarding'
        }
       });
  });
  const sdk = document.createElement('script');
  sdk.src = 'https://connect.facebook.net/id_ID/sdk.js';
  sdk.async = true;
  sdk.onerror = failed;
  document.head.appendChild(sdk);
})();
