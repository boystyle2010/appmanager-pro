// Trang đăng nhập "máy chủ + máy chiếu": tắt -> ô đăng nhập ẩn; bấm nút nguồn -> LED nhấp nháy, chùm sáng, ô đăng nhập hiện;
// chấm màu đổi màu ánh sáng + nút; đăng nhập thật; lần sau đèn tự bật; khổ máy tính; tắt JavaScript vẫn đăng nhập được.
// argv: OUT, base URL (uvicorn đã tạo admin / Test-Passw0rd!x), [base URL của máy CHƯA có tài khoản]
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
  // Đăng nhập / Đăng ký + cách đăng nhập khác
  const hint = (await p.textContent('body')).includes('Quản trị bật trong Cài đặt');
  await p.getByRole('tab', { name: 'Tạo tài khoản' }).click(); await sleep(500);
  const su = (await p.textContent('body')).includes('Tài khoản do Quản trị tạo') && !(await p.locator('form').isVisible());
  await p.screenshot({ path: OUT + '/l7-signup.png' });
  await p.getByRole('tab', { name: 'Đăng nhập' }).click(); await sleep(400);
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
  await p3.setViewportSize({ width: 1280, height: 1400 }); await sleep(400);
  await p3.setViewportSize({ width: 1280, height: 520 }); await sleep(400); await p3.mouse.wheel(0, 400); await sleep(500);
  const fit = await p3.evaluate(() => ({ sh: document.documentElement.scrollHeight, room: Math.ceil(document.querySelector('.lp-room').getBoundingClientRect().height) }));
  const bm = await p3.evaluate(() => { const r = document.querySelector('[x-ref=mouth]').getBoundingClientRect(); return { y: r.top + r.height / 2 + window.scrollY, cy: Alpine.$data(document.body).beam.cy, sy: window.scrollY }; });
  // không có JS -> ô đăng nhập vẫn hiện
  const ctx4 = await b.newContext({ viewport: { width: 390, height: 844 }, javaScriptEnabled: false });
  const p4 = await ctx4.newPage(); await p4.goto(B + '/login'); await sleep(500);
    const cardVisibleNoJs = await p4.locator('.lp-card').isVisible();
  // Lần đầu (máy chưa có tài khoản, argv[4]): trang vẫn là Đăng nhập; tạo Quản trị ở tab Đăng ký
  let first = null;
  if (process.argv[4]) {
    const F = process.argv[4];
    const c5 = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
    const f = await c5.newPage(); f.on('pageerror', e => errs.push(e.message));
    await f.goto(F + '/login'); await sleep(1500);
    const tabs = await f.getByRole('tab').count();
    const noConfirm = !(await f.locator('input[autocomplete="new-password"]').count());
    await f.fill('input[autocomplete="username"]', 'admin'); await f.fill('input[type="password"]', 'Test-Passw0rd!x');
    await f.click('button[type="submit"]'); await sleep(500);
    const noAcc = (await f.textContent('body')).includes('Máy này chưa có tài khoản');
    await f.getByRole('tab', { name: 'Tạo tài khoản' }).click(); await sleep(500);
    const note = (await f.textContent('body')).includes('Tài khoản đầu tiên là Quản trị');
    await f.screenshot({ path: OUT + '/l8-first-run-signup.png' });
    await f.fill('input[autocomplete="username"]', 'admin');
    const pw = f.locator('input[type="password"]'); await pw.nth(0).fill('Test-Passw0rd!x'); await pw.nth(1).fill('Test-Passw0rd!x');
    await f.click('button[type="submit"]'); await sleep(2500);
    first = { tabs, noConfirm, noAcc, note, url: f.url() };
  }
  const R = [];
  const check = (n, c, d = '') => { R.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
  check('Server off: the sign-in card is hidden, hint shown', vis0 === 'hidden');
  check('Pressing the server power button starts the projector and shows the card', vis1 === 'visible');
  check('Signing in from the lamp page works', url1 === B + '/', url1);
  check('Next visit: already on', vis2 === 'visible');
  check('Without JavaScript the sign-in card is still visible', cardVisibleNoJs);
  check('"Or continue with": SSO off -> hint how an administrator turns it on', hint);
  check('Create account tab explains accounts are created by an administrator (no open sign-up form)', su);
  check('Light beam scrolls with the projector (short window)', bm.sy > 0 && Math.abs(bm.y - bm.cy) < 3, JSON.stringify(bm));
  check('Window made smaller: the page ends with the content (no extra empty area)', fit.sh <= fit.room + 2, JSON.stringify(fit));
  if (first) {
    check('First run: same Sign in / Create account page (no separate "create admin" screen)', first.tabs === 2 && first.noConfirm, JSON.stringify(first));
    check('First run: signing in explains there is no account yet', first.noAcc);
    check('First run: Create account tab creates the administrator account and opens the dashboard', first.note && /\/$/.test(first.url), JSON.stringify(first));
  }
  check('No JavaScript errors', !errs.length, errs.join(' | '));
  console.log(`SUMMARY ${R.filter(Boolean).length} / ${R.length}`);
  await b.close();
})();
