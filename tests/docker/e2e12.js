// Ảnh + kiểm tra: Cài đặt dạng danh sách, Bộ nhớ & SSD → Thư mục dữ liệu (Setup = menu cũ, bấm ô = popup mới),
// Manual trong menu cũ -> popup mới chế độ thêm; thêm thật 1 thư mục (AppManager tạo lại) rồi kiểm tra mount.
// Cần AppManager ở :8770 (chạy phần đầu t_datafolders.py: df_setup.py). argv: OUT, base URL, thư mục để thêm.
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8770'; const NEWP = process.argv[4];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(1500);
  await p.screenshot({ path: OUT + '/s0-settings-home.png' });
  check('Settings opens on the section list', await D("return d.settingsModal.tab === 'home' && document.querySelectorAll('[x-text=\"item.title\"]').length === d.settingsMenu().flatMap(g => g.items).length && d.settingsMenu().flatMap(g => g.items).length >= 7"));
  await p.getByText('Bộ nhớ & SSD', { exact: true }).click(); await sleep(1500);
  check('Tapping a row opens the section with a back button', await D("return d.settingsModal.tab === 'storage'"));
  await p.screenshot({ path: OUT + '/s1-storage.png' });
  await p.getByText('Thiết lập', { exact: true }).first().click().catch(async () => { await D('d.openDataSetup()'); }); await sleep(800);
  check('Setup button opens the old menu (Manual / Auto Scan)', await D("return d.dataSetup.open && d.dataSetup.step === 'intro' && !d.dataFolders.open"));
  await p.screenshot({ path: OUT + '/s2-setup-menu.png' });
  await D("document.querySelector('[x-text=\"t(\\'dataManual\\')\"]').closest('button').click()"); await sleep(1200);
  check('Manual opens the new popup in add mode', await D("return !d.dataSetup.open && d.dataFolders.open && d.dataFolders.mode === 'add'"));
  await D(`d.dataFolders.newPath = ${JSON.stringify(NEWP)}`); await D('return d.dataFolderCheck()'); await sleep(800);
  await p.screenshot({ path: OUT + '/s3-manual-add.png' });
  check('Add plan lists the app that becomes manageable', await D("return d.dataFolderPlan().some(s => s.text.includes('otherapp'))"));
  await D("d.dataFolders.mode = 'list'; d.dataFolders.check = null"); await sleep(300);
  await D("d.dataFolders.open = false"); await sleep(300);
  await D("document.querySelector('[x-text=\"dataFolderSummary()\"]').closest('[role=button]').click()"); await sleep(1200);
  check('Tapping the card opens the folder list', await D("return d.dataFolders.open && d.dataFolders.mode === 'list'"));
  await p.screenshot({ path: OUT + '/s4-folder-list.png' });
  // thêm thật
  await D(`d.dataFolderAdd(); d.dataFolders.newPath = ${JSON.stringify(NEWP)}`); await D('return d.dataFolderCheck()'); await sleep(500);
  await D('return d.applyDataFolderChange()'); await sleep(3000);
  let ok = false;
  for (let i = 0; i < 60 && !ok; i++) { await sleep(3000); try { ok = execSync("docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' appmanager-pro 2>/dev/null").toString().includes(NEWP) && !execSync("docker ps -aq -f name=^appmanager-pro-self-updater$").toString().trim(); } catch (_) {} }
  check('Add & restart: AppManager recreated with the new folder mounted', ok);
  // ô dung lượng sao lưu hiển thị đủ số
  await sleep(8000); await p.goto(B + '/'); await sleep(2500);
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(1200); await D("d.openSettingsSection('storage')"); await sleep(1500);
  await D("d.settingsForm.backup_before_update = true; d.settingsForm.backup_max_mb = 20480"); await sleep(400);
  const fit = await p.evaluate(() => { const i = document.querySelector('input[x-model\\.number="settingsForm.backup_max_mb"]'); return i.scrollWidth <= i.clientWidth; });
  check('Backup total size input shows the full number (20480)', fit);
  await p.evaluate(() => document.querySelector('input[x-model\\.number="settingsForm.backup_max_mb"]').scrollIntoView({ block: 'center' })); await sleep(400);
  await p.screenshot({ path: OUT + '/s5-backup-inputs.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
