// 0.21 giao diện: cửa sổ log (trực tiếp + khoảng thời gian, tìm, lọc mức, tải về), danh sách gộp mọi máy (thẻ ghi tên máy,
// tìm theo tên máy), log app máy phụ, khôi phục app máy phụ (chọn bản -> tiến trình -> kết quả).
// Cần srv_setup.sh (máy chính :8793, máy phụ :8792, Token Cập nhật trong $S/srv.tok), container lg ghi log mẫu,
// bản sao lưu bb-none trên máy phụ (tạo trong run_everything.sh). argv: OUT, Token máy phụ.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const TOK = process.argv[3]; const B = 'http://localhost:8793';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, acceptDownloads: true });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  await ctx.request.post(B + '/api/servers', { data: { name: 'NAS phòng khách', url: 'http://127.0.0.1:8792', token: TOK }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(3000); await D("d.lang = 'vi'; d.dataSetup.open = false");

  // Log trên máy này
  await D("d.openLogs(d.apps.find(a => a.name === 'lg'))"); await sleep(2500);
  check('Live log shows the container output', (await D('return d.logModal.lines')).includes('cannot connect db'));
  await p.fill('input[x-model="logModal.q"]', 'line'); await sleep(400);
  check('Live: search filters lines in the browser', (await D('return d.logView()')).includes('about cats') && !(await D('return d.logView()')).includes('WARNING'));
  await p.fill('input[x-model="logModal.q"]', ''); await sleep(200);
  await p.locator('select').filter({ has: p.locator('option[value="live"]') }).selectOption('1h'); await sleep(1500);
  await p.getByRole('button', { name: 'Lỗi', exact: true }).click(); await sleep(1500);
  const errText = await D('return d.logView()');
  check('Range "1 hour" + Errors: server-side filter keeps the error block only', errText.includes('cannot connect db') && errText.includes('File x.py') && !errText.includes('WARNING'), errText);
  check('Counts are shown (matching / read lines)', (await p.textContent('body')).includes('3 dòng khớp'));
  await p.screenshot({ path: OUT + '/g1-logs-errors.png' });
  const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 10000 }).catch(() => null), p.getByRole('button', { name: 'Tải log về (.txt)' }).click()]);
  const name = dl ? dl.suggestedFilename() : '';
  check('Download gives a .txt named after the app and range', /^lg-logs-1h-\d{8}-\d{4}\.txt$/.test(name), name);
  await D('d.closeLogs()'); await sleep(500);

  // Log có mã màu ANSI (container lgc, kiểu Portainer): hiện màu thật, không còn ký tự lạ
  await D("d.openLogs(d.apps.find(a => a.name === 'lgc'))"); await sleep(2500);
  const html = await p.evaluate(() => document.querySelector('pre[x-ref="logBox"]').innerHTML);
  const txt = await p.evaluate(() => document.querySelector('pre[x-ref="logBox"]').textContent);
  check('ANSI colors rendered as colored text (no escape characters shown)',
        !txt.includes('\x1b') && !txt.includes('[32m') && txt.includes('INF main.go:705 > starting Portainer')
        && /<span style="color:#4ade80">INF<\/span>/.test(html) && /color:#f87171/.test(html), html.slice(0, 400));
  await p.screenshot({ path: OUT + '/g0-logs-ansi.png' });
  await p.getByRole('button', { name: 'Lỗi', exact: true }).click(); await sleep(400);
  check('Live + Errors on a colored log keeps the ERR line only', (await D('return d.logView()')).includes('failed to load') && !(await D('return d.logView()')).includes('Portainer'));
  await D('d.closeLogs()'); await sleep(400);

  // Danh sách gộp mọi máy
  await p.getByRole('button', { name: 'Tất cả máy', exact: true }).click(); await sleep(4500);
  const data = await D('return { n: d.remote.data?.apps?.length || 0, local: d.apps.length, servers: d.remote.data?.servers, names: [...new Set((d.remote.data?.apps || []).map(a => a._serverName))] }');
  check('All servers: apps of this server + the remote in one list', data.n >= data.local * 2 && data.servers === 2 && data.names.includes('NAS phòng khách') && data.names.includes('Máy này'), JSON.stringify(data));
  await p.screenshot({ path: OUT + '/g2-all-servers.png' });
  await p.fill('input[x-model="remote.q"]', 'NAS'); await sleep(400);
  const onlyRemote = await D("return d.remoteApps().every(a => a._serverName === 'NAS phòng khách') && d.remoteApps().length > 0");
  check('Search by server name filters the combined list', onlyRemote);
  await p.fill('input[x-model="remote.q"]', 'bb-none'); await sleep(400);
  await p.screenshot({ path: OUT + '/g3-all-search.png' });

  // Log app máy phụ
  await D("d.openLogs(d.remote.data.apps.find(a => a._server && a.name === 'lg'), d.srv.list[0])");
  await sleep(2500);
  const rl = await D('return { mode: d.logModal.mode, server: d.logModal.server?.name, text: d.logModal.lines, err: d.logModal.error }');
  check('Remote logs open in "last hour" mode (no live stream) with the remote content', rl.mode === '1h' && rl.server === 'NAS phòng khách' && rl.text.includes('cannot connect db'), JSON.stringify(rl));
  await p.screenshot({ path: OUT + '/g4-remote-logs.png' });
  await D('d.closeLogs()'); await sleep(400);

  // Khôi phục app máy phụ
  await p.locator('button:has-text("Khôi phục"):visible').first().click(); await sleep(2500);
  check('Remote restore: backup picker lists the remote backups', await D('return d.restorePicker.open && d.restorePicker.items.length >= 1 && !!d.restorePicker.server'));
  await p.screenshot({ path: OUT + '/g5-remote-restore-pick.png' });
  await D('d.runRestorePicker()'); await sleep(500);
  for (let i = 0; i < 60 && await D('return d.restoreRun.running'); i++) await sleep(1000);
  const rr = await D('return { status: d.restoreRun.status, title: d.restoreRun.title, log: d.restoreRun.log.length }');
  check('Remote restore finishes with the steps shown', rr.status === 'success' && rr.title.startsWith('NAS phòng khách') && rr.log > 0, JSON.stringify(rr));
  await p.screenshot({ path: OUT + '/g6-remote-restore-done.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
