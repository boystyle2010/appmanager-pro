// 0.20 quy tắc tự cập nhật: phần quy tắc trong cửa sổ cập nhật, dòng "đang giữ lại" trên thẻ, cảnh báo khi tự cập nhật chung tắt.
// AppManager chạy bằng uvicorn từ repo ở argv[3] (đã tạo admin; setup.sh: bb-none busybox:1.35). argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8794';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  await ctx.request.post(B + '/api/apps/bb-none/check', { headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D("d.openUpdateModal(d.apps.find(a => a.name === 'bb-none'))"); await sleep(1800);
  await D("d.updateModal.autoUpdate = true; return d.saveAppPref()"); await sleep(1200);
  check('Rules appear when auto-update is on, with a warning while scheduled auto-update is off', await D('return !!d.updateModal.policy') && (await p.textContent('body')).includes('Tự cập nhật theo lịch đang tắt'));
  await p.getByRole('button', { name: 'Chỉ bản vá' }).click(); await sleep(1500);
  const hold = await D("return d.apps.find(a => a.name === 'bb-none').auto_hold");
  check('Patch only -> held: minor version waits for you', hold && hold.code === 'level', JSON.stringify(hold));
  await p.evaluate(() => [...document.querySelectorAll('p')].find(x => x.textContent.trim() === 'Quy tắc tự cập nhật')?.scrollIntoView({ block: 'start' })); await sleep(400);
  await p.screenshot({ path: OUT + '/r1-rules.png' });
  await D('d.closeUpdateModal()'); await sleep(600);
  await p.evaluate(() => [...document.querySelectorAll('h2')].find(h => h.textContent.trim() === 'bb-none')?.scrollIntoView({ block: 'center' })); await sleep(400);
  check('Card shows why auto-update is holding the new version', (await p.textContent('body')).includes('chờ bạn cập nhật tay'));
  await p.screenshot({ path: OUT + '/r2-card.png' });
  // đợi 3 ngày
  await D("d.openUpdateModal(d.apps.find(a => a.name === 'bb-none'))"); await sleep(1500);
  await D("d.updateModal.policy.level = 'minor'; d.updateModal.policy.min_age_days = 3; return d.saveAppPolicy()"); await sleep(1200);
  const h2 = await D("return d.apps.find(a => a.name === 'bb-none').auto_hold");
  check('Minor + wait 3 days -> "auto-update in 3 days"', h2 && h2.code === 'wait' && h2.days_left === 3, JSON.stringify(h2));
  await p.evaluate(() => [...document.querySelectorAll('p')].find(x => x.textContent.trim() === 'Quy tắc tự cập nhật')?.scrollIntoView({ block: 'start' })); await sleep(400);
  await p.screenshot({ path: OUT + '/r3-wait.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
