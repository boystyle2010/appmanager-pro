const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = 'http://localhost:8000';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage();
  const D = (code) => p.evaluate((c) => { const d = Alpine.$data(document.body); return (new Function('d', c))(d); }, code);
  const waitFalse = async (expr, t = 180) => { for (let i = 0; i < t; i++) { await sleep(1000); if (!(await D('return ' + expr))) return true; } return false; };
  await p.goto(B + '/'); await sleep(2000); await D("d.lang = 'vi'");
  const cur = await D("return d.apps.find(a => a.name === 'oldcasa').image");
  await D("d.openVersionPickerFor(d.apps.find(a => a.name === 'oldcasa'))"); await sleep(1500); await waitFalse('d.versionPicker.loading', 60);
  const target = cur.endsWith('1.36') ? '1.37' : '1.36';
  await D(`d.versionPicker.selected = '${target}'; d.pickVersion()`); await sleep(1000); await waitFalse('d.updateModal.loading', 60);
  await D('d.startAppUpdate(d.updateModal.preview.tag)'); await waitFalse('d.updateModal.updating', 150);
  const t0 = Date.now(); for (let i = 0; i < 20; i++) { await sleep(250); if ((await D('return d.updateModal.app.image')).endsWith(':' + target)) break; }
  const hdr = await D("return [d.updateModal.app.image, d.updateModal.app.version, !!d.updateModal.preview]");
  console.log('details refreshed after', ((Date.now() - t0) / 1000).toFixed(1), 's ->', JSON.stringify(hdr));
  console.log((hdr[0].endsWith(':' + target) && !hdr[2]) ? 'PASS U6b header shows the new version once refreshed' : 'FAIL U6b');
  await p.screenshot({ path: OUT + '/v06b-after-refresh.png' });
  await b.close();
})();
