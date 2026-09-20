(() => {
  'use strict';
  const configEl = document.getElementById('platform-wa-config');
  const button = document.getElementById('platform-wa-signup');
  const status = document.getElementById('platform-wa-status');
  if (!configEl || !button || !status) return;
  const config = JSON.parse(configEl.textContent);
  let code = null, assets = null, started = false, sent = false;

  const failed = (message) => {
    started = false;
    code = assets = null;
    button.disabled = false;
    status.textContent = message || 'Coexistence belum selesai. Coba lagi setelah memastikan WhatsApp Business HP aktif.';
  };

  async function complete() {
    if (!started || sent || !code || !assets || !assets.waba_id) return;
    sent = true;
    status.textContent = 'Memverifikasi Coexistence…';
    try {
      const response = await fetch(config.endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': document.getElementById('platform-wa-csrf').value
        },
        body: JSON.stringify({
          state: config.state,
          code,
          waba_id: assets.waba_id,
          phone_number_id: assets.phone_number_id || null,
          coexistence: true
        })
      });
      const result = await response.json();
      code = assets = null;
      if (!response.ok) {
        sent = false;
        failed(result.error);
        return;
      }
      status.textContent = result.message;
      button.disabled = true;
    } catch (_) {
      sent = false;
      failed('Koneksi ke server gagal. Muat ulang halaman sebelum mencoba lagi.');
    }
  }

  window.addEventListener('message', event => {
    if (!started || sent || !['https://www.facebook.com', 'https://web.facebook.com'].includes(event.origin)) return;
    try {
      const result = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      if (!result || result.type !== 'WA_EMBEDDED_SIGNUP') return;
      const eventName = String(result.event || '');
      const coexistence = eventName === 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING' ||
        (eventName === 'FINISH' && result.data && result.data.is_wa_login_user === true);
      if (coexistence && result.data && result.data.waba_id) {
        assets = {
          waba_id: String(result.data.waba_id),
          phone_number_id: result.data.phone_number_id ? String(result.data.phone_number_id) : null
        };
        complete();
      } else if (eventName === 'CANCEL' || eventName === 'ERROR' || eventName.startsWith('FINISH')) {
        failed('Meta belum menyelesaikan mode WhatsApp Business App Coexistence.');
      }
    } catch (_) {}
  });

  window.fbAsyncInit = () => {
    FB.init({appId: config.appId, version: config.version, cookie: false, xfbml: false});
    button.disabled = false;
    status.textContent = 'Siap. Pastikan WhatsApp Business HP sudah aktif, lalu hubungkan.';
  };

  button.addEventListener('click', () => {
    if (started || sent) return;
    started = true;
    button.disabled = true;
    status.textContent = 'Selesaikan langkah Meta/QR di jendela yang muncul.';
    FB.login(response => {
      if (!started) return;
      if (!response.authResponse || !response.authResponse.code) {
        failed('Login Meta dibatalkan atau tidak selesai.');
        return;
      }
      code = response.authResponse.code;
      complete();
    }, {
      config_id: config.configId,
      response_type: 'code',
      override_default_response_type: true,
      extras: {
        setup: {},
        featureType: 'whatsapp_business_app_onboarding',
        sessionInfoVersion: '3'
      }
    });
  });

  const sdk = document.createElement('script');
  sdk.src = 'https://connect.facebook.net/id_ID/sdk.js';
  sdk.async = true;
  sdk.onerror = () => failed('Facebook SDK gagal dimuat. Muat ulang halaman.');
  document.head.appendChild(sdk);
})();
