/* Notifications only: no fetch interception, caching or background browser execution. */
self.addEventListener('push', event => {
  let data;
  try { data = event.data.json(); } catch (_) { return; }
  const target = new URL(data.url || '/kilas-ai/agent', self.location.origin);
  if (target.origin !== self.location.origin || target.pathname !== '/kilas-ai/agent') return;
  event.waitUntil(self.registration.showNotification('Kilas Work', {
    body: String(data.body || 'Pengingat Work').slice(0, 240),
    tag: String(data.tag || 'kilas-work').slice(0, 100),
    data: {url: target.href}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/kilas-ai/agent', self.location.origin);
  if (target.origin !== self.location.origin || target.pathname !== '/kilas-ai/agent') return;
  event.waitUntil(clients.matchAll({type:'window', includeUncontrolled:true}).then(async windows => {
    const existing = windows.find(window => window.url === target.href);
    if (existing) return existing.focus();
    return clients.openWindow(target.href);
  }));
});
