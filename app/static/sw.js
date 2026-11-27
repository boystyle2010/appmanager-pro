// AppManager Pro — service worker cho Web Push (0.25). Chỉ nhận thông báo đẩy và mở app khi bấm; không lưu đệm trang.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (_) { d = { title: 'AppManager Pro', body: event.data ? event.data.text() : '' }; }
  const title = d.title || 'AppManager Pro';
  const opts = {
    body: d.body || '',
    icon: '/assets/icon.png?v=2',
    badge: '/assets/icon.png?v=2',
    tag: d.tag || 'appmanager',
    renotify: true,
    timestamp: (d.ts || Math.floor(Date.now() / 1000)) * 1000,
    data: { url: d.url || '/' },
  };
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) {
      if (new URL(c.url).origin === self.location.origin && 'focus' in c) { await c.focus(); if ('navigate' in c) c.navigate(url).catch(() => {}); return; }
    }
    if (self.clients.openWindow) await self.clients.openWindow(url);
  })());
});
