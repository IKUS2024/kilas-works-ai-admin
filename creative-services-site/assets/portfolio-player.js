/* One user-initiated, provider-hosted player. No downloaded video is implied. */
(() => {
  'use strict';
  const dialog = document.querySelector('#cs-video-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const stage = dialog.querySelector('#cs-player-stage');
  const title = dialog.querySelector('#cs-player-title');
  const provider = dialog.querySelector('#cs-player-provider');
  const status = dialog.querySelector('#cs-player-status');
  const closeButton = dialog.querySelector('[data-player-close]');
  let selected = null;
  let frame = null;
  let timeout = null;
  let state = 'loading';
  const language = () => document.documentElement.lang === 'en' ? 'en' : 'id';

  function sourceFor(card) {
    // Only the original, explicitly supported public provider URLs are embedded.
    try {
      const url = new URL(card.dataset.videoSource);
      if (url.protocol !== 'https:') return null;
      const drive = url.pathname.match(/^\/file\/d\/([\w-]+)\/view$/);
      if (url.hostname === 'drive.google.com' && drive) {
        return {name: 'Google Drive', kind: 'drive', url: `https://drive.google.com/file/d/${drive[1]}/preview`};
      }
      const instagram = url.pathname.match(/^\/(reel|tv)\/([\w-]+)\/$/);
      if (['instagram.com', 'www.instagram.com'].includes(url.hostname) && instagram) {
        return {name: 'Instagram', kind: 'instagram', url: `https://www.instagram.com/${instagram[1]}/${instagram[2]}/embed/`};
      }
    } catch (_) { /* Leave unsupported cards disabled. */ }
    return null;
  }

  function labelFor(card) {
    return card.querySelector('.cs-video-caption > span').textContent.trim();
  }

  function updateLanguage() {
    const en = language() === 'en';
    document.querySelectorAll('.cs-video-card').forEach(card => {
      const source = sourceFor(card);
      if (source) card.setAttribute('aria-label', `${en ? 'Open' : 'Buka'} ${labelFor(card)} · ${source.name} ${en ? 'player on this page' : 'di pemutar halaman ini'}`);
    });
    if (!selected) return;
    const source = sourceFor(selected);
    title.textContent = labelFor(selected);
    provider.textContent = `${source.name} · ${en ? 'Embedded player' : 'Pemutar sematan'}`;
    if (frame) frame.title = `${labelFor(selected)} · ${source.name}`;
    const messages = en ? {
      loading: `Loading the ${source.name} player…`,
      loaded: 'If the video appears, press play inside the player. Video access is controlled by the provider.',
      timeout: 'Player availability could not be confirmed. Check your connection or retry. The provider may restrict this video.',
      error: 'The player could not load. Check your connection or retry.'
    } : {
      loading: `Memuat pemutar ${source.name}…`,
      loaded: 'Jika video muncul, tekan play di pemutar. Akses video ditentukan oleh penyedia.',
      timeout: 'Ketersediaan pemutar belum terkonfirmasi. Periksa koneksi atau coba muat ulang. Penyedia mungkin membatasi video ini.',
      error: 'Pemutar gagal dimuat. Periksa koneksi atau coba muat ulang.'
    };
    status.textContent = messages[state];
    dialog.dataset.playerState = state;
  }

  function clearPlayer() {
    window.clearTimeout(timeout);
    // Removing the browsing context stops its video/audio, including cross-origin media.
    // Do this on every close/retry/switch; never retain hidden playing iframes.
    if (frame) frame.remove();
    frame = null;
    stage.replaceChildren();
    stage.setAttribute('aria-busy', 'false');
    stage.style.removeProperty('height');
    stage.hidden = true;
  }

  function loadPlayer() {
    clearPlayer();
    const source = sourceFor(selected);
    if (!source) return;
    state = 'loading';
    stage.dataset.provider = source.kind;
    stage.hidden = false;
    stage.setAttribute('aria-busy', 'true');
    const nextFrame = document.createElement('iframe');
    frame = nextFrame;
    nextFrame.title = `${labelFor(selected)} · ${source.name}`;
    nextFrame.allow = 'fullscreen; picture-in-picture; encrypted-media';
    nextFrame.allowFullscreen = true;
    // Provider links cannot replace the Kilas page or open another tab.
    nextFrame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
    nextFrame.referrerPolicy = 'strict-origin-when-cross-origin';
    nextFrame.addEventListener('load', () => {
      if (frame !== nextFrame) return;
      window.clearTimeout(timeout);
      stage.setAttribute('aria-busy', 'false');
      // A cross-origin iframe load is NOT confirmation that the video is playable.
      state = 'loaded';
      updateLanguage();
    });
    nextFrame.addEventListener('error', () => {
      if (frame !== nextFrame) return;
      clearPlayer();
      state = 'error';
      updateLanguage();
    });
    timeout = window.setTimeout(() => {
      if (frame !== nextFrame) return;
      clearPlayer();
      state = 'timeout';
      updateLanguage();
    }, 12000);
    // No request is made for any video/provider until its card is activated.
    nextFrame.src = source.url;
    stage.append(nextFrame);
    updateLanguage();
  }

  function openPlayer(card) {
    if (!sourceFor(card)) return;
    selected = card;
    if (!dialog.open) dialog.showModal();
    document.documentElement.classList.add('cs-player-open');
    dialog.scrollTop = 0;
    closeButton.focus({preventScroll: true});
    loadPlayer();
  }

  document.querySelectorAll('.cs-video-card').forEach(card => {
    if (!sourceFor(card)) return;
    card.disabled = false;
    card.addEventListener('click', () => openPlayer(card));
  });
  closeButton.addEventListener('click', () => dialog.close());
  dialog.querySelector('[data-player-retry]').addEventListener('click', loadPlayer);
  dialog.addEventListener('close', () => {
    const previous = selected;
    clearPlayer();
    selected = null;
    document.documentElement.classList.remove('cs-player-open');
    if (previous && previous.isConnected && previous.getClientRects().length) previous.focus({preventScroll: true});
  });
  // Native dialog supplies Escape, inert background and keyboard focus containment.
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  window.addEventListener('hashchange', () => { if (dialog.open) dialog.close(); });
  window.addEventListener('pagehide', () => {
    if (dialog.open) dialog.close();
    clearPlayer();
  });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-cs-language]')) updateLanguage();
  });
  // Official Instagram embeds may report their measured post height. Only accept
  // bounded resize messages from the currently mounted, known provider frame.
  window.addEventListener('message', event => {
    if (!frame || event.source !== frame.contentWindow || event.origin !== 'https://www.instagram.com') return;
    let data = event.data;
    try { if (typeof data === 'string') data = JSON.parse(data); } catch (_) { return; }
    if (!data || data.type !== 'MEASURE') return;
    const height = Number(data.details && data.details.height);
    if (Number.isFinite(height) && height >= 240 && height <= 1600) stage.style.height = Math.ceil(height) + 'px';
  });
  updateLanguage();
})();
