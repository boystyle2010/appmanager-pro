// 0.27 ngôn ngữ: trang Ngôn ngữ (7 ngôn ngữ, % đã dịch, góp bản dịch), đổi sang zh / es / de / fr / ja (tải file JSON khi chọn,
// giữ sau khi tải lại, <html lang>), tự chọn theo ngôn ngữ trình duyệt, ngày giờ theo locale, trang đăng nhập (ô chọn ngôn ngữ).
// argv: OUT, base URL (uvicorn có admin / Test-Passw0rd!x)
const { chromium } = require('playwright');
const OUT = process.argv[2], B = process.argv[3];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const R = []; const check = (n, c, d = '') => { R.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
const SETTINGS = { zh: '设置', es: 'Ajustes', de: 'Einstellungen', fr: 'Paramètres', ja: '設定' };
(async () => {
  const b = await chromium.launch();
  const login = async (ctx) => ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'en-US' });
  await login(ctx);
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  const files = []; p.on('request', r => { if (r.url().includes('/static/i18n/')) files.push(r.url()); });
  await p.goto(B + '/'); await sleep(2500); await D('d.dataSetup.open = false');
  check('Browser in English, nothing stored -> English, no language file loaded', (await D('return d.lang')) === 'en' && !files.length, files.join());
  await D('d.openSettings()'); await sleep(600); await D("d.openSettingsSection('language')"); await sleep(700);
  const rows = await p.locator('[x-ref=settingsScroll] button', { hasText: /English|Tiếng Việt|简体中文|Español|Deutsch|Français|日本語/ }).count();
  check('Language page lists 7 languages', rows === 7, rows);
  check('Help translate link (TRANSLATING.md)', (await p.getAttribute('[data-lang-help]', 'href')).includes('TRANSLATING.md'));
  await p.screenshot({ path: OUT + '/l1-language-page.png' });
  for (const [code, word] of Object.entries(SETTINGS)) {
    await D(`return d.setLang('${code}')`); await sleep(700);
    const ok = (await D('return d.lang')) === code && (await D("return d.t('settings')")) === word && (await p.evaluate(() => document.documentElement.lang)) === code;
    check(`Switch to ${code}: texts change ("${word}"), <html lang>`, ok, await D("return d.lang + ' ' + d.t('settings')"));
    if (code === 'zh' || code === 'ja' || code === 'de') {
      await D("d.settingsModal.tab = 'home'"); await sleep(500);
      await p.screenshot({ path: OUT + `/l2-settings-${code}.png` });
      await D("d.openSettingsSection('language')"); await sleep(400);
    }
  }
  check('Each language file loaded once, on demand', files.length === 5, files.length);
  check('Placeholders filled ({n} replaced)', !(await D("return d.tf('svApps', { n: 3 })")).includes('{n}') && (await D("return d.tf('svApps', { n: 3 })")).includes('3'));
  check('Dates follow the language (ja-JP)', (await D('return d.locale()')) === 'ja-JP');
  await p.reload(); await sleep(2500);
  check('Kept after reload (ja)', (await D('return d.lang')) === 'ja' && (await D("return d.t('settings')")) === '設定');
  await D('d.dataSetup.open = false'); await sleep(300);
  await p.screenshot({ path: OUT + '/l3-main-ja.png' });
  await D("return d.setLang('vi')"); await sleep(400);
  check('Back to Vietnamese works', (await D("return d.t('settings')")) === 'Cài đặt');
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  // tự chọn theo trình duyệt (chưa chọn bao giờ)
  const ctx2 = await b.newContext({ viewport: { width: 390, height: 844 }, locale: 'fr-FR' });
  await login(ctx2);
  const p2 = await ctx2.newPage(); await p2.goto(B + '/'); await sleep(2500);
  const lang2 = await p2.evaluate(() => Alpine.$data(document.body).lang);
  check('Browser in French, nothing stored -> French automatically', lang2 === 'fr', lang2);
  // trang đăng nhập
  const ctx3 = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'en-US' });
  const p3 = await ctx3.newPage(); await p3.goto(B + '/login'); await sleep(1200);
  await p3.locator('.lp-power').click(); await sleep(800);
  await p3.locator('[data-lang-select]').selectOption('zh'); await sleep(900);
  const t3 = await p3.textContent('body');
  check('Login page: language picker -> Chinese', t3.includes('欢迎回来') && t3.includes('用户名'), t3.slice(0, 200));
  await p3.screenshot({ path: OUT + '/l4-login-zh.png' });
  await p3.locator('[data-lang-select]').selectOption('es'); await sleep(700);
  check('Login page: Spanish', (await p3.textContent('body')).includes('Iniciar sesión'));
  const p4 = await ctx3.newPage(); await p4.goto(B + '/login'); await sleep(1500);
  check('Login page remembers the language (es)', (await p4.textContent('body')).includes('Iniciar sesión'));
  await b.close();
  console.log(`SUMMARY ${R.filter(Boolean).length} / ${R.length}`);
})();
