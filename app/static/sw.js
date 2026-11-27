// AppManager Pro — service worker: Web Push (0.25) + trang báo lỗi khi không kết nối được (không lưu đệm trang).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// Mở trang (app trên màn hình chính) mà máy chủ không trả lời (đang khởi động lại sau cập nhật, mất Wi-Fi…):
// thay vì màn hình đen, hiện trang báo lỗi tự thử lại. KHÔNG lưu đệm gì — trang thật luôn lấy từ mạng.
const OFFLINE_HTML = `<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>AppManager Pro</title>
<style>html,body{margin:0;height:100%;background:#090f1d;color:#e8eaf0;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{min-height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:24px;text-align:center;box-sizing:border-box}
img{width:72px;height:72px;border-radius:18px}h1{font-size:19px;margin:6px 0 0}p{margin:0;color:#9aa3b5;line-height:1.5;max-width:320px}
button{margin-top:6px;border:0;border-radius:14px;padding:12px 22px;font:600 15px inherit;color:#fff;background:linear-gradient(135deg,#0ea5e9,#4f46e5)}
.s{font-size:12.5px;color:#6b7385}</style></head><body><main>
<img src="/assets/icon.png" alt="" onerror="this.remove()">
<h1>Chưa kết nối được AppManager</h1>
<p>Máy chủ có thể đang khởi động lại (vd vừa cập nhật) hoặc iPhone chưa vào cùng mạng. Trang sẽ tự thử lại.</p>
<p class="s">Can't reach AppManager yet — it may be restarting. Retrying automatically.</p>
<button onclick="location.reload()">Thử lại ngay / Retry</button>
<p class="s" id="t"></p></main>
<script>let n=5;const t=document.getElementById('t');setInterval(()=>{n--;t.textContent='Thử lại sau '+Math.max(n,0)+' giây…';if(n<=0)location.reload()},1000)</script>
</body></html>`;

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.mode !== 'navigate') return;  // chỉ trang HTML; file / API đi thẳng ra mạng như bình thường
  event.respondWith((async () => {
    try {
      // quá 15 giây không có phản hồi -> coi như không kết nối được
      return await Promise.race([fetch(req), new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 15000))]);
    } catch (_) {
      return new Response(OFFLINE_HTML, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } });
    }
  })());
});

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
