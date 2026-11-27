// Trang đăng nhập "máy chủ + máy chiếu": tắt -> ô đăng nhập ẩn; bấm nút nguồn -> LED nhấp nháy, chùm sáng, ô đăng nhập hiện;
// chấm màu đổi màu ánh sáng + nút; đăng nhập thật; lần sau đèn tự bật; khổ máy tính; tắt JavaScript vẫn đăng nhập được.
// argv: OUT, base URL (uvicorn đã tạo admin / Test-Passw0rd!x)
const { chromium } = require('playwright');
const OUT = process.argv[2], B = process.argv[3] || 'http://localhost:8771';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(B + '/login'); await sleep(1200);
  await p.screenshot({ path: OUT + '/l1-off.png' });
  const vis0 = await p.evaluate(() => getComputedStyle(document.querySelector('.lp-card')).visibility);
  // bấm nút nguồn máy chủ
  await p.locator('.lp-power').click(); await sleep(1400);
  const vis1 = await p.evaluate(() => getComputedStyle(document.querySelector('.lp-card')).visibility);
  await p.screenshot({ path: OUT + '/l3-on-white.png' });
  await p.locator('.lp-dot').nth(3).click(); await sleep(700);
  await p.screenshot({ path: OUT + '/l4-green.png' });
  await p.locator('.lp-dot').nth(0).click(); await sleep(700);
  await p.screenshot({ path: OUT + '/l5-amber.png' });
  // đăng nhập thật
  await p.fill('input[autocomplete="username"]', 'admin'); await p.fill('input[type="password"]', 'Test-Passw0rd!x');
  await p.click('button[type="submit"]'); await sleep(2500);
  const url1 = p.url();
  // lần sau: đèn tự bật
  const p2 = await ctx.newPage(); await ctx.clearCookies(); await p2.goto(B + '/login'); await sleep(1300);
  const vis2 = await p2.evaluate(() => getComputedStyle(document.querySelector('.lp-card')).visibility);
  // máy tính
  const ctx3 = await b.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const p3 = await ctx3.newPage(); await p3.goto(B + '/login'); await sleep(800);
  await p3.locator('.lp-power').click(); await sleep(1400);
  await p3.locator('.lp-dot').nth(1).click(); await sleep(600);
  await p3.screenshot({ path: OUT + '/l6-desktop-cyan.png' });
  // không có JS -> ô đăng nhập vẫn hiện
  const ctx4 = await b.newContext({ viewport: { width: 390, height: 844 }, javaScriptEnabled: false });
  const p4 = await ctx4.newPage(); await p4.goto(B + '/login'); await sleep(500);
    const cardVisibleNoJs = await p4.locator('.lp-card').isVisible();
  const R = [];
  const check = (n, c, d = '') => { R.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
  check('Server off: the sign-in card is hidden, hint shown', vis0 === 'hidden');
  check('Pressing the server power button starts the projector and shows the card', vis1 === 'visible');
  check('Signing in from the lamp page works', url1 === B + '/', url1);
  check('Next visit: already on', vis2 === 'visible');
  check('Without JavaScript the sign-in card is still visible', cardVisibleNoJs);
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${R.filter(Boolean).length} / ${R.length}`);
  await b.close();
})();
