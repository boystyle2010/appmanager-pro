// Kiểm tra bản mới cho riêng 1 app: menu ⋯ -> "Kiểm tra bản mới", nút làm mới trong cửa sổ cập nhật, API + quyền Token.
// AppManager chạy bằng uvicorn từ repo ở argv[3] (đã tạo admin; Docker có bb-none busybox:1.35 từ setup.sh). argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8794';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ locale: 'vi-VN', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D("d.openActionSheet(d.apps.find(a => a.name === 'bb-none'))"); await sleep(600);
  await p.screenshot({ path: OUT + '/c1-action-sheet.png' });
  check('Action sheet has "Kiểm tra bản mới"', await p.getByText('Kiểm tra bản mới', { exact: true }).first().isVisible());
  await D("window.__toasts = []; const o = d.showToast.bind(d); d.showToast = (m, ...r) => { window.__toasts.push(m); return o(m, ...r); }");
  await p.getByText('Kiểm tra bản mới', { exact: true }).first().click();
  let toasts = [];
  for (let i = 0; i < 90 && !toasts.some(t => t.startsWith('bb-none:')); i++) { await sleep(1000); toasts = await p.evaluate(() => window.__toasts); }
  const app = await D("return d.apps.find(a => a.name === 'bb-none')");
  check('Single-app check finishes with a clear message (busybox 1.35 -> new version)', toasts.some(t => /^bb-none: có bản mới 1\.\d+/.test(t)) && app.has_update, JSON.stringify(toasts));
  await sleep(300);
  await p.screenshot({ path: OUT + '/c2-toast.png' });
  await D("d.openUpdateModal(d.apps.find(a => a.name === 'bb-none'))"); await sleep(1500);
  await p.screenshot({ path: OUT + '/c3-modal.png' });
  await p.getByRole('button', { name: 'Kiểm tra bản mới' }).click(); await sleep(400);
  const spinning = await D('return d.updateModal.checking');
  for (let i = 0; i < 60 && await D('return d.updateModal.checking'); i++) await sleep(1000);
  check('Refresh button in the update window re-checks (spins while checking)', spinning && !(await D('return d.updateModal.checking')));
  // API + Token
  const mk = async (scope) => (await (await ctx.request.post(B + '/api/tokens', { data: { name: 'c-' + scope, scope }, headers: { Origin: B } })).json()).token;
  const up = await mk('update'), ro = await mk('read');
  const r1 = await fetch(B + '/api/apps/bb-none/check', { method: 'POST', headers: { Authorization: 'Bearer ' + up } });
  const r2 = await fetch(B + '/api/apps/bb-none/check', { method: 'POST', headers: { Authorization: 'Bearer ' + ro } });
  const r3 = await fetch(B + '/api/apps/no-such-app/check', { method: 'POST', headers: { Authorization: 'Bearer ' + up } });
  const j1 = await r1.json();
  check('API: Update Token can check one app; Read-only gets 403; unknown app 404', r1.status === 200 && j1.has_update === true && r2.status === 403 && r3.status === 404, `${r1.status} ${r2.status} ${r3.status}`);
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
