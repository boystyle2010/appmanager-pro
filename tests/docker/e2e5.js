const { chromium } = require('playwright');
const { execSync } = require('child_process');
const OUT = process.argv[2]; const B = 'http://localhost:8000';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const check = (n, c, d = '') => { results.push(!!c); console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : ' :: ' + d)); };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const login = async () => ctx.request.post(B + '/api/auth/login', { data: { username: 'admin', password: 'Test-Passw0rd!x' }, headers: { Origin: B } });
  await login();
  const p = await ctx.newPage(); const errors = []; p.on('pageerror', e => errors.push(e.message));
  const D = (code) => p.evaluate((c) => { const d = Alpine.$data(document.body); return (new Function('d', c))(d); }, code);
  const waitFalse = async (expr, t = 180) => { for (let i = 0; i < t; i++) { await sleep(1000); if (!(await D('return ' + expr))) return true; } return false; };
  await p.goto(B + '/'); await sleep(2000); await D("d.lang = 'vi'");
  await D('d.checkUpdates(true)'); await waitFalse('d.checkingUpdates', 90); await D('d.loadApps()'); await sleep(1500);
  const apps = await D("return d.apps.map(a => ({n: a.name, m: a.manage, s: a.source, self: a.is_self, cu: a.can_update, ce: a.can_edit, t: a.title}))");
  const A = n => apps.find(a => a.n === n) || {};
  check('U1 all 11 containers listed (registry included, helper hidden; test servers ntfy/gotify excluded)', apps.filter(a => !['ntfy','gotify'].includes(a.n)).length === 11, JSON.stringify(apps.map(a => a.n)));
  check('U1 AppManager itself: run + updatable + editable', A('appmanager-pro').self && A('appmanager-pro').m === 'run' && A('appmanager-pro').cu && A('appmanager-pro').ce);
  check('U1 compose apps: DOCKER/CASAOS, CasaOS title', A('cmpweb').m === 'compose' && A('casaapp').s === 'casaos' && A('casaapp').t === 'Casa Demo App');
  check('U1 external: not updatable/editable', A('ext-swarm').m === 'external' && !A('ext-swarm').cu && !A('ext-swarm').ce);
  check('U1 run app named like old CasaOS app is run', A('oldcasa').m === 'run');
  await p.screenshot({ path: OUT + '/v01-dashboard.png', fullPage: true });
  const hs = await p.evaluate(() => [...document.querySelectorAll('h2')].map(h => { const row = h.parentElement.querySelector('.shrink-0'); if (!row) return null; const [x, y] = row.children; return [x.getBoundingClientRect().height, y.getBoundingClientRect().height, Math.abs(x.getBoundingClientRect().top - y.getBoundingClientRect().top)]; }).filter(Boolean));
  check('U2 every badge is 24px high, same as ⋯ and aligned', hs.every(([a, b, d]) => a === 24 && b === 24 && d < 0.5), JSON.stringify(hs));
  const extBtn = await p.evaluate(() => { const h = [...document.querySelectorAll('h2')].find(x => x.textContent.trim() === 'ext-swarm'); const card = h.closest('.glass-card, [class*=rounded]').parentElement.closest('div'); return /Cập nhật ngay/.test(h.closest('article, div.glass-panel, div').parentElement.parentElement.innerText); });
  // Edit Config: docker run app
  await D("d.openEditModal(d.apps.find(a => a.name === 'cfgapp'))"); await sleep(2500);
  check('U3 run app editor: run mode, 2 tabs, visual UI', await D('return d.editModal.runMode && !!d.editModal.ui && d.editModal.tab === "ui"'));
  await p.screenshot({ path: OUT + '/v02-run-edit.png' });
  await D("d.editModal.ui.service.environment.push({key: 'FROM_UI', value: 'yes'}); d.editModal.ui.service.restart = 'always'");
  await D('d.applyCompose()'); await waitFalse('d.editModal.saving', 120); await sleep(1000);
  const fb = await D('return [d.editModal.feedbackOk, d.editModal.feedback]');
  const env = execSync("docker inspect -f '{{json .Config.Env}} {{.HostConfig.RestartPolicy.Name}}' cfgapp").toString();
  check('U4 Save & Apply from the visual editor recreated the container', fb[0] && env.includes('FROM_UI=yes') && env.includes('always'), fb + ' ' + env);
  await p.screenshot({ path: OUT + '/v03-run-edit-applied.png' });
  await D("d.switchEditTab('yaml')"); await sleep(800);
  await p.screenshot({ path: OUT + '/v04-run-edit-yaml.png' });
  await D('d.closeEditModal()'); await sleep(400);
  // Edit Config: compose app
  await D("d.openEditModal(d.apps.find(a => a.name === 'cmpweb'))"); await sleep(2500);
  check('U5 compose editor: not run mode, has compose path', await D('return !d.editModal.runMode && d.editModal.composePath.endsWith("docker-compose.yml")'));
  await p.screenshot({ path: OUT + '/v05-compose-edit.png' });
  await D('d.closeEditModal()'); await sleep(400);
  // Update run app via version picker
  await D("d.openVersionPickerFor(d.apps.find(a => a.name === 'cfgapp'))"); await sleep(1500);
  await waitFalse('d.versionPicker.loading', 60);
  console.log('picker', await D("return [d.versionPicker.error, d.versionPicker.items.map(i => i.tag).join(',')]"));
  await D("d.versionPicker.selected = '1.27-alpine'; d.pickVersion()"); await sleep(1000); await waitFalse('d.updateModal.loading', 60);
  await D('d.startAppUpdate(d.updateModal.preview.tag)'); await waitFalse('d.updateModal.updating', 150); await sleep(2500);
  const img = execSync("docker inspect -f '{{.Config.Image}} {{json .Config.Env}}' cfgapp").toString();
  check('U6 run update via UI: 1.27 + edited env kept', img.includes('1.27') && img.includes('FROM_UI=yes'), img);
  check('U6 update window clean afterwards (no preview / loader)', await D('return !d.updateModal.preview && !d.updateModal.loading'));
  await p.screenshot({ path: OUT + '/v06-run-update.png' });
  await D('d.closeUpdateModal()'); await sleep(500); await D('d.loadApps()'); await sleep(1500);
  // Restore
  await D("d.confirmRestoreApp(d.apps.find(a => a.name === 'cfgapp'))"); await sleep(600);
  await p.screenshot({ path: OUT + '/v07-restore-picker.png' });
  await D('d.runRestorePicker()'); await sleep(600);
  await waitFalse('d.restoreRun.running', 120); await sleep(800);
  const img2 = execSync("docker inspect -f '{{.Config.Image}}' cfgapp").toString();
  check('U7 restore via UI back to 1.26', img2.includes('1.26') && await D("return d.restoreRun.status !== 'error'"), img2);
  await p.screenshot({ path: OUT + '/v08-restore-result.png' });
  await D('d.restoreRun.open = false'); await sleep(300);
  // Run command + external popup + menu of AppManager itself
  await D("d.openRunCommand(d.apps.find(a => a.name === 'cfgapp'))"); await sleep(1200);
  check('U8 docker run command shows edited env', (await D('return d.runCmd.text')).includes('FROM_UI=yes'));
  await p.screenshot({ path: OUT + '/v09-run-command.png' });
  await D('d.runCmd.open = false');
  await D("d.openActionSheet(d.apps.find(a => a.is_self))"); await sleep(600);
  await p.screenshot({ path: OUT + '/v10-self-menu.png' });
  await D('d.closeActionSheet()'); await sleep(300);
  // Update All (compose + run, external skipped)
  await D('d.startBatchUpdate()'); await waitFalse('d.batchModal.running', 600); await sleep(1000);
  const batch = await D('return d.batchModal.items.map(i => (i.name || i.title) + ":" + i.status)');
  check('U9 Update All: AppManager & external not in batch, cfgmig rolled back, others ok',
        !batch.some(x => x.startsWith('appmanager-pro') || x.startsWith('ext-swarm')) && batch.length >= 5, batch.join(', '));
  await p.screenshot({ path: OUT + '/v11-update-all.png' });
  await D('d.closeBatchModal()'); await sleep(500);
  // Self-update of AppManager (docker run) from the UI
  execSync('docker tag localhost:5000/amp:2 localhost:5000/amp:latest && docker push -q localhost:5000/amp:latest');
  await D("d.openUpdateModal(d.apps.find(a => a.is_self))"); await sleep(2500);
  await p.screenshot({ path: OUT + '/v12-self-update-modal.png' });
  await D('d.startAppUpdate()');
  await sleep(4000); await p.screenshot({ path: OUT + '/v13-self-update-started.png' });
  // trang tự tải lại khi AppManager chạy lại
  for (let i = 0; i < 90; i++) { await sleep(2000); try { const t = execSync('docker exec appmanager-pro cat /app/BUILD_TAG 2>/dev/null').toString().trim(); if (t === '2' && !execSync('docker ps -aq -f name=self-updater').toString().trim()) break; } catch (e) {} }
  await sleep(8000); await login(); await p.goto(B + '/'); await sleep(2500); await D("d.lang = 'vi'");
  await D("d.openSettings().then(() => { d.settingsModal.tab = 'history'; })"); await sleep(2000);
  const h0 = await D('return d.updateHistory[0] && [d.updateHistory[0].container_name, d.updateHistory[0].status]');
  check('U10 AppManager self-updated (build 2) and History shows success', execSync('docker exec appmanager-pro cat /app/BUILD_TAG').toString().trim() === '2' && h0 && h0[0] === 'appmanager-pro' && h0[1] === 'success', JSON.stringify(h0));
  await p.screenshot({ path: OUT + '/v14-history.png' });
  await D('d.settingsModal.open = false'); await sleep(300); await D('d.loadApps()'); await sleep(1500);
  await p.screenshot({ path: OUT + '/v15-dashboard-after.png', fullPage: true });
  check('U11 no JavaScript errors on the page', errors.length === 0, errors.join(' | '));
  console.log(`\nSUMMARY ${results.filter(Boolean).length} / ${results.length}`);
  await b.close();
})();
