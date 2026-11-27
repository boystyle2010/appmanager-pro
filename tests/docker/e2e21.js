// 0.22 giao diện nhiều tài khoản: Cài đặt → Tài khoản & quyền (danh sách, thêm, sửa vai trò / khoá / đặt lại mật khẩu),
// giao diện theo vai trò (Chỉ xem: không có nút cập nhật / thao tác, Cài đặt chỉ còn mục của mình; Cập nhật: có nút cập nhật,
// không sửa / gỡ app), nhật ký lọc theo người. AppManager uvicorn đã tạo admin (setup.sh: bb-none...). argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8797';
const PW = 'Test-Passw0rd!x';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const page = async (user, pw = PW) => {
    const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
    await ctx.request.post(B + '/api/auth/login', { data: { username: user, password: pw }, headers: { Origin: B } });
    const p = await ctx.newPage(); p._errs = []; p.on('pageerror', e => p._errs.push(e.message));
    await p.goto(B + '/'); await sleep(2500);
    p.D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
    await p.D("d.lang = 'vi'; d.dataSetup.open = false"); await sleep(300);
    return p;
  };
  // Quản trị: thêm tài khoản qua giao diện
  const a = await page('admin');
  await a.D('d.openSettings()'); await sleep(1200);
  await a.getByText('Tài khoản & quyền', { exact: true }).click(); await sleep(1000);
  check('Admin sees the Accounts & permissions section with role explanations', (await a.textContent('body')).includes('Xem + kiểm tra và cài bản mới'));
  for (const [u, role] of [['minh', 'Cập nhật'], ['khach', 'Chỉ xem']]) {
    await a.getByRole('button', { name: 'Thêm tài khoản' }).click(); await sleep(400);
    await a.fill('input[x-model="usersState.form.username"]', u);
    await a.getByRole('button', { name: role, exact: true }).last().click();
    await a.fill('input[x-model="usersState.form.password"]', PW);
    if (u === 'khach') await a.screenshot({ path: OUT + '/u2-add-user.png' });
    await a.getByRole('button', { name: 'Tạo tài khoản' }).click(); await sleep(1200);
  }
  const list = await a.D('return d.usersState.list.map(u => u.username + ":" + u.role).join(",")');
  check('Two accounts created from the UI with the chosen roles', list === 'admin:admin,minh:operator,khach:viewer', list);
  await a.screenshot({ path: OUT + '/u1-users.png' });

  // Chỉ xem
  const v = await page('khach');
  const vs = await v.D(`return { role: d.me.role, check: !!document.querySelector('button[title="' + d.t('checkShort') + '"]')?.offsetParent,
    deploy: !!document.querySelector('button[title="' + d.t('deployApp') + '"]')?.offsetParent }`);
  check('View only: no Check updates / Deploy buttons on the main page', vs.role === 'viewer' && !vs.check && !vs.deploy, JSON.stringify(vs));
  await v.screenshot({ path: OUT + '/u3-viewer-main.png' });
  await v.D("d.openActionSheet(d.apps.find(a => a.name === 'bb-none'))"); await sleep(600);
  const sheet = await v.evaluate(() => [...document.querySelectorAll('.ios-row, button')].filter(x => x.offsetParent).map(x => x.textContent.trim()).join('|'));
  check('View only: the app menu keeps Logs / changelog but no Edit / Uninstall / Restart / Stop',
        sheet.includes('Logs') || sheet.includes('Log') ? !/Sửa cấu hình|Gỡ app|Khởi động lại|Dừng/.test(sheet) : false, sheet.slice(0, 400));
  await v.screenshot({ path: OUT + '/u4-viewer-menu.png' });
  await v.D('d.closeActionSheet()'); await sleep(300);
  await v.D("d.openUpdateModal(d.apps.find(a => a.name === 'bb-none'))"); await sleep(1800);
  const um = await v.textContent('body');
  const upBtns = await v.evaluate(() => [...document.querySelector('[x-show="updateModal.open"]').querySelectorAll('button')].filter(b => b.offsetParent).map(b => b.textContent.trim()).join('|'));
  check('View only: update window shows the changelog with a "view only" note, no update / skip / auto-update / repo controls',
        um.includes('chỉ được xem') && !/Cập nhật ngay|Tải lại|Bỏ qua bản này|Nguồn|Quét lại|Lưu/.test(upBtns), upBtns);
  await v.screenshot({ path: OUT + '/u5-viewer-update.png' });
  await v.D('d.closeUpdateModal()'); await sleep(300);
  await v.D('d.openSettings()'); await sleep(1200);
  const menu = await v.D('return d.settingsMenu().flatMap(g => g.items.map(i => i.tab)).join(",")');
  check('View only: Settings keep only own account, update history and about', menu === 'security,history,about', menu);
  await v.screenshot({ path: OUT + '/u6-viewer-settings.png' });

  // Cập nhật
  const o = await page('minh');
  await o.D("d.openActionSheet(d.apps.find(a => a.name === 'bb-none'))"); await sleep(600);
  const osheet = await o.evaluate(() => [...document.querySelectorAll('.ios-row, button')].filter(x => x.offsetParent).map(x => x.textContent.trim()).join('|'));
  check('Update role: menu has Restart / Stop and version choice, no Edit / Uninstall', /Khởi động lại/.test(osheet) && !/Sửa cấu hình|Gỡ app/.test(osheet), osheet.slice(0, 400));
  await o.screenshot({ path: OUT + '/u7-operator-menu.png' });

  // Quản trị: khoá tài khoản, nhật ký theo người
  await a.D("d.openUserForm(d.usersState.list.find(u => u.username === 'khach'))"); await sleep(400);
  await a.locator('button[role="switch"]').last().click(); await sleep(200);
  await a.screenshot({ path: OUT + '/u8-edit-user.png' });
  await a.getByRole('button', { name: 'Lưu', exact: true }).last().click(); await sleep(1200);
  const st = await v.evaluate(async () => (await fetch('/api/apps')).status);
  check('Disabling an account signs that person out at once (their open page gets 401)', st === 401, st);
  await a.D("d.openSettingsSection('security')"); await sleep(1500);
  await a.locator('select[x-model="auditUser"]').selectOption('admin'); await sleep(1200);
  const au = await a.D("return d.auditItems.every(x => x.username === 'admin') && d.auditItems.some(x => x.action === 'user_add')");
  check('Activity log filtered by person (admin: accounts added / changed)', au);
  await a.evaluate(() => [...document.querySelectorAll('p')].find(x => x.textContent.trim() === 'Nhật ký hoạt động')?.scrollIntoView({ block: 'start' })); await sleep(400);
  await a.screenshot({ path: OUT + '/u9-audit-by-user.png' });
  check('No JavaScript errors', ![a, v, o].some(p => p._errs.length), [a, v, o].map(p => p._errs.join(' | ')).join(' || '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
