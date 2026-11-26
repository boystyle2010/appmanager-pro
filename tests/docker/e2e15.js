// 16 kênh thông báo: nhóm Chat / Đẩy lên điện thoại / Khác, dấu iPhone, dòng "Nhận được trên", form Email (ô chọn), Bark, Gotify (không có iPhone).
// AppManager chạy bằng uvicorn từ repo ở argv[3] (đã tạo admin). argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8794';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(800); await D("d.openSettingsSection('notify')"); await sleep(1500);
  await D('d.newNotifyChannel()'); await sleep(500);
  const shot = async (name) => { await p.evaluate(() => document.querySelector('[x-model="notifyState.edit.name"]')?.parentElement?.scrollIntoView({ block: 'start' })); await sleep(300); await p.screenshot({ path: OUT + '/' + name }); };
  const types = await D('return d.notifyGroups().flatMap(g => g.types)');
  check('16 channel types in 3 groups', types.length === 16, JSON.stringify(types));
  check('Telegram shows 6 platform icons, no dots on the picker', await p.evaluate(() => [...document.querySelectorAll('svg')].filter(x => x.getAttribute('x-html') === 'platformIcon(pf)' && x.getBoundingClientRect().width > 0).length) === 6
        && await p.evaluate(() => [...document.querySelectorAll('button')].filter(b => /Telegram|Discord|Bark|Signal/.test(b.textContent) && b.querySelector('.rounded-full')).length) === 0);
  for (const w of [390, 320]) {  // iPhone thường và iPhone SE: tên kênh không bị cắt
    await p.setViewportSize({ width: w, height: 844 }); await sleep(300);
    const cut = await p.evaluate(() => [...document.querySelectorAll('button')].filter(b => b.getAttribute('x-text') === null && b.querySelector('span') && /^(Telegram|Discord|Slack|Teams|Google Chat|Mattermost|Matrix|Signal|ntfy|Bark|Pushover|Pushbullet|Gotify|Email|Apprise|Webhook)$/.test(b.textContent.trim()) && (b.scrollWidth > b.clientWidth + 1 || b.querySelector('span').scrollWidth > b.querySelector('span').clientWidth + 1)).map(b => b.textContent.trim()));
    check(`Channel names not cut at ${w}px`, cut.length === 0, JSON.stringify(cut));
  }
  await p.setViewportSize({ width: 390, height: 844 }); await sleep(300);
  await shot('n1-types-telegram.png');
  await D("d.notifyState.edit.type = 'gotify'"); await sleep(300);
  check('Gotify: Android + Web icons and a no-iPhone hint', (await p.textContent('body')).toLowerCase().includes('không có app iphone') && JSON.stringify(await D('return d.notifyPlatforms("gotify")')) === '["android","web"]');
  await shot('n2-gotify-no-ios.png');
  await D("d.notifyState.edit.type = 'bark'"); await sleep(300); await shot('n3-bark.png');
  await D("d.notifyState.edit.type = 'email'; d.notifyState.edit.config.security = 'starttls'"); await sleep(300);
  check('Email form has a security dropdown', await p.locator('select[x-model="notifyState.edit.config[f.k]"]:visible').count() === 1);
  await shot('n4-email.png');
  await D("d.notifyState.edit.type = 'ntfy'"); await sleep(300);
  check('ntfy hint explains upstream-base-url for iPhone', (await p.textContent('body')).includes('upstream-base-url'));
  await shot('n5-ntfy.png');
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
