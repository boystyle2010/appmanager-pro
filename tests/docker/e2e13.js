// API token (0.17): mục trong Cài đặt, tạo token (hiện 1 lần), danh sách, ví dụ, xoá — kèm kiểm tra token dùng được thật.
// AppManager chạy bằng uvicorn từ repo ở cổng argv[3] (đã tạo admin). argv: OUT, base URL.
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
  await D('d.openSettings()'); await sleep(1200);
  await p.screenshot({ path: OUT + '/k0-settings-home.png' });
  await p.getByText('API Token', { exact: true }).click(); await sleep(1200);
  check('API token row opens the section', await D("return d.settingsModal.tab === 'tokens' && d.tokenState.loaded"));
  await p.screenshot({ path: OUT + '/k1-empty.png' });
  await p.getByText('Tạo Token', { exact: true }).first().click(); await sleep(500);
  await p.fill('input[x-model="tokenState.form.name"]', 'Home Assistant');
  await p.getByText('Cập nhật', { exact: true }).click(); await p.getByText('90 ngày', { exact: true }).click();
  await p.fill('input[x-model="tokenState.form.ips"]', '192.168.68.0/24, 127.0.0.1');
  await sleep(300); await p.screenshot({ path: OUT + '/k2-form.png' });
  await p.getByText('Tạo', { exact: true }).click(); await sleep(1200);
  const tok = await D('return d.tokenState.created');
  check('Token shown once after Create', /^amp_.{40}$/.test(tok), tok);
  await p.screenshot({ path: OUT + '/k3-created.png' });
  const r = await (await fetch(B + '/api/health', { headers: { Authorization: 'Bearer ' + tok } })).json();
  check('The new token works (GET /api/health detailed)', r.status === 'ok' && !!r.version, JSON.stringify(r));
  await p.getByText('Đã lưu, đóng', { exact: true }).click(); await sleep(800);
  check('Closing forgets the token in the page', await D("return d.tokenState.created === '' && !d.tokenState.form.open"));
  // token thứ 2: chỉ đọc, không hết hạn
  await D("d.openTokenForm(); d.tokenState.form.name = 'Uptime Kuma'; d.tokenState.form.days = 0"); await D('return d.createToken()'); await sleep(500); await D('d.closeTokenForm()');
  await sleep(800); await D('d.tokenState.examples = true'); await sleep(400);
  await p.screenshot({ path: OUT + '/k4-list.png', fullPage: false });
  const list = await D('return d.tokenState.items.map(t => [t.name, t.scope, t.ips.length, !!t.last_used])');
  check('List shows both tokens with permission, IP limit and last use', list.length === 2 && list.some(x => x[0] === 'Home Assistant' && x[1] === 'update' && x[2] === 2 && x[3]), JSON.stringify(list));
  await p.evaluate(() => document.querySelector('pre.glass-terminal')?.scrollIntoView({ block: 'center' })); await sleep(400);
  await p.screenshot({ path: OUT + '/k5-examples.png' });
  await D("d.confirmDeleteToken(d.tokenState.items.find(t => t.name === 'Home Assistant'))"); await sleep(500);
  await p.screenshot({ path: OUT + '/k6-delete.png' });
  await D('d.runConfirmedAction()'); await sleep(1200);
  const r2 = await fetch(B + '/api/health', { headers: { Authorization: 'Bearer ' + tok } }).then(x => x.json());
  check('Deleted token no longer returns details', !r2.version && (await D('return d.tokenState.items.length')) === 1, JSON.stringify(r2));
  // API Docs mở ngay trong app (khung trong cửa sổ, không mở tab mới)
  await D("d.settingsModal.tab = 'tokens'"); await sleep(400);
  const pagesBefore = ctx.pages().length;
  await p.getByRole('button', { name: 'API Docs' }).click(); await sleep(2500);
  const fr = p.frameLocator('iframe');
  check('API Docs opens inside AppManager (no new tab) and shows the automation API',
        ctx.pages().length === pagesBefore && await D('return d.apiDocs.open') && await fr.getByText('API cho tự động hoá').count() === 1);
  await p.screenshot({ path: OUT + '/k8-docs.png' });
  await fr.locator('details').nth(5).locator('summary').click(); await sleep(400);
  await fr.locator('details').nth(5).scrollIntoViewIfNeeded(); await sleep(300);
  await p.screenshot({ path: OUT + '/k9-docs-update.png' });
  await D('d.apiDocs.open = false'); await sleep(300);
  // English labels fit
  await D("d.lang = 'en'"); await sleep(400); await D("d.settingsModal.tab = 'home'"); await sleep(400);
  await p.screenshot({ path: OUT + '/k7-home-en.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
