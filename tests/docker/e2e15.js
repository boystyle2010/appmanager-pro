// 17 kênh thông báo: nhóm Chat / Đẩy lên điện thoại / Khác, dấu iPhone, dòng "Nhận được trên", form Email (ô chọn), Bark, Gotify (không có iPhone).
// AppManager chạy bằng uvicorn từ repo ở argv[3] (đã tạo admin). argv: OUT, base URL.
const { chromium } = require('playwright');
const OUT = process.argv[2]; const B = process.argv[3] || 'http://localhost:8794';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = []; const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ locale: 'vi-VN', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const D = (code) => p.evaluate((c) => (new Function('d', c))(Alpine.$data(document.body)), code);
  await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'; d.dataSetup.open = false");
  await D('d.openSettings()'); await sleep(800); await D("d.openSettingsSection('notify')"); await sleep(1500);
  await D('d.newNotifyChannel()'); await sleep(500);
  const shot = async (name) => { await p.evaluate(() => document.querySelector('[x-model="notifyState.edit.name"]')?.parentElement?.scrollIntoView({ block: 'start' })); await sleep(300); await p.screenshot({ path: OUT + '/' + name }); };
  const types = await D('return d.notifyGroups().flatMap(g => g.types)');
  check('17 channel types in 3 groups', types.length === 17, JSON.stringify(types));
  check('Telegram shows 6 platform icons, no dots on the picker', await p.evaluate(() => [...document.querySelectorAll('svg')].filter(x => x.getAttribute('x-html') === 'platformIcon(pf)' && !x.closest('[data-wp]') && x.getBoundingClientRect().width > 0).length) === 6
        && await p.evaluate(() => [...document.querySelectorAll('button')].filter(b => /Telegram|Discord|Bark|Signal/.test(b.textContent) && b.querySelector('.rounded-full')).length) === 0);
  const iconOk = await p.evaluate(() => [...document.querySelectorAll('svg')].filter(x => x.getAttribute('x-html') === 'notifyIcon(tp).svg' && x.innerHTML.length > 20).length);
  check('Every channel button shows its icon (17)', iconOk === 17, iconOk);
  for (const w of [390, 320]) {  // iPhone thường và iPhone SE: tên kênh không bị cắt
    await p.setViewportSize({ width: w, height: 844 }); await sleep(300);
    const cut = await p.evaluate(() => [...document.querySelectorAll('button')].filter(b => b.getAttribute('x-text') === null && b.querySelector('span') && /^(Telegram|Discord|Slack|Teams|Google Chat|Mattermost|Matrix|Signal|Web Push|ntfy|Bark|Pushover|Pushbullet|Gotify|Email|Apprise|Webhook)$/.test(b.textContent.trim()) && (b.scrollWidth > b.clientWidth + 1 || b.querySelector('span').scrollWidth > b.querySelector('span').clientWidth + 1)).map(b => b.textContent.trim()));
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
  // Mã hoá (Bark) + chế độ riêng tư
  await D("d.notifyState.edit.type = 'bark'; d.notifyState.edit.config.encrypt = '1'; d.genNotifyKey(); d.notifyState.edit.private = true"); await sleep(400);
  const kv = await D('return [d.notifyState.edit.config.enc_key.length, d.notifyState.edit.config.enc_iv.length]');
  check('Bark: encryption on generates a 32-char key + 16-char IV', kv[0] === 32 && kv[1] === 16, JSON.stringify(kv));
  await p.evaluate(() => [...document.querySelectorAll('span')].find(x => x.textContent.trim() === 'Mã hoá nội dung tin')?.scrollIntoView({ block: 'start' })); await sleep(300);
  await p.screenshot({ path: OUT + '/n7-bark-encrypt.png' });
  await D("d.notifyState.edit.type = 'telegram'"); await sleep(300);
  check('Telegram: no encryption switch, explains HTTPS + private mode', (await p.textContent('body')).includes('không tự giải mã được') && await p.evaluate(() => [...document.querySelectorAll('button[role=switch]')].filter(b => b.getBoundingClientRect().width > 0).length) >= 1);
  await p.evaluate(() => [...document.querySelectorAll('span')].find(x => x.textContent.trim() === 'Mã hoá nội dung tin')?.scrollIntoView({ block: 'start' })); await sleep(300);
  await p.screenshot({ path: OUT + '/n8-telegram-private.png' });
  // danh sách kênh đã lưu cũng dùng icon
  await D("d.notifyState.edit = null"); await D("return d._postJson('/api/notify/channels', { type: 'bark', name: 'iPhone của mình', private: true, config: { device_key: 'K', encrypt: '1', enc_key: 'K'.repeat(32), enc_iv: '0123456789abcdef' }, events: d.notifyState.events })"); await D('return d.loadNotify()'); await sleep(800);
  await p.evaluate(() => window.scrollTo(0, 0)); await p.screenshot({ path: OUT + '/n6-list.png' });
  check('Saved channel keeps Private mode + encryption (shown in the list)', (await p.textContent('body')).includes('mã hoá') && (await p.textContent('body')).includes('riêng tư'));
  check('Saved channel list uses the app icon', await p.evaluate(() => [...document.querySelectorAll('svg')].some(x => x.getAttribute('x-html') === 'notifyIcon(ch.type).svg' && x.innerHTML.length > 20)));
  await p.evaluate(() => document.querySelector('select[x-model="notifyState.settings.lang"]')?.scrollIntoView({ block: 'center' })); await sleep(300);
  await p.screenshot({ path: OUT + '/n9-lang-select.png' });
  const gap = await p.evaluate(() => { const el = document.querySelector('select[x-model="notifyState.settings.lang"]'); const cs = getComputedStyle(el); return [cs.appearance, el.getBoundingClientRect().width]; });
  check('Language select: vector arrow next to the text (no native arrow, compact width)', gap[0] === 'none' && gap[1] < 140, JSON.stringify(gap));
  check('No emoji stickers in the notification UI', !/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(await p.evaluate(() => document.querySelector('[x-show], body').innerText.replace(/[✓✕→↗]/g, ''))));
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
