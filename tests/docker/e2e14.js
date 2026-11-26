// 0.18 nhiều máy chủ: Cài đặt → Máy chủ (giải thích giao thức / yêu cầu), thêm máy, thanh chọn máy, app máy kia, cập nhật thật.
// Cần srv_setup.sh. argv: OUT, Token máy phụ.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const TOK = process.argv[3]; const B = 'http://localhost:8793';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  check('No server switcher while no other server is added', !(await p.getByText('Máy này', { exact: true }).isVisible()));
  await D('d.openSettings()'); await sleep(1000);
  await p.getByText('Máy chủ', { exact: true }).click(); await sleep(1000);
  check('Servers section explains protocol and requirements', await p.getByText('Giao thức:', { exact: false }).count() > 0 && await p.getByText('REST API', { exact: false }).count() > 0);
  await p.screenshot({ path: OUT + '/m1-servers-howto.png' });
  await p.getByRole('button', { name: 'Thêm máy chủ' }).click(); await sleep(400);
  await p.fill('input[x-model="srv.form.name"]', 'NAS phòng khách');
  await p.fill('input[x-model="srv.form.url"]', 'http://127.0.0.1:8792');
  await p.fill('input[x-model="srv.form.token"]', TOK);
  await p.getByRole('button', { name: 'Kiểm tra' }).click(); await sleep(2500);
  check('Test shows version / apps / Token permission', await D('return !!d.srv.test?.ok && d.srv.test.scope === "update"'), JSON.stringify(await D('return d.srv.test')));
  await p.screenshot({ path: OUT + '/m2-add-form.png' });
  await p.getByRole('button', { name: 'Lưu', exact: true }).click(); await sleep(2500);
  await p.screenshot({ path: OUT + '/m3-server-list.png' });
  await p.getByRole('button', { name: 'Mở', exact: true }).first().click(); await sleep(3500);
  check('Open switches the dashboard to the other server', await D('return !!d.remote.id && (d.remote.data?.apps || []).length > 0'));
  await p.screenshot({ path: OUT + '/m4-remote-dashboard.png' });
  // cập nhật thật bb-none trên máy phụ
  await D("d.confirmRemoteUpdate(d.remote.data.apps.find(a => a.name === 'bb-none') || { name: 'bb-none', title: 'bb-none' })"); await sleep(400);
  await p.screenshot({ path: OUT + '/m5-confirm.png' });
  await D('d.runConfirmedAction()');
  let st = '';
  for (let i = 0; i < 90; i++) { await sleep(2000); st = await D('return d.remoteJob.status'); if (st === 'success' || st === 'failed') break; }
  check('Remote update finished (log shown in the window)', st === 'success' && (await D('return d.remoteJob.log.length')) > 20, st + ' ' + await D('return d.remoteJob.error'));
  await p.screenshot({ path: OUT + '/m6-job.png' });
  await D('d.remoteJob.open = false'); await sleep(300);
  await p.getByText('Máy này', { exact: true }).click(); await sleep(2500);
  check('Back to this server', await D('return d.remote.id === "" && d.apps.length > 0'));
  await p.screenshot({ path: OUT + '/m7-switcher-local.png' });
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
