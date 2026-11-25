const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = 'http://localhost:8796'; const fs = require('fs');
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => { const d = Alpine.$data(document.body); return (new Function('d', c))(d); }, code);
  await p.goto(B + '/'); await sleep(2000); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D("d.openSettings().then(() => { d.settingsModal.tab = 'notify'; d.loadNotify(); })"); await sleep(1500);
  await p.screenshot({ path: OUT + '/o1-empty.png' });
  // thêm webhook qua giao diện, Lưu & gửi thử
  await D("d.newNotifyChannel(); d.notifyState.edit.type = 'webhook'; d.notifyState.edit.name = 'Máy chủ nhà'; d.notifyState.edit.config.url = 'http://127.0.0.1:8094/x'"); await sleep(400);
  await D("d.saveNotifyChannel(true)"); for (let i = 0; i < 30; i++) { await sleep(500); if (!(await D('return d.notifyState.busy || !!d.notifyState.testing'))) break; } await sleep(800);
  const msg = await D('return [d.notifyState.ok, d.notifyState.msg]'); console.log('save&test:', JSON.stringify(msg));
  // thêm ntfy (lưu)
  await D("d.newNotifyChannel(); d.notifyState.edit.type = 'ntfy'; d.notifyState.edit.name = 'Điện thoại'; d.notifyState.edit.config.server = 'http://localhost:8091'; d.notifyState.edit.config.topic = 'amp-ui2'; d.notifyState.edit.events = ['update_failed','app_unhealthy','security']"); await D("d.saveNotifyChannel(false)"); await sleep(1200);
  await D("d.newNotifyChannel()"); await sleep(400);
  await p.screenshot({ path: OUT + '/o2-form-telegram.png' });
  await D("d.notifyState.edit = null"); await sleep(300);
  await p.screenshot({ path: OUT + '/o3-list.png' });
  await p.evaluate(() => { const el = document.querySelector('[x-show="settingsModal.open"] .overflow-y-auto'); if (el) el.scrollTop = 99999; }); await sleep(300);
  await D("d.notifyState.settings.quiet_enabled = true"); await sleep(300);
  await p.screenshot({ path: OUT + '/o4-quiet.png' });
  // 5 lần đăng nhập sai từ một context khác -> khoá IP -> tin bảo mật
  const c2 = await b.newContext();
  for (let i = 0; i < 5; i++) await c2.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'wrong' + i }, headers: { Origin: B } });
  await sleep(4000);
  const lines = fs.readFileSync(process.argv[3], 'utf8').trim().split('\n').map(l => JSON.parse(l));
  console.log('webhook events:', JSON.stringify(lines.map(x => x.event)));
  const ntfy = await (await ctx.request.get('http://localhost:8091/amp-ui2/json?poll=1')).text();
  console.log('ntfy titles:', JSON.stringify(ntfy.trim().split('\n').filter(Boolean).map(l => JSON.parse(l).title)));
  console.log('errors:', errs.length ? errs.join(' | ') : 'none');
  await b.close();
})();
