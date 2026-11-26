// Trang đang mở là của bản build cũ (Safari giữ tab sau khi AppManager cập nhật) -> tự tải lại đúng 1 lần.
// HTML có Cache-Control: no-cache, file tĩnh có ?v=<mã build>. AppManager chạy bằng uvicorn, đã tạo admin. argv: base URL.
const { chromium } = require('playwright');
const B = process.argv[2] || 'http://localhost:8796';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  let loads = 0; p.on('load', () => loads++);
  const resp = await p.goto(B + '/'); await sleep(2500);
  check('HTML is sent with Cache-Control: no-cache', (resp.headers()['cache-control'] || '').includes('no-cache'), resp.headers()['cache-control']);
  const build = await p.evaluate(() => document.querySelector('meta[name="amp-build"]').content);
  const js = await p.evaluate(() => [...document.scripts].map(s => s.src).find(s => s.includes('app.js')));
  check('Static files carry the build id (?v=<build>)', build && js.endsWith('?v=' + build), js + ' / ' + build);
  const before = loads;
  await p.evaluate(() => { document.querySelector('meta[name="amp-build"]').content = 'old-build'; return Alpine.$data(document.body).loadApps(); }).catch(() => {});
  await sleep(3000);
  check('Old page reloads itself once when the server has a newer build', loads === before + 1, `${before} -> ${loads}`);
  await p.evaluate(() => { document.querySelector('meta[name="amp-build"]').content = 'old-build'; return Alpine.$data(document.body).loadApps(); }).catch(() => {});
  await sleep(2500);
  check('No reload loop: a second mismatch for the same build does not reload again', loads === before + 1, `${loads}`);
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
