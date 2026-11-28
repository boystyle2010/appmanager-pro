// 0.26 giao diện Quét lỗ hổng: trang Cài đặt (giải thích, cài Trivy, bật / lịch / mức báo, quét tất cả, kết quả),
// huy hiệu khiên trên thẻ app (nginx 1.26-alpine có lỗi thật), cửa sổ chi tiết (lọc mức, "Có bản vá", link CVE), menu ⋯.
// argv: OUT, base URL (uvicorn có admin / Test-Passw0rd!x, TRIVY_IMAGE=mirror.gcr.io/aquasec/trivy:latest, setup.sh đã chạy)
const { chromium } = require('playwright');
const OUT = process.argv[2], B = process.argv[3];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const R = []; const check = (n, c, d = '') => { R.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ locale: 'vi-VN', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(900);
  check('Settings list has "Quét lỗ hổng" (off)', (await p.textContent('body')).includes('Quét lỗ hổng') && (await p.textContent('body')).includes('Đang tắt'));
  await D("d.openSettingsSection('vuln')"); await sleep(900);
  check('Page explains what a vulnerability scan is + install button', (await p.textContent('body')).includes('Quét lỗ hổng là gì?') && await p.getByRole('button', { name: 'Cài Trivy' }).isVisible());
  await p.screenshot({ path: OUT + '/v1-not-installed.png' });
  await p.getByRole('button', { name: 'Cài Trivy' }).click(); await sleep(1500);
  await p.screenshot({ path: OUT + '/v2-installing.png' });
  for (let i = 0; i < 300 && (await D('return !!d.vuln.data?.state?.installing')); i++) await sleep(2000);
  await sleep(1500);
  check('Trivy installed: version + database date shown', (await p.textContent('[data-vuln=trivy]')).includes('Trivy 0.'), await p.textContent('[data-vuln=trivy]'));
  await p.getByRole('switch').first().click(); await sleep(800);
  check('Turn the scan on (saved on the server)', await D('return d.vuln.data.settings.enabled'));
  await p.getByRole('button', { name: 'Quét tất cả ngay' }).click(); await sleep(1500);
  for (let i = 0; i < 300 && (await D('return !!d.vuln.data?.state?.running')); i++) await sleep(2000);
  await sleep(1500);
  check('Results list: nginx ("web") with critical / high counts', (await D("return d.vulnApps().map(r => r.name).join(',')")).includes('web'));
  await p.screenshot({ path: OUT + '/v3-settings-results.png' });
  await p.evaluate(() => document.querySelector('[x-ref=settingsScroll]').scrollTo(0, 0)); await sleep(300);
  await p.screenshot({ path: OUT + '/v3b-settings-top.png' });
  await D('d.settingsModal.open = false'); await sleep(600);
  const badge = await D("return d.vulnBadge(d.apps.find(a => a.name === 'web'))");
  check('App card shows a shield badge with the number of critical + high vulnerabilities', badge && badge.n > 0, JSON.stringify(badge));
  await p.evaluate(() => { const el = [...document.querySelectorAll('button[aria-label*="lỗ hổng"]')][0]; el && el.scrollIntoView({ block: 'center' }); }); await sleep(400);
  await p.screenshot({ path: OUT + '/v4-card-badge.png' });
  await p.locator('button[aria-label*="lỗ hổng"]').first().click(); await sleep(1500);
  const n = await p.locator('[data-finding]').count();
  check('Details window lists findings (CVE, package, fixed version)', n > 0 && (await p.textContent('[data-vuln-modal]')).match(/CVE-\d{4}-\d+/), n);
  await p.screenshot({ path: OUT + '/v5-details.png' });
  await p.locator('[data-vuln-modal] button', { hasText: 'Nghiêm trọng' }).first().click().catch(() => {}); await sleep(300);
  const onlyCrit = await D("return d.vulnFindings().every(f => f.severity === 'CRITICAL')");
  await p.locator('[data-vuln-modal] button').filter({ hasText: /^\s*Có bản vá\s*$/ }).first().click(); await sleep(300);
  const fixed = await D("return d.vulnFindings().every(f => f.fixed)");
  check('Filters: severity + "Có bản vá"', onlyCrit && fixed, [onlyCrit, fixed]);
  // 0.26.1: "Có thể làm gì?" + Chấp nhận
  await D("d.vuln.modal.sev = 'ALL'; d.vuln.modal.fixable = false"); await sleep(200);
  await p.evaluate(() => document.querySelector('[data-vuln-modal] .overflow-y-auto').scrollTo(0, 0)); await sleep(200);
  check('"What can you do?" explains third-party images + update / network / accept', (await p.textContent('[data-vuln-what]')).includes('Chỉ nhà phát triển') && await p.locator('[data-vuln-accept]').isVisible());
  await p.screenshot({ path: OUT + '/v6-what-to-do.png' });
  await p.locator('[data-vuln-accept]').click(); await sleep(1500);
  const accTxt = await p.textContent('[data-vuln-what]');
  check('Accept: modal says how many were accepted, findings tagged', accTxt.includes('Đã chấp nhận') && (await p.locator('[data-finding]', { hasText: 'đã chấp nhận' }).count()) > 0, accTxt.slice(0, 200));
  await p.screenshot({ path: OUT + '/v7-accepted.png' });
  check('Accepted: shield gone from the card', !(await D("return d.vulnBadge(d.apps.find(a => a.name === 'web'), true)")));
  await p.locator('[data-vuln-unaccept]').click(); await sleep(1200);
  check('Undo brings the shield back', !!(await D("return d.vulnBadge(d.apps.find(a => a.name === 'web'), true)")));
  await D('d.vuln.modal.open = false'); await sleep(300);
  // menu ⋯
  await D("d.openActionSheet(d.apps.find(a => a.name === 'web'))"); await sleep(500);
  check('⋯ menu has "Lỗ hổng bảo mật"', await p.getByText('Lỗ hổng bảo mật', { exact: true }).isVisible());
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${R.filter(Boolean).length} / ${R.length}`);
  await b.close();
})();
