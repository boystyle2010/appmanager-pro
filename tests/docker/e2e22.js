// 0.23 giao diện SSO: Cài đặt → Đăng nhập một lần (hướng dẫn, Redirect URI, nhà cung cấp, nhóm → vai trò, Kiểm tra),
// trang đăng nhập có nút "Đăng nhập bằng …" và hiện lỗi SSO, đăng nhập SSO thật qua nhà cung cấp giả (oidc_mock.py :8790),
// tài khoản SSO có nhãn SSO, trang Bảo mật của tài khoản SSO. AppManager uvicorn đã tạo admin. argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8780'; const MOCK = 'http://127.0.0.1:8790';
const PW = 'Test-Passw0rd!x';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: PW }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(1200);
  await p.getByText('Đăng nhập một lần (SSO)', { exact: true }).click(); await sleep(1200);
  check('SSO page explains steps and shows the Redirect URI', (await p.textContent('body')).includes('Dán Redirect URI') && (await D('return d.ssoState.redirect')) === B + '/api/auth/oidc/callback');
  await p.screenshot({ path: OUT + '/s1-sso-intro.png' });
  await p.locator('button[role="switch"]').first().click();
  await p.fill('input[x-model="ssoState.form.label"]', 'Authentik');
  await p.fill('input[x-model="ssoState.form.issuer"]', MOCK);
  await p.fill('input[x-model="ssoState.form.client_id"]', 'appmanager');
  await p.fill('input[x-model="ssoState.secret"]', 's3cret-value');
  await p.locator('input[x-model="ssoState.form[r + \'_groups\']"]').nth(0).fill('amp-admins');
  await p.locator('input[x-model="ssoState.form[r + \'_groups\']"]').nth(1).fill('amp-ops');
  await p.getByRole('button', { name: 'Kiểm tra', exact: true }).click(); await sleep(1500);
  check('Test shows the provider is reachable with its keys', (await p.textContent('body')).includes('Kết nối được nhà cung cấp'));
  await p.evaluate(() => [...document.querySelectorAll('p')].find(x => x.textContent.trim() === 'Nhóm → Vai trò')?.scrollIntoView({ block: 'start' })); await sleep(300);
  await p.screenshot({ path: OUT + '/s2-sso-groups.png' });
  await p.getByRole('button', { name: 'Lưu', exact: true }).last().click(); await sleep(1500);
  check('Saved: SSO on, secret not shown again', await D('return d.ssoState.cfg.enabled && d.ssoState.cfg.has_secret && !d.ssoState.secret'));
  await p.screenshot({ path: OUT + '/s3-sso-saved.png' });

  // trang đăng nhập (trình duyệt khác, chưa đăng nhập)
  const ctx2 = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const q = await ctx2.newPage(); q.on('pageerror', e => errs.push(e.message));
  await q.goto(B + '/login'); await sleep(1500);
  await q.locator('.lp-power').click(); await sleep(1200);  // trang đăng nhập: bấm nút nguồn để hiện ô đăng nhập
  check('Login page shows "Đăng nhập bằng Authentik"', await q.getByText('Đăng nhập bằng Authentik').isVisible());
  const st = await q.evaluate(async () => (await fetch('/api/auth/oidc/status')).json());
  check('Status tells the page which provider icon to show + that SSO can create accounts', st.provider === 'oidc' || st.provider === 'authentik', JSON.stringify(st));
  await q.getByRole('tab', { name: 'Đăng ký' }).click(); await sleep(500);
  check('Sign up tab offers "Đăng ký bằng Authentik" when SSO creates accounts', await q.getByText('Đăng ký bằng Authentik').isVisible() === !!st.signup, JSON.stringify(st));
  await q.screenshot({ path: OUT + '/s4b-signup-sso.png' });
  await q.getByRole('tab', { name: 'Đăng nhập' }).click(); await sleep(300);
  await q.screenshot({ path: OUT + '/s4-login-sso.png' });
  await ctx2.request.post(MOCK + '/admin', { data: { user: { sub: 'u-5', preferred_username: 'minh', email: 'minh@example.com', groups: ['random'] }, fault: '' } });
  await q.getByText('Đăng nhập bằng Authentik').click(); await sleep(2500);
  check('Not in an allowed group -> back on the login page with the reason (in Vietnamese)', (await q.textContent('body')).includes('không thuộc nhóm nào được dùng AppManager'));
  await q.screenshot({ path: OUT + '/s5-login-sso-error.png' });
  await ctx2.request.post(MOCK + '/admin', { data: { user: { sub: 'u-5', preferred_username: 'minh', email: 'minh@example.com', groups: ['amp-ops'] } } });
  await q.getByText('Đăng nhập bằng Authentik').click(); await sleep(3500);
  const meQ = await q.evaluate(async () => (await fetch('/api/auth/me')).json());
  check('SSO sign-in lands on the dashboard as Update role', q.url() === B + '/' && meQ.username === 'minh' && meQ.role === 'operator', JSON.stringify(meQ) + ' ' + q.url());
  await q.evaluate(() => { const d = Alpine.$data(document.body); d.lang = 'vi'; d.dataSetup.open = false; }); await sleep(300);
  await q.evaluate(() => Alpine.$data(document.body).openSettings()); await sleep(1000);
  await q.evaluate(() => Alpine.$data(document.body).openSettingsSection('security')); await sleep(1000);
  check('SSO account: Security page says password / 2FA are managed by the provider', (await q.textContent('body')).includes('do nhà cung cấp danh tính của bạn quản lý'));
  await q.screenshot({ path: OUT + '/s6-sso-security.png' });
  // tài khoản có nhãn SSO
  await D("d.openSettingsSection('users')"); await sleep(1200);
  check('Accounts list marks the SSO account', (await D("return d.usersState.list.find(u => u.username === 'minh')?.auth_source")) === 'oidc');
  await p.screenshot({ path: OUT + '/s7-users-sso.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
