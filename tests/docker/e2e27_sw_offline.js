// Trang báo lỗi của Service Worker: máy chủ tắt -> "Chưa kết nối được AppManager" (thay màn hình đen), bật lại -> tự vào trang thật.
// argv: OUT, base URL (uvicorn :8769, đã có admin), S (thư mục dữ liệu ampset). Chạy tay: node e2e27_sw_offline.js $S/shots http://localhost:8769 $S
const { chromium } = require('playwright'); const { execSync } = require('child_process'); const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const B = process.argv[3], S = process.argv[4];
  const b = await chromium.launch(); const c = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const p = await c.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(B + '/login'); await sleep(2500);
  const swOk = await p.evaluate(async () => !!(await navigator.serviceWorker.getRegistration('/')));
  await p.reload(); await sleep(1500);
  const normal = await p.evaluate(() => !!document.querySelector('.lp-power'));
  execSync('pkill -f "port 876[9]"'); await sleep(1500);
  await p.goto(B + '/login').catch(() => {}); await sleep(1500);
  const offline = await p.evaluate(() => document.body.innerText.includes('Chưa kết nối được AppManager'));
  await p.screenshot({ path: process.argv[2] + '/sw-offline.png' });
  execSync(`cd /home/user/appmanager-pro && (APP_DATA_DIR=${S}/ampset nohup python -m uvicorn app.main:app --port 8769 > ${S}/uvset.log 2>&1 &)`); await sleep(9000);
  const back = await p.evaluate(() => !!document.querySelector('.lp-power')).catch(() => false);
  console.log(JSON.stringify({ swOk, normal, offline, back, errs })); await b.close();
})();
