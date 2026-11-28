const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = 'http://localhost:8797';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ locale: 'vi-VN', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => { const d = Alpine.$data(document.body); return (new Function('d', c))(d); }, code);
  await p.goto(B + '/'); await sleep(2000); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.checkUpdates(true)'); for (let i = 0; i < 60; i++) { await sleep(1000); if (!(await D('return d.checkingUpdates'))) break; }
  await D('d.loadApps()'); await sleep(1200);
  // giả lập: Docker Hub đang giới hạn -> kiểm tra lại
  const r = await ctx.request.post(B + '/api/test-only-block', { headers: { Origin: B } }).catch(() => null);
  await D('d.openSettings()'); await sleep(1800);
  await p.evaluate(() => { const el = document.querySelector('[x-show="settingsModal.open"] .overflow-y-auto') || document.querySelector('[x-show="settingsModal.open"] .glass-panel'); if (el) el.scrollTop = 99999; }); await sleep(500);
  await p.screenshot({ path: OUT + '/k1-settings-api.png' });
  console.log('sources', JSON.stringify(await D('return d.apiStatus.sources.map(s => [s.source, s.requests_1h, s.cache_hits_1h, s.blocked_until > 0])')));
  console.log('errors:', errs.length ? errs.join(' | ') : 'none');
  await b.close();
})();
