(() => {
  const notice = document.querySelector('[data-premium-capacity-notice]');
  if (!notice) return;
  let pending = false;
  async function refresh() {
    if (pending || document.hidden) return;
    pending = true;
    try {
      const response = await fetch('/kilas-ai/capacity', {cache:'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      notice.hidden = !state.active || state.state === 'Cukup';
      const copy = notice.querySelector('[data-premium-capacity-copy]');
      copy.textContent = state.state === 'Habis' ? copy.dataset.empty : copy.dataset.low;
    } catch (_) { /* A capacity status failure must never interrupt Chat. */ }
    finally { pending = false; }
  }
  refresh();
  document.addEventListener('kilas:request-finished', refresh);
  window.addEventListener('focus', refresh);
})();
