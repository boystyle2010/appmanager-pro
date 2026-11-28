// 0.24 giao diện sao lưu cấu hình: Cài đặt → Sao lưu cấu hình (giải thích, chọn phần, mật khẩu, tạo & tải file .ampbak),
// khôi phục (chọn file, mật khẩu, xem trước từng phần, Sẽ thực hiện, hộp xác nhận, kết quả + bản tự lưu). AppManager uvicorn
// đã tạo admin. argv: OUT, base URL, thư mục tạm.
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8776'; const TMP = process.argv[4] || '/tmp';
const PW = 'Test-Passw0rd!x';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ locale: 'vi-VN', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, acceptDownloads: true });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: PW }, headers: { Origin: B } });
  await ctx.request.post(B + '/api/tokens', { data: { name: 'Home Assistant', scope: 'update' }, headers: { Origin: B } });
  await ctx.request.post(B + '/api/users', { data: { new: true, username: 'minh', password: 'Minh-Passw0rd!1', role: 'operator' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(1200);
  await p.getByText('Sao lưu cấu hình', { exact: true }).click(); await sleep(1500);
  check('Page explains what is in the file and lists every part with counts', (await p.textContent('body')).includes('Tài khoản & vai trò') && (await p.textContent('body')).includes('2 mục'));
  await p.screenshot({ path: OUT + '/c1-config-page.png' });
  await p.fill('input[x-model="cfgState.exp.pw"]', 'Backup-Pass-2026');
  await p.fill('input[x-model="cfgState.exp.pw2"]', 'Backup-Pass-2026');
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 15000 }).catch(() => null), p.getByRole('button', { name: 'Tạo & tải file' }).click()]);
  const name = dl ? dl.suggestedFilename() : '';
  const file = TMP + '/' + (name || 'x.ampbak'); if (dl) await dl.saveAs(file);
  check('Create & download gives an encrypted .ampbak file', /^appmanager-config-\d{8}-\d{4}\.ampbak$/.test(name) && fs.readFileSync(file, 'utf8').includes('AES-256-GCM'), name);
  // thay đổi rồi khôi phục: xoá Token
  const toks = await (await ctx.request.get(B + '/api/tokens')).json();
  for (const t of toks.tokens) await ctx.request.post(B + '/api/tokens/delete', { data: { id: t.id }, headers: { Origin: B } });
  await p.locator('input[type="file"]').setInputFiles(file); await sleep(600);
  await p.fill('input[x-model="cfgState.imp.pw"]', 'wrong-password');
  await p.getByRole('button', { name: 'Mở', exact: true }).click(); await sleep(1200);
  check('Wrong password: clear message, nothing shown', (await p.textContent('body')).includes('Wrong password') && !(await D('return !!d.cfgState.imp.info')));
  await p.fill('input[x-model="cfgState.imp.pw"]', 'Backup-Pass-2026');
  await p.getByRole('button', { name: 'Mở', exact: true }).click(); await sleep(1500);
  check('Right password: preview of each part (accounts admin, minh)', (await p.textContent('body')).includes('admin, minh'));
  await D("Object.keys(d.cfgState.imp.sel).forEach(k => d.cfgState.imp.sel[k] = (k === 'tokens'))"); await sleep(300);
  await p.evaluate(() => [...document.querySelectorAll('p')].find(x => x.textContent.trim() === 'Khôi phục từ file')?.scrollIntoView({ block: 'start' })); await sleep(300);
  await p.screenshot({ path: OUT + '/c2-config-preview.png' });
  await p.getByRole('button', { name: 'Khôi phục', exact: true }).last().click(); await sleep(600);
  check('Restore asks for confirmation (danger)', (await p.textContent('body')).includes('Khôi phục cấu hình?'));
  await p.screenshot({ path: OUT + '/c3-config-confirm.png' });
  await D('d.confirmModal.onConfirm(); d.closeConfirm()'); await sleep(2500);
  const after = await (await ctx.request.get(B + '/api/tokens')).json();
  check('Only the chosen part restored: the deleted Token is back', after.tokens.length === 1 && after.tokens[0].name === 'Home Assistant', JSON.stringify(after));
  check('Result shows what was restored and the automatic copy', (await p.textContent('body')).includes('Đã khôi phục cấu hình') && (await D('return d.cfgState.safety.length')) === 1);
  await p.evaluate(() => [...document.querySelectorAll('p')].find(x => x.textContent.trim() === 'Đã khôi phục cấu hình')?.scrollIntoView({ block: 'center' })); await sleep(300);
  await p.screenshot({ path: OUT + '/c4-config-restored.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
