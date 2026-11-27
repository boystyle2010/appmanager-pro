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
    badge: '/assets/badge.png?v=1',  // Android: biểu tượng nhỏ đơn sắc trên thanh trạng thái
    tag: d.tag || 'appmanager',
    renotify: true,
    timestamp: (d.ts || Math.floor(Date.now() / 1000)) * 1000,
    lang: d.lang || undefined,
    data: { url: d.url || '/' },
  };
  const jobs = [self.registration.showNotification(title, opts)];
  // Số trên biểu tượng app ở màn hình chính (như App Store): số app đang có bản cập nhật
  if (typeof d.badge === 'number' && self.navigator.setAppBadge) {
    jobs.push((d.badge > 0 ? self.navigator.setAppBadge(d.badge) : self.navigator.clearAppBadge()).catch(() => {}));
  }
  event.waitUntil(Promise.all(jobs));
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
