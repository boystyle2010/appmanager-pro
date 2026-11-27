// 0.25 giao diện Web Push (Cài đặt → Thông báo): trang HTTP qua IP mạng -> "cần HTTPS" + hướng dẫn Tailscale / reverse proxy /
// Cloudflare Tunnel; iPhone (Safari, chưa thêm vào màn hình chính) -> hướng dẫn "Thêm vào MH chính"; localhost (trình duyệt
// coi là an toàn) -> nút "Bật trên thiết bị này", service worker /sw.js đăng ký thật; danh sách thiết bị + Gửi thử.
// argv: OUT, base URL (localhost), base URL qua IP mạng (http, không an toàn), endpoint push giả https.
const { chromium, devices } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3]; const BIP = process.argv[4]; const PUSH = process.argv[5] || 'https://127.0.0.1:8775';
const PW = 'Test-Passw0rd!x';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
const open = async (b, base, opts = {}) => {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, ...opts });
  if (opts.perm) await ctx.grantPermissions(['notifications'], { origin: base });
  await ctx.request.post(base + '/api/auth/login', { data: { username: 'admin', password: PW }, headers: { Origin: base } });
  const p = await ctx.newPage(); p._errs = []; p.on('pageerror', e => p._errs.push(e.message));
  await p.goto(base + '/'); await sleep(2500);
  p.D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.D("d.lang = 'vi'; d.dataSetup.open = false");
  await p.D("d.openSettings()"); await sleep(1000); await p.D("d.openSettingsSection('notify')"); await sleep(1800);
  return p;
};
(async () => {
  const b = await chromium.launch({ channel: 'chromium' });
  // 1) HTTP qua IP mạng: không an toàn
  const h = await open(b, BIP);
  check('Plain http:// over the LAN: "Web Push needs HTTPS" with a guide', (await h.textContent('body')).includes('Web Push cần HTTPS') && !(await h.D('return d.wp.secure')));
  await h.getByText('Cách có HTTPS ›').click(); await sleep(400);
  const txt = await h.textContent('body');
  check('Guide lists Tailscale, reverse proxy and Cloudflare Tunnel', txt.includes('Tailscale') && txt.includes('Reverse proxy') && txt.includes('Cloudflare Tunnel') && txt.includes('tailscale serve --bg'));
  await h.screenshot({ path: OUT + '/w1-needs-https.png' });
  // 2) iPhone Safari chưa thêm vào màn hình chính
  const i = await open(b, B, { ...devices['iPhone 13'] });
  check('iPhone in Safari (not from the home screen icon): explains "Add to Home Screen" first', (await i.textContent('body')).includes('thêm AppManager vào màn hình chính trước'));
  await i.screenshot({ path: OUT + '/w2-iphone-add-home.png' });
  // 3) localhost (an toàn): nút bật, service worker đăng ký thật
  const l = await open(b, B, { perm: true });
  check('Secure page with push support: "Turn on here" with a device name', await l.getByRole('button', { name: 'Bật trên thiết bị này' }).isVisible() && (await l.D('return d.wp.name')).length > 0);
  await l.screenshot({ path: OUT + '/w3-enable-here.png' });
  await l.getByRole('button', { name: 'Bật trên thiết bị này' }).click(); await sleep(3000);
  const swState = await l.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration('/'); return r ? (r.active ? r.active.state : 'installing') : 'none'; });
  check('Service worker /sw.js registered and active in a real Chromium (scope /)', swState === 'activated', swState);
  const msg = await l.D('return d.wp.msg');
  check('If the browser cannot reach a push service, the reason is shown (no silent failure)', msg.length > 0, msg);
  // 4) danh sách thiết bị (thiết bị đăng ký qua API tới dịch vụ push giả)
  const sub = { endpoint: PUSH + '/push/ui1', keys: { p256dh: 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4', auth: 'BTBZMqHH6r4Tts7J_aSIgg' } };
  await l.evaluate(async (s) => fetch('/api/notify/webpush/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subscription: s, name: 'iPhone của Minh' }) }), sub);
  await l.D('d.loadNotify(); return d.loadWebPush()'); await sleep(800);
  await l.getByRole('button', { name: 'Gửi thử', exact: true }).first().click(); await sleep(2500);
  check('Device list: name + push service; Test delivers (fake push service)', (await l.textContent('body')).includes('iPhone của Minh') && (await l.D('return d.wp.ok')), await l.D('return d.wp.msg'));
  const chans = await l.D('return d.notifyState.channels.map(c => c.type)');
  check('Web Push channel appears in the channel list (events chosen there)', chans.includes('webpush'), JSON.stringify(chans));
  await l.screenshot({ path: OUT + '/w4-devices.png' });
  check('No JavaScript errors', ![h, i, l].some(p => p._errs.length), [h, i, l].map(p => p._errs.join(' | ')).join(' || '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
