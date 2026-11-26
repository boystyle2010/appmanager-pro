// Ảnh: Cài đặt → Bộ nhớ → Thư mục dữ liệu (danh sách, sửa đường dẫn, gỡ). Cần AppManager ở :8770 (chạy t_datafolders.py phần đầu).
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8770'; const NEWP = process.argv[4];
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(800); await D("d.settingsModal.tab = 'storage'"); await D('return d.refreshDataStatus()'); await sleep(1500);
  await p.screenshot({ path: OUT + '/f1-settings-row.png' });
  await D('return d.openDataFolders()'); await sleep(1200);
  await p.screenshot({ path: OUT + '/f2-folders.png' });
  await D("d.dataFolderEdit(d.dataSetup.status.folders.find(f => !f.has_self))"); await sleep(400);
  await D(`d.dataFolders.newPath = ${JSON.stringify(NEWP)}`); await D('return d.dataFolderCheck()'); await sleep(800);
  await p.screenshot({ path: OUT + '/f3-edit.png' });
  await D("d.dataFolders.mode = 'list'"); await D("d.dataFolderRemove(d.dataSetup.status.folders.find(f => !f.has_self))"); await sleep(500);
  await p.screenshot({ path: OUT + '/f4-remove.png' });
  await D('d.confirmDataFolderChange()'); await sleep(600);
  await p.screenshot({ path: OUT + '/f5-confirm.png' });
  console.log('errors:', errs.length ? errs.join(' | ') : 'none');
  await b.close();
})();
