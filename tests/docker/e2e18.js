// Kênh phát hành theo biến thể (glances): latest-full có thêm LATEST thường (không có DEV), latest thường có LATEST-FULL + DEV.
// Container thật gl-full / gl-plain chạy image busybox gắn tag nicolargo/glances:latest-full / :latest (chỉ để lấy kênh từ
// Docker Hub thật, không pull glances). AppManager chạy bằng uvicorn, đã tạo admin. argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8795';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ locale: 'vi-VN', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  for (const n of ['gl-full', 'gl-plain']) await ctx.request.post(B + `/api/apps/${n}/check`, { headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  const tags = async (n) => D(`return (d.apps.find(a => a.name === '${n}').channels || []).map(c => c.label)`);
  const full = await tags('gl-full'), plain = await tags('gl-plain');
  check('latest-full: LATEST-FULL + plain LATEST, no DEV', JSON.stringify(full) === '["latest-full","latest"]', JSON.stringify(full));
  check('plain latest: LATEST + LATEST-FULL + DEV', JSON.stringify(plain) === '["latest","latest-full","dev"]', JSON.stringify(plain));
  const shot = async (name, file) => {
    await D(`d.openUpdateModal(d.apps.find(a => a.name === '${name}'))`); await sleep(1800);
    await p.evaluate(() => [...document.querySelectorAll('p')].find(x => /Kênh phát hành/.test(x.textContent))?.scrollIntoView({ block: 'center' })); await sleep(400);
    await p.screenshot({ path: OUT + '/' + file });
  };
  await shot('gl-full', 'v1-full.png');
  check('Window shows the channel buttons with full names', (await p.textContent('body')).includes('latest-full'));
  await p.locator('button:has(span:text-is("latest"))').first().click(); await sleep(700);
  const body = await p.textContent('body');
  check('Switching to the other variant warns that features may differ', body.includes('biến thể image khác'), body.slice(0, 300));
  await p.screenshot({ path: OUT + '/v2-confirm.png' });
  await D('d.confirmModal && (d.confirmModal.open = false); d.closeUpdateModal()'); await sleep(600);
  await shot('gl-plain', 'v3-plain.png');
  await D("d.openUpdateModal(d.apps.find(a => a.name === 'gl-full'))"); await sleep(1500);
  check('Changelog badge names the variant (LATEST-FULL)', await D('return d.changelogChannel()?.label') === 'latest-full');
  await D('d.closeUpdateModal()');
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
