// Cài đặt kiểu iOS (0.25.1): tiêu đề lớn, thẻ Chế độ tối, nhóm có nhãn chữ in hoa + giá trị hiện tại, trang Ngôn ngữ,
// thanh "N thay đổi · Huỷ · Lưu" (đếm đúng, Huỷ trả lại, Lưu ghi vào máy chủ). argv: OUT, base URL (admin / Test-Passw0rd!x)
const { chromium } = require('playwright');
const OUT = process.argv[2], B = process.argv[3];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const R = []; const check = (n, c, d = '') => { R.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(1500);
  const body = await p.textContent('body');
  check('Home: large title, dark mode card, uppercase group labels', body.includes('Tuỳ chỉnh AppManager theo ý bạn') && body.includes('Chế độ tối')
        && await p.locator('section p.uppercase', { hasText: 'Bảo mật & tài khoản' }).count() === 1);
  check('Rows show the current value (auto-update / 2FA)', body.includes('Kiểm tra mỗi') && body.includes('Xác thực 2 lớp đang tắt'), body.slice(0, 300));
  await p.screenshot({ path: OUT + '/c1-settings-home.png' });
  await p.locator('button', { hasText: 'Chế độ tối' }).click(); await sleep(400);
  check('Dark mode card switches the theme', (await D('return d.theme')) === 'light');
  await p.screenshot({ path: OUT + '/c2-settings-light.png' });
  await p.locator('button', { hasText: 'Chế độ tối' }).click(); await sleep(300);
  await D("d.openSettingsSection('language')"); await sleep(500);
  await p.screenshot({ path: OUT + '/c3-language.png' });
  await p.locator('button', { hasText: 'English' }).click(); await sleep(400);
  check('Language page switches right away', (await D('return d.lang')) === 'en' && (await p.textContent('body')).includes('Applies right away'));
  await p.locator('button', { hasText: 'Tiếng Việt' }).click(); await sleep(300);
  await D("d.openSettingsSection('schedule')"); await sleep(500);
  check('No pending bar before any change', !(await p.locator('text=thay đổi').first().isVisible().catch(() => false)));
  await D('d.settingsForm.auto_update_enabled = !d.settingsForm.auto_update_enabled; d.settingsForm.check_interval_hours = 12'); await sleep(400);
  check('Pending bar counts 2 changes', await p.getByText('2 thay đổi').isVisible());
  await p.screenshot({ path: OUT + '/c4-pending.png' });
  await p.getByRole('button', { name: 'Huỷ', exact: true }).click(); await sleep(300);
  check('Discard restores the saved values', (await D('return d.settingsChanges()')) === 0 && (await D('return d.settingsForm.check_interval_hours')) !== 12);
  await D('d.settingsForm.check_interval_hours = 12'); await sleep(300);
  await p.getByRole('button', { name: 'Lưu', exact: true }).click(); await sleep(1200);
  const saved = await p.evaluate(async () => (await (await fetch('/api/settings')).json()).settings.check_interval_hours);
  check('Save writes to the server and the bar disappears', saved === 12 && (await D('return d.settingsChanges()')) === 0, saved);
  await D("d.settingsModal.tab = 'home'"); await sleep(400);
  check('Home shows the new value', (await p.textContent('body')).includes('mỗi 12 giờ'));
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${R.filter(Boolean).length} / ${R.length}`);
  await b.close();
})();
