/* AppManager Pro — logic giao diện (Alpine.js) */
    function dashboardApp() {
      const dict = window.AMP_I18N;

      const gradients = [
        'bg-linear-to-br from-sky-500 to-indigo-600',
        'bg-linear-to-br from-emerald-500 to-teal-600',
        'bg-linear-to-br from-violet-500 to-fuchsia-600',
        'bg-linear-to-br from-amber-500 to-orange-600'
      ];

      return {
        lang: localStorage.getItem('amp_lang') || 'vi',
        theme: localStorage.getItem('amp_theme') || 'dark',
        bannerDismissKey: localStorage.getItem('amp_banner_dismissed') || '',
        envMode: 'docker',
        apps: [],
        lastChecked: '',
        checkingUpdates: false,
        summary: { total: 0, running: 0, stopped: 0, casaos: 0, docker: 0, updates: 0 },
        search: '',
        filter: 'all',
        sortMode: (() => { try { return localStorage.getItem('amp_sort') || 'smart'; } catch (_) { return 'smart'; } })(),
        sortMenuOpen: false,
        sortOptions: ['smart', 'name_asc', 'name_desc', 'running', 'stopped'],
        loading: true,
        busyId: null,
        error: '',
        toast: { show: false, message: '' },

        confirmModal: { open: false, tone: 'primary', title: '', message: '', confirmLabel: '', onConfirm: null },
        actionSheet: { open: false, app: null },
        logModal: { open: false, title: '', containerName: '', lines: '', ws: null, mode: 'live', q: '', level: '', server: null, loading: false, info: null, error: '' },
        historyLog: { id: null, text: '', loading: false },
        batchModal: { open: false, running: false, items: [], doneCount: 0, succeeded: 0, failed: 0, logs: '', ws: null },
        deployModal: {
          open: false, tab: 'yaml', appName: '', rawYaml: '',
          quick: { app_name: '', title: '', image: '', icon: '', ports: [{host:'', container:'', protocol:'tcp'}], volumes: [], environment: [{key:'TZ', value:'America/Denver'}] },
          feedback: '', feedbackOk: true, deploying: false, done: false, logs: '', ws: null
        },
        updateModal: {
          open: false, loading: false, updating: false, checking: false, app: null,
          changelogHtml: '', changelogError: '', releaseTag: '', releaseUrl: '',
          autoUpdate: false, policy: null, policySaving: false, customRepo: '', showRepoInput: false, updateLogs: '', ws: null, preview: null
        },
        editModal: {
          open: false, loading: false, saving: false, tab: 'ui',
          app: null, composePath: '', rawYaml: '', ui: null, otherComposeFiles: [], skippedComposeFiles: [], dupBusy: false,
          backups: [], feedback: '', feedbackOk: true, feedbackLogs: '',
          sec: { container: true, ports: true, volumes: false, env: false, casaos: false }
        },
        uninstallModal: {
          open: false, running: false, app: null,
          removeCompose: true, removeImages: false, removeAppdata: false,
          confirmName: '', error: ''
        },
        taskModal: { open: false, connected: false, data: null, ws: null },
        taskSort: 'cpu',
        settingsModal: { open: false, tab: 'home' },
        settingsBase: null,
        // Giao diện theo thiết bị (localStorage amp_ui): xem trước ngay, Lưu / Huỷ ở thanh thay đổi
        ui: (() => { const d = { accent: 'sky', text: 'm', radius: 'soft', icons: 'tint', appIcon: 'default' };
          try { return { ...d, ...JSON.parse(localStorage.getItem('amp_ui') || '{}') }; } catch (_) { return d; } })(),
        uiBase: null,
        settingsForm: {
          check_interval_hours: 6, auto_update_enabled: false,
          auto_update_time: '03:30', prune_old_images: true, auto_rollback: true, health_wait_seconds: 25,
          auto_prune_enabled: false, auto_prune_freq: 'weekly', auto_prune_weekday: 6, auto_prune_time: '04:00',
          auto_prune_images: 'dangling', auto_prune_cache: true, auto_prune_next_run: '', auto_prune_last: '',
          backup_before_update: true, backup_max_mb: 2048, backup_file_max_mb: 50, backup_keep: 3,
          github_token: '', has_github_token: false
        },
        storageState: { loading: false, pruning: false, data: null, lastFreed: '' },
        pruneOpts: {
          prune_images: true, all_unused_images: false,
          prune_build_cache: true, prune_containers: false, prune_volumes: false
        },
        updateHistory: [],
        security: { loading: false, totp_enabled: false, backup_codes_left: 0, setup: null, code: '',
                    backupCodes: [], disablePw: '', disableCode: '', regenCode: '', busy: false },
        pwForm: { current: '', next: '', confirm: '', busy: false },
        auditItems: [], auditUser: '',
        me: { username: '', role: 'admin', auth_source: 'local' },
        cfgState: { loading: false, sections: [], current: {}, safety: [], exp: { pw: '', pw2: '', sel: {}, busy: false, error: '' },
                    imp: { name: '', text: '', pw: '', info: null, sel: {}, busy: false, error: '', result: null } },
        ssoState: { cfg: null, form: {}, secret: '', redirect: '', loading: false, saving: false, testing: false, test: null, error: '', saved: false },
        usersState: { list: [], loading: false, form: { open: false, isNew: true, username: '', role: 'viewer', password: '', disabled: false, busy: false, error: '' } },
        backupsState: { loading: false, items: [], busyFile: '' },
        restorePicker: { open: false, app: null, items: [], selected: '', server: null },
        versionPicker: { open: false, loading: false, error: '', items: [], selected: '' },
        apiDocs: { open: false },
        checkingOne: {},
        autoCfg: { enabled: false, time: '03:30' },
        srv: { list: [], loaded: false, statusBusy: false, form: { open: false, id: '', name: '', url: '', token: '', verify_tls: true }, test: null, busy: false, error: '' },
        remote: { id: '', loading: false, data: null, error: '', busy: '', checking: false, q: '' },
        remoteJob: { open: false, server: null, app: '', id: '', status: '', log: '', result: {}, error: '' },
        tokenState: { loading: false, items: [], loaded: false, form: { open: false, name: '', scope: 'read', days: 90, ips: '' }, created: '', busy: false, error: '', examples: false },
        dataFolders: { open: false, mode: 'list', folder: null, newPath: '', check: null, busy: false, error: '' },
        dataSetup: { open: false, step: 'intro', status: null, manualPath: '', busy: false, error: '', candidates: [], selected: [], elapsed: 0, source: '' },
        composeHint: { open: false, app: null, loading: false, busy: false, preview: null, folder: '', yaml: '', log: '', error: '', done: false },
        wp: { supported: false, secure: false, ios: false, standalone: false, perm: 'default', publicKey: '', devices: [], thisEp: '', name: '', busy: false, msg: '', ok: true, showHttps: false },
        notifyState: { loading: false, channels: [], settings: { quiet_enabled: false, quiet_start: '22:00', quiet_end: '07:00', disk_pct: 90, lang: 'vi' }, events: [], critical: [], edit: null, busy: false, msg: '', ok: true, testing: '' },
        apiStatus: { loading: false, sources: [], logins: [], form: { registry: 'docker.io', custom: '', username: '', token: '' }, busy: false, msg: '', ok: true },
        runCmd: { open: false, app: null, text: '', loading: false, error: '' },
        dupPopup: { open: false, loading: false, busy: false, app: null, composePath: '', files: [] },
        updateAllExcluded: [],
        updateAllPicker: { open: false, selected: [], saving: false },
        tagMenu: { open: false, loading: false, items: [], error: '', image: '' },
        restoreRun: { open: false, running: false, title: '', version: '', status: '', message: '', log: [], elapsed: 0, timer: null },
        histOpen: {},
        histData: {},
        histTotalOpen: false,
        filterTabs: [
          { id: 'all', labelKey: 'all' },
          { id: 'updates', labelKey: 'tabUpdates' },
          { id: 'running', labelKey: 'tabRunning' },
          { id: 'stopped', labelKey: 'tabStopped' },
          { id: 'casaos', labelKey: 'tabCasaos' },
          { id: 'docker', labelKey: 'tabDocker' },
        ],

        t(key) { return (dict[this.lang] || dict.en)[key] || key; },

        get showUpdateBanner() {
          if (this.summary.updates <= 0) return false;
          const currentKey = `${this.summary.updates}:${this.lastChecked}`;
          return this.bannerDismissKey !== currentKey;
        },

        dismissUpdateBanner() {
          const currentKey = `${this.summary.updates}:${this.lastChecked}`;
          this.bannerDismissKey = currentKey;
          localStorage.setItem('amp_banner_dismissed', currentKey);
        },

        askConfirm({ tone = 'primary', title, message, confirmLabel, onConfirm }) {
          this.confirmModal = { open: true, tone, title, message, confirmLabel, onConfirm };
        },

        closeConfirm() { this.confirmModal.open = false; this.confirmModal.onConfirm = null; },

        runConfirmedAction() {
          const fn = this.confirmModal.onConfirm;
          this.closeConfirm();
          if (typeof fn === 'function') fn();
        },

        confirmStop(app) {
          this.askConfirm({
            tone: 'danger', title: this.t('confirmStopTitle'),
            message: `"${app.title}" ${this.t('confirmStopMsg')}`,
            confirmLabel: this.t('stop'), onConfirm: () => this.runAction(app, 'stop')
          });
        },

        confirmRestart(app) {
          this.askConfirm({
            tone: 'primary', title: this.t('confirmRestartTitle'),
            message: `"${app.title}" ${this.t('confirmRestartMsg')}`,
            confirmLabel: this.t('restart'), onConfirm: () => this.runAction(app, 'restart')
          });
        },

        confirmAppUpdate() {
          const app = this.updateModal.app;
          if (!app) return;
          const extra = app.target_tag
            ? (this.lang === 'vi' ? ` và nâng tag lên ${app.target_tag}` : ` and bump tag to ${app.target_tag}`)
            : '';
          this.askConfirm({
            tone: app.raw_has_update ? 'update' : 'primary',
            title: this.t('confirmUpdateTitle'),
            message: `${this.t('confirmUpdateMsg')} "${app.title}"${extra}?`,
            confirmLabel: app.raw_has_update ? this.t('updateNow') : this.t('forcePull'),
            onConfirm: () => this.startAppUpdate()
          });
        },

        get selfApp() { return this.apps.find(a => a.is_self) || null; },

        // App có bản cập nhật & cập nhật được; và phần được chọn cho "Cập nhật tất cả"
        get updatableApps() { return this.apps.filter(a => a.has_update && a.can_update); },
        get updateAllTargets() { return this.updatableApps.filter(a => !this.updateAllExcluded.includes(a.name)); },

        confirmBatchUpdate() {
          const n = this.updateAllTargets.length, total = this.updatableApps.length;
          if (!n) { this.openUpdateAllPicker(); return; }
          const skipped = total - n;
          this.askConfirm({
            tone: 'update', title: this.t('confirmBatchTitle'),
            message: `${n} ${this.t('confirmBatchMsg')}` + (skipped ? ` ${this.t('updateAllSkippedNote').replace('{n}', skipped)}` : ''),
            confirmLabel: `${this.t('updateAll')} (${n})`,
            onConfirm: () => this.startBatchUpdate()
          });
        },

        openUpdateAllPicker() {
          this.updateAllPicker = {
            open: true, saving: false,
            selected: this.updatableApps.filter(a => !this.updateAllExcluded.includes(a.name)).map(a => a.name)
          };
        },

        toggleUpdateAllPick(name) {
          const s = this.updateAllPicker.selected;
          this.updateAllPicker.selected = s.includes(name) ? s.filter(x => x !== name) : [...s, name];
        },

        async saveUpdateAllPicker() {
          const p = this.updateAllPicker;
          // Loại trừ = app có update bị bỏ chọn + app đã loại trừ trước đó hiện không có update (giữ lựa chọn cũ)
          const visible = this.updatableApps.map(a => a.name);
          const names = [...visible.filter(n => !p.selected.includes(n)),
                         ...this.updateAllExcluded.filter(n => !visible.includes(n))];
          p.saving = true;
          try {
            const { res, data } = await this._postJson('/api/update-all/excluded', { names });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.updateAllExcluded = data.excluded || [];
            p.open = false;
          } catch (err) { this.showToast(err.message); }
          finally { p.saving = false; }
        },

        confirmRollback(filename) {
          this.askConfirm({
            tone: 'update', title: this.t('confirmRollbackTitle'),
            message: `${filename} — ${this.t('confirmRollbackMsg')}`,
            confirmLabel: this.t('rollbackBtn'), onConfirm: () => this.rollbackCompose(filename)
          });
        },

        confirmPrune() {
          this.askConfirm({
            tone: 'update', title: this.t('confirmPruneTitle'),
            message: this.t('confirmPruneMsg'),
            confirmLabel: this.t('pruneNowBtn'), onConfirm: () => this.runPrune()
          });
        },

        // ---------------- + Deploy New App ----------------
        openDeployModal() {
          this.deployModal = {
            open: true, tab: 'yaml', appName: '', rawYaml: '',
            quick: {
              app_name: '', title: '', image: '', icon: '',
              ports: [{host:'', container:'', protocol:'tcp'}],
              volumes: [], environment: [{key:'TZ', value:'America/Denver'}]
            },
            feedback: '', feedbackOk: true, deploying: false, done: false, logs: '', ws: null
          };
        },

        closeDeployModal() {
          if (this.deployModal.deploying) return;
          if (this.deployModal.ws) this.deployModal.ws.close();
          this.deployModal.open = false;
        },

        loadSampleCompose() {
          this.deployModal.appName = 'homepage-demo';
          this.deployModal.rawYaml = `name: homepage-demo\n\nservices:\n  homepage-demo:\n    image: nginx:alpine\n    container_name: homepage-demo\n    restart: unless-stopped\n    ports:\n      - target: 80\n        published: "8880"\n        protocol: tcp\n\nx-casaos:\n  architectures:\n    - amd64\n    - arm64\n  main: homepage-demo\n  category: Utilities\n  index: /\n  port_map: "8880"\n  scheme: http\n  title:\n    en_US: Nginx Demo\n`;
        },

        async switchDeployTab(nextTab) {
          if (nextTab === this.deployModal.tab) return;
          this.deployModal.feedback = '';
          if (this.deployModal.tab === 'quick' && nextTab === 'yaml' && this.deployModal.quick.image.trim()) {
            const ok = await this._generateDeployYamlFromQuick();
            if (!ok) return;
          }
          this.deployModal.tab = nextTab;
        },

        async _generateDeployYamlFromQuick() {
          const res = await fetch('/api/deploy/generate', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...this.deployModal.quick, app_id: this.deployModal.quick.app_name })
          });
          const data = await res.json();
          if (!res.ok) {
            this.deployModal.feedbackOk = false;
            this.deployModal.feedback = data.detail || 'Invalid form values';
            return false;
          }
          this.deployModal.appName = data.app_id || this.deployModal.quick.app_name;
          this.deployModal.rawYaml = data.raw_yaml;
          return true;
        },

        async validateDeploy() {
          this.deployModal.feedback = '';
          if (this.deployModal.tab === 'quick') {
            if (!(await this._generateDeployYamlFromQuick())) return;
          }
          const res = await fetch('/api/deploy/validate', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ raw_yaml: this.deployModal.rawYaml })
          });
          const data = await res.json();
          this.deployModal.feedbackOk = !!data.ok;
          this.deployModal.feedback = data.message || data.detail || '';
        },

        async startDeploy() {
          this.deployModal.feedback = '';
          if (this.deployModal.tab === 'quick') {
            if (!(await this._generateDeployYamlFromQuick())) return;
          }
          if (!this.deployModal.rawYaml.trim()) {
            this.deployModal.feedbackOk = false;
            this.deployModal.feedback = 'YAML content cannot be empty.';
            return;
          }

          this.deployModal.deploying = true;
          this.deployModal.done = false;
          this.deployModal.logs = '';

          const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
          const ws = new WebSocket(`${proto}//${window.location.host}/ws/deploy`);
          this.deployModal.ws = ws;

          let deployOk = false;
          ws.onopen = () => {
            ws.send(JSON.stringify({
              app_id: this.deployModal.appName,
              raw_yaml: this.deployModal.rawYaml
            }));
          };

          ws.onmessage = (event) => {
            let text = String(event.data);
            if (text.includes('__DEPLOY_OK__')) {
              deployOk = true;
              text = text.replace('__DEPLOY_OK__\n', '').replace('__DEPLOY_OK__', '');
            }
            this.deployModal.logs += text;
            this.$nextTick(() => { const b = this.$refs.deployLogBox; if (b) b.scrollTop = b.scrollHeight; });
          };

          ws.onclose = (event) => {
            this.deployModal.deploying = false;
            this.deployModal.done = true;
            this.deployModal.ws = null;
            if (event.code === 4401) { window.location.href = '/login'; return; }
            if (deployOk) {
              const name = this.deployModal.appName || '';
              this.showToast(this.lang === 'vi' ? `Đã cài ${name} thành công ✓` : `Deployed ${name} ✓`);
              this.loadApps();
            }
          };
        },

        // ---------------- Storage & Prune SSD ----------------
        async loadStorage() {
          this.storageState.loading = true;
          try {
            const res = await fetch('/api/system/storage');
            if (res.ok) this.storageState.data = await res.json();
          } finally {
            this.storageState.loading = false;
          }
        },

        async runPrune() {
          this.storageState.pruning = true;
          this.storageState.lastFreed = '';
          try {
            const res = await fetch('/api/system/prune', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(this.pruneOpts)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Prune failed');
            this.storageState.data = data.storage;
            const msg = this.lang === 'vi'
              ? `Đã giải phóng ${data.freed_display} dung lượng SSD ✓`
              : `Freed ${data.freed_display} of SSD space ✓`;
            this.storageState.lastFreed = msg;
            this.showToast(msg);
            if (this.pruneOpts.prune_containers) await this.loadApps();
          } catch (err) {
            this.showToast(err.message);
          } finally {
            this.storageState.pruning = false;
          }
        },

        async init() {
          this.$watch(() => [this.confirmModal, this.actionSheet, this.logModal, this.batchModal, this.deployModal, this.updateModal,
                             this.editModal, this.uninstallModal, this.taskModal, this.settingsModal, this.restorePicker, this.restoreRun, this.updateAllPicker, this.versionPicker, this.dupPopup, this.dataSetup, this.dataFolders, this.tokenState.form, this.apiDocs, this.srv.form, this.remoteJob, this.composeHint, this.runCmd, this.usersState.form].some(m => m && m.open), (open) => {
            const b = document.body, h = document.documentElement;
            if (open) {
              this._lockY = window.scrollY || 0;
              b.style.top = `-${this._lockY}px`;
              b.classList.add('modal-open'); h.classList.add('modal-open');
            } else {
              b.classList.remove('modal-open'); h.classList.remove('modal-open');
              b.style.top = '';
              window.scrollTo(0, this._lockY || 0);
            }
          });
          // Bấm thông báo "có bản cập nhật" -> mở thẳng danh sách cần cập nhật
          try {
            const q = new URLSearchParams(location.search);
            if (q.get('filter') === 'updates') { this.filter = 'updates'; history.replaceState(null, '', location.pathname); }
            else if (q.has('r')) history.replaceState(null, '', location.pathname);  // sau "Xoá bộ nhớ đệm"
          } catch (e) {}
          await this.loadMe();
          await this.loadApps();
          if (this.isAdmin()) this.checkDataSetup();
          this.loadServers(true);
          const stale = !this.lastChecked || (Date.now() - new Date(this.lastChecked).getTime()) > 3600000;
          if (stale && !this.checkingUpdates && this.canUpdate()) this.checkUpdates(true);
        },

        // ---------------- Tài khoản & quyền (0.22) ----------------
        async loadMe() {
          try {
            const res = await fetch('/api/auth/me');
            if (res.status === 401) { window.location.href = '/login'; return; }
            if (res.ok) this.me = await res.json();
          } catch (_) {}
        },
        isAdmin() { return this.me.role === 'admin'; },
        canUpdate() { return this.me.role === 'admin' || this.me.role === 'operator'; },
        roleLabel(r) { return this.t('role_' + (r || 'admin')); },

        async loadUsers() {
          const st = this.usersState;
          st.loading = true;
          try {
            const res = await fetch('/api/users');
            if (res.ok) st.list = (await res.json()).users || [];
          } catch (_) {}
          finally { st.loading = false; }
        },

        openUserForm(u = null) {
          this.usersState.form = u
            ? { open: true, isNew: false, username: u.username, role: u.role, password: '', disabled: u.disabled, busy: false, error: '', self: u.username === this.me.username, user: u }
            : { open: true, isNew: true, username: '', role: 'viewer', password: '', disabled: false, busy: false, error: '', self: false, user: null };
        },

        async saveUserForm() {
          const f = this.usersState.form;
          f.busy = true; f.error = '';
          try {
            const body = { new: f.isNew, username: f.username.trim(), role: f.role, password: f.password || null };
            if (!f.isNew) body.disabled = f.disabled;
            const { res, data } = await this._postJson('/api/users', body);
            if (!res.ok) throw new Error(data.detail || 'Failed');
            f.open = false;
            this.showToast(f.isNew ? this.t('usAdded').replace('{u}', body.username) : this.t('usSaved').replace('{u}', body.username));
            if (data.self_changed) { await this.loadMe(); if (!this.isAdmin()) { this.settingsModal.tab = 'home'; } }
            await this.loadUsers();
          } catch (err) { f.error = err.message; }
          finally { f.busy = false; }
        },

        confirmDeleteUser() {
          const f = this.usersState.form;
          this.askConfirm({
            tone: 'danger', title: this.t('usDeleteTitle').replace('{u}', f.username), message: this.t('usDeleteMsg'),
            confirmLabel: this.t('delete'),
            onConfirm: async () => {
              const { res, data } = await this._postJson('/api/users/delete', { username: f.username });
              if (!res.ok) { this.showToast(data.detail || 'Failed'); return; }
              f.open = false;
              this.showToast(this.t('usDeleted').replace('{u}', f.username));
              this.loadUsers();
            }
          });
        },

        // ---------------- Sao lưu / khôi phục cấu hình AppManager (0.24) ----------------
        async loadConfigBackup() {
          const st = this.cfgState;
          st.loading = true;
          try {
            const res = await fetch('/api/config/sections');
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            st.sections = data.sections; st.current = data.current; st.safety = data.safety || [];
            if (!Object.keys(st.exp.sel).length) data.sections.forEach(x => { st.exp.sel[x] = true; });
          } catch (err) { this.showToast(err.message); }
          finally { st.loading = false; }
        },

        cfgCount(sum, sec) {
          const x = (sum || {})[sec];
          if (!x) return '';
          if (sec === 'sso') return x.issuer ? (x.enabled ? this.t('cfgSsoOn').replace('{p}', x.label || 'SSO') : this.t('cfgSsoOff')) : this.t('cfgNone');
          return x.count ? this.t('cfgItems').replace('{n}', x.count) : this.t('cfgNone');
        },

        _download(name, text) {
          const blob = new Blob([text], { type: 'application/octet-stream' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
          setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
        },

        async exportConfig() {
          const e = this.cfgState.exp;
          e.error = '';
          if (e.pw.length < 8) { e.error = this.t('cfgPwShort'); return; }
          if (e.pw !== e.pw2) { e.error = this.t('pwMismatch'); return; }
          e.busy = true;
          try {
            const sections = this.cfgState.sections.filter(x => e.sel[x]);
            const { res, data } = await this._postJson('/api/config/export', { password: e.pw, sections });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this._download(data.filename, data.data);
            this.showToast(this.t('cfgExported').replace('{f}', data.filename));
            e.pw = ''; e.pw2 = '';
          } catch (err) { e.error = err.message; }
          finally { e.busy = false; }
        },

        pickConfigFile(ev) {
          const f = ev.target.files && ev.target.files[0];
          const i = this.cfgState.imp;
          Object.assign(i, { name: '', text: '', info: null, sel: {}, error: '', result: null });
          if (!f) return;
          if (f.size > 20 * 1024 * 1024) { i.error = this.t('cfgTooBig'); return; }
          const r = new FileReader();
          r.onload = () => { i.name = f.name; i.text = String(r.result || ''); };
          r.onerror = () => { i.error = this.t('cfgReadFail'); };
          r.readAsText(f);
        },

        async inspectConfig() {
          const i = this.cfgState.imp;
          i.busy = true; i.error = ''; i.info = null; i.result = null;
          try {
            const { res, data } = await this._postJson('/api/config/inspect', { data: i.text, password: i.pw });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            i.info = data; i.sel = {};
            (data.header.sections || []).forEach(x => { i.sel[x] = true; });
          } catch (err) { i.error = err.message; }
          finally { i.busy = false; }
        },

        confirmRestoreConfig() {
          const i = this.cfgState.imp;
          const secs = (i.info?.header.sections || []).filter(x => i.sel[x]);
          if (!secs.length) { i.error = this.t('cfgPickOne'); return; }
          const acc = secs.includes('accounts') && i.info.summary.accounts;
          const lost = acc && !acc.items.some(u => u.username.toLowerCase() === this.me.username.toLowerCase());
          this.askConfirm({
            tone: 'danger', title: this.t('cfgRestoreTitle'),
            message: this.t('cfgRestoreMsg').replace('{s}', secs.map(x => this.t('cfgSec_' + x)).join(', ')) + (lost ? ' ' + this.t('cfgRestoreLoseMe') : ''),
            confirmLabel: this.t('cfgRestoreBtn'), onConfirm: () => this.restoreConfig(secs)
          });
        },

        async restoreConfig(secs) {
          const i = this.cfgState.imp;
          i.busy = true; i.error = '';
          try {
            const { res, data } = await this._postJson('/api/config/restore', { data: i.text, password: i.pw, sections: secs });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            i.result = data; i.pw = '';
            this.showToast(this.t('cfgRestored'));
            if (data.signed_out) { setTimeout(() => { window.location.href = '/login'; }, 2500); return; }
            await this.loadMe(); this.loadConfigBackup(); this.loadApps();
          } catch (err) { i.error = err.message; }
          finally { i.busy = false; }
        },

        // ---------------- SSO / OIDC (0.23) ----------------
        async loadSso() {
          const st = this.ssoState;
          st.loading = true; st.error = ''; st.test = null; st.saved = false;
          try {
            const res = await fetch('/api/sso');
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            st.cfg = data.config; st.form = { ...data.config }; st.secret = ''; st.redirect = data.redirect_uri;
          } catch (err) { st.error = err.message; }
          finally { st.loading = false; }
        },

        _ssoBody() {
          const f = this.ssoState.form;
          const body = {};
          for (const k of ['enabled', 'label', 'issuer', 'client_id', 'scopes', 'username_claim', 'groups_claim', 'admin_groups', 'operator_groups',
                           'viewer_groups', 'default_role', 'auto_create', 'link_existing', 'verify_tls', 'public_url']) body[k] = f[k];
          if (this.ssoState.secret) body.client_secret = this.ssoState.secret;
          return body;
        },

        async testSso() {
          const st = this.ssoState;
          st.testing = true; st.test = null;
          try {
            const { data } = await this._postJson('/api/sso/test', this._ssoBody());
            st.test = data;
          } catch (err) { st.test = { ok: false, error: err.message }; }
          finally { st.testing = false; }
        },

        async saveSso() {
          const st = this.ssoState;
          st.saving = true; st.error = ''; st.saved = false;
          try {
            const { res, data } = await this._postJson('/api/sso', this._ssoBody());
            if (!res.ok) throw new Error(data.detail || 'Failed');
            st.cfg = data.config; st.form = { ...data.config }; st.secret = ''; st.redirect = data.redirect_uri; st.saved = true;
            this.showToast(this.t('ssoSaved'));
          } catch (err) { st.error = err.message; }
          finally { st.saving = false; }
        },

        // Người có trong nhật ký (để lọc): tài khoản + Token + tên đã xuất hiện
        auditPeople() {
          const names = new Set(this.usersState.list.map(u => u.username));
          this.auditItems.forEach(a => { if (a.username) names.add(a.username); });
          if (this.auditUser) names.add(this.auditUser);
          return [...names].sort((a, b) => a.localeCompare(b));
        },

        handleShortcut(e) {
          if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA' && this.$refs.searchInput) {
            e.preventDefault(); this.$refs.searchInput.focus();
          }
        },

        avatarGradient(title) {
          let h = 0;
          for (let i = 0; i < title.length; i++) h = title.charCodeAt(i) + ((h << 5) - h);
          return gradients[Math.abs(h) % gradients.length];
        },

        shortImage(img) { return (img || '').replace(/^docker\.io\/(library\/)?/, ''); },

        formatRelativeTime(iso) {
          if (!iso) return '';
          const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
          if (mins < 1) return this.lang === 'vi' ? 'vừa xong' : 'just now';
          if (mins < 60) return `${mins}m`;
          const hrs = Math.floor(mins / 60);
          return `${hrs}h ${mins % 60}m`;
        },

        setLang(code) { this.lang = code; localStorage.setItem('amp_lang', code); },

        // Xoá bộ nhớ đệm giao diện (PWA / Safari đôi khi giữ bản cũ): xoá Cache Storage, tải lại các file giao diện
        // bỏ qua bộ nhớ đệm HTTP, cập nhật Service Worker (KHÔNG gỡ — Web Push cần nó), rồi tải lại trang.
        // Giữ nguyên: đăng nhập (cookie), cài đặt Giao diện / ngôn ngữ (localStorage), thiết bị nhận Web Push.
        cacheBusy: false,
        cacheState: { stats: null, busy: '' },
        fmtBytes(b) { b = b || 0; return b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' : (b / 1048576).toFixed(1) + ' MB'; },
        async loadCaches() {
          try { const r = await fetch('/api/system/caches'); if (r.ok) this.cacheState.stats = await r.json(); } catch (_) {}
        },
        // Bộ đệm trên máy chủ (Quản trị): có hộp xác nhận + nói rõ sẽ mất gì / giữ gì
        clearServerCache(kind) {
          this.askConfirm({ tone: kind === 'resources' ? 'danger' : 'primary', title: this.t('cc_' + kind), message: this.t('ccConfirm_' + kind),
            confirmLabel: this.t('ccClearBtn'), onConfirm: async () => {
              this.cacheState.busy = kind;
              try {
                const { res, data } = await this._postJson('/api/system/caches/clear', { kind });
                if (!res.ok) throw new Error(data.detail || 'Failed');
                this.showToast(this.t('ccDone').replace('{n}', data.cleared ?? 0));
                if (kind === 'updates') this.checkUpdates(true);
                if (kind === 'http' && this.loadApiStatus) this.loadApiStatus();
              } catch (e) { this.showToast(e.message); }
              finally { this.cacheState.busy = ''; this.loadCaches(); }
            } });
        },
        // Đưa Giao diện trên thiết bị này + đèn trang đăng nhập về mặc định (không đụng cài đặt trên máy chủ)
        resetDeviceUi() {
          this.askConfirm({ tone: 'primary', title: this.t('ccUiReset'), message: this.t('ccConfirm_ui'), confirmLabel: this.t('ccResetBtn'), onConfirm: () => {
            ['amp_ui', 'amp_lamp_on', 'amp_lamp_color', 'amp_banner_dismissed'].forEach(k => { try { localStorage.removeItem(k); } catch (_) {} });
            this.ui = { accent: 'sky', text: 'm', radius: 'soft', icons: 'tint', appIcon: 'default' };
            this.uiBase = { ...this.ui }; this.applyUi();
            this.showToast(this.t('ccUiResetDone'));
          } });
        },
        async clearCache() {
          if (this.cacheBusy) return;
          this.cacheBusy = true;
          try { if (window.caches) for (const k of await caches.keys()) await caches.delete(k); } catch (_) {}
          try {
            const urls = [...document.querySelectorAll('link[rel="stylesheet"][href^="/static/"], script[src^="/static/"]')]
              .map(el => el.getAttribute('href') || el.getAttribute('src'));
            urls.push('/', '/login', '/manifest.json', '/sw.js');
            await Promise.all(urls.map(u => fetch(u, { cache: 'reload', credentials: 'same-origin' }).catch(() => null)));
          } catch (_) {}
          try { const reg = await navigator.serviceWorker?.getRegistration('/'); await reg?.update(); } catch (_) {}
          try { sessionStorage.removeItem('amp_reload_for'); } catch (_) {}
          this.showToast(this.t('clearCacheDone'));
          setTimeout(() => window.location.replace('/?r=' + Date.now()), 700);
        },

        // ---------------- Giao diện ----------------
        uiOptions() {
          return {
            accent: [{ id: 'sky', c: '#38bdf8' }, { id: 'violet', c: '#8b5cf6' }, { id: 'pink', c: '#ec4899' }, { id: 'emerald', c: '#10b981' }, { id: 'amber', c: '#f59e0b' }],
            text: [{ id: 's', px: 12 }, { id: 'm', px: 15 }, { id: 'l', px: 18 }, { id: 'xl', px: 21 }],
            radius: ['round', 'soft', 'crisp'], icons: ['tint', 'solid', 'mono'],
            // ô mẫu dùng ĐÚNG độ bo áp dụng cho app (glass.css html[data-radius]): thẻ / nút
            radiusPx: { round: [26, 9999], soft: [16, 12], crisp: [9, 5] },
            appIcon: ['default', 'violet', 'pink', 'emerald', 'amber', 'graphite'],
          };
        },
        appIconSrc(v = this.ui.appIcon) { return v && v !== 'default' ? `/assets/icon-${v}.png` : '/assets/icon.png?v=2'; },
        applyUi() {
          const h = document.documentElement, u = this.ui;
          h.dataset.accent = u.accent || 'sky';
          if (u.text && u.text !== 'm') h.dataset.text = u.text; else delete h.dataset.text;
          if (u.radius && u.radius !== 'soft') h.dataset.radius = u.radius; else delete h.dataset.radius;
          const src = this.appIconSrc();
          document.querySelectorAll('link[rel="icon"], link[rel="apple-touch-icon"]').forEach(l => { l.href = src; });
          const m = document.querySelector('link[rel="manifest"]');
          if (m) m.href = u.appIcon && u.appIcon !== 'default' ? `/manifest.json?icon=${u.appIcon}` : '/manifest.json';
        },
        setUi(k, v) { this.ui = { ...this.ui, [k]: v }; this.applyUi(); },
        uiChanges() { return this.uiBase ? Object.keys(this.ui).filter(k => this.ui[k] !== this.uiBase[k]).length : 0; },
        uiSummary() {
          return [this.t('acc_' + this.ui.accent), this.t('txt_' + this.ui.text), this.t('rad_' + this.ui.radius)].join(' · ');
        },
        // Icon trên trang Cài đặt theo kiểu đã chọn: màu nhạt (mặc định) / nền đặc màu chủ đạo / đơn sắc
        iconCls(color) {
          if (this.ui.icons === 'solid') return 'bg-sky-500 border-sky-400/40 text-white';
          if (this.ui.icons === 'mono') return 'bg-white/[0.06] border-[var(--glass-border)] text-[var(--text-secondary)]';
          return color;
        },

        setTheme(mode) {
          this.theme = mode; localStorage.setItem('amp_theme', mode);
          const isLight = mode === 'light';
          document.documentElement.classList.toggle('light', isLight);
          document.documentElement.classList.toggle('dark', !isLight);
          document.getElementById('meta-theme-color').setAttribute('content', isLight ? '#e5eef9' : '#090f1d');
        },

        showToast(msg) {
          this.toast.message = msg; this.toast.show = true;
          clearTimeout(this._toastTimer);
          this._toastTimer = setTimeout(() => { this.toast.show = false; }, 2800);
        },

        countForTab(tabId) { return tabId === 'all' ? this.summary.total : (this.summary[tabId] || 0); },

        get filteredApps() {
          const q = this.search.trim().toLowerCase();
          const list = this.apps.filter(a => {
            if (this.filter === 'updates' && !a.has_update) return false;
            if (this.filter === 'running' && a.status !== 'running') return false;
            if (this.filter === 'stopped' && a.status === 'running') return false;
            if (this.filter === 'casaos' && a.source !== 'casaos') return false;
            if (this.filter === 'docker' && a.source !== 'docker') return false;
            if (!q) return true;
            return a.title.toLowerCase().includes(q) || a.name.toLowerCase().includes(q) || a.image.toLowerCase().includes(q);
          });
          const byName = (x, y) => x.title.localeCompare(y.title, undefined, { sensitivity: 'base', numeric: true });
          const run = a => (a.status === 'running' ? 0 : 1);
          switch (this.sortMode) {
            case 'name_asc': return list.sort(byName);
            case 'name_desc': return list.sort((x, y) => byName(y, x));
            case 'running': return list.sort((x, y) => run(x) - run(y) || byName(x, y));
            case 'stopped': return list.sort((x, y) => run(y) - run(x) || byName(x, y));
            default: return list; // 'smart': thứ tự từ server (có cập nhật -> đang chạy -> CasaOS -> tên)
          }
        },

        setSort(mode) {
          this.sortMode = mode;
          this.sortMenuOpen = false;
          try { localStorage.setItem('amp_sort', mode); } catch (_) {}
        },

        buildWebUrl(app) {
          // Chỉ cho http/https và đường dẫn tương đối an toàn (chặn "javascript:" từ manifest lạ)
          const scheme = String(app.scheme || 'http').toLowerCase() === 'https' ? 'https' : 'http';
          const raw = String(app.index || '').replace(/[\s\u0000-\u001f]/g, '');
          const idx = raw.startsWith('/') && !raw.startsWith('//') ? raw : `/${raw.replace(/^\/+/, '')}`;
          const port = String(app.port_map || '').replace(/[^0-9]/g, '');
          return `${scheme}://${window.location.hostname}${port ? ':' + port : ''}${idx}`;
        },

        async loadApps() {
          this.loading = true;
          try {
            const res = await fetch('/api/apps');
            if (res.status === 401) { window.location.href = '/login'; return; }
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed to load apps');
            // Trang đang mở là của bản cũ (Safari giữ tab) -> tải lại 1 lần để có giao diện khớp với AppManager mới
            const pageBuild = document.querySelector('meta[name="amp-build"]')?.content || '';
            if (data.build && pageBuild && data.build !== pageBuild) {
              let tried = '';
              try { tried = sessionStorage.getItem('amp_reload_for') || ''; } catch (e) {}
              if (tried !== data.build) {
                try { sessionStorage.setItem('amp_reload_for', data.build); } catch (e) {}
                window.location.reload(); return;
              }
            }
            this.envMode = data.environment;
            this.summary = data.summary;
            this.updateAllExcluded = data.update_all_excluded || [];
            if (data.auto_update) this.autoCfg = data.auto_update;
            this.apps = data.apps;
            this._syncAppBadge();
            this.lastChecked = data.last_checked || '';
            this.checkingUpdates = !!data.checking_updates;
            if (this.remote.id === '*' && this.remote.data) this._mergeLocal();
          } catch (err) { this.error = err.message; }
          finally { this.loading = false; }
        },

        // Số trên biểu tượng app ở màn hình chính (PWA, như App Store) = số app có bản cập nhật; 0 thì xoá số.
        _syncAppBadge() {
          try {
            if (!navigator.setAppBadge) return;
            const n = (this.apps || []).filter(a => a.has_update && !a.is_skipped).length;
            (n ? navigator.setAppBadge(n) : navigator.clearAppBadge()).catch(() => {});
          } catch (e) {}
        },

        async checkUpdates(silent = false) {
          this.checkingUpdates = true;
          if (!silent) {
            this.bannerDismissKey = '';
            localStorage.removeItem('amp_banner_dismissed');
          }
          try {
            const res = await fetch('/api/updates/check', { method: 'POST' });
            const body = await res.clone().json().catch(() => ({}));
            if (body.already_running) {
              if (!silent) this.showToast(this.lang === 'vi' ? 'Đang kiểm tra cập nhật, vui lòng đợi…' : 'An update check is already running…');
              await new Promise(r => setTimeout(r, 4000));
            }
            await this.loadApps();
            if (!silent && res.ok && !body.already_running) {
              const found = this.summary.updates;
              this.showToast(found > 0
                ? `${found} ${this.t('updatesAvailable')}`
                : (this.lang === 'vi' ? 'Tất cả ứng dụng đều đang ở bản mới nhất ✓' : 'All apps are up to date ✓'));
            }
          } catch (err) { if (!silent) this.error = err.message; }
          finally { this.checkingUpdates = false; }
        },

        openActionSheet(app) { this.actionSheet.app = app; this.actionSheet.open = true; },
        closeActionSheet() { this.actionSheet.open = false; },

        async openUpdateModal(app) {
          this.updateModal.open = true; this.updateModal.loading = true;
          this.updateModal.updating = false; this.updateModal.showRepoInput = false;
          this.updateModal.updateLogs = ''; this.updateModal.app = app; this.updateModal.preview = null;
          await this._fetchAppDetails(app.name, false);
        },

        // Mở/đóng nhật ký đầy đủ của một lần cập nhật trong tab Lịch sử
        async toggleHistoryLog(h) {
          if (this.historyLog.id === h.id) { this.historyLog = { id: null, text: '', loading: false }; return; }
          this.historyLog = { id: h.id, text: '', loading: true };
          try {
            const res = await fetch(`/api/history/${h.id}/log`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            if (this.historyLog.id === h.id) this.historyLog.text = data.log || this.t('noUpdateLog');
          } catch (err) {
            if (this.historyLog.id === h.id) this.historyLog.text = err.message;
          } finally {
            if (this.historyLog.id === h.id) this.historyLog.loading = false;
          }
        },

        // Markdown -> HTML an toàn. Thiếu thư viện (CDN/vendor hỏng) thì vẫn hiện chữ thô thay vì báo lỗi.
        _renderMarkdown(md) {
          if (window.marked && window.DOMPurify) {
            return window.DOMPurify.sanitize(window.marked.parse(md));
          }
          const esc = String(md).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
          return `<pre style="white-space:pre-wrap">${esc}</pre>`;
        },

        // Loại bỏ phần "SHA256 Checksums" (danh sách hash dài) khỏi release notes để hiện nội dung thay đổi thật
        _cleanChangelog(md) {
          const lines = String(md || '').split(/\r?\n/);
          const out = [];
          let skipping = false;
          const isHash = (l) => /[a-f0-9]{40,}/i.test(l);
          for (const line of lines) {
            const t = line.trim();
            if (/^[#>*_\s-]*(sha-?\d*\s*)?(sha-?256|sha-?512|md5)?\s*(checksums?|hashes|digests?)[\s:*_]*$/i.test(t) || /^[#>*_\s-]*sha-?(256|512)(\s*(sums?|checksums?|hashes))?[\s:*_]*$/i.test(t)) {
              skipping = true; continue;
            }
            if (skipping) {
              if (t === '' || t.startsWith('```') || t.startsWith('|') || isHash(t)) continue;
              skipping = false;
            }
            // Chỉ bỏ dòng CHỈ gồm mã hash (+ tên file); ghi chú có link commit vẫn giữ nguyên
            if (/^[\s`*>|-]*(?:[\w./+@-]+\s*[:=]?\s*)?`?(?:sha(?:256|512):)?[a-f0-9]{40,}`?(?:\s+\*?[\w./+@-]+)?[\s`|]*$/i.test(t)) continue;
            out.push(line);
          }
          return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
        },

        async _fetchAppDetails(name, refresh) {
          this.updateModal.loading = true;
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(name)}/details?refresh=${refresh ? 'true' : 'false'}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.updateModal.app = data.app;
            this.updateModal.releaseTag = data.release_tag || '';
            this.updateModal.releaseUrl = data.release_url || '';
            this.updateModal.changelogError = data.changelog_error || '';
            this.updateModal.autoUpdate = !!data.pref?.auto_update;
            this.updateModal.policy = JSON.parse(JSON.stringify(data.app?.policy || { level: 'all', min_age_days: 0, days: [], time: '' }));
            this.updateModal.customRepo = data.pref?.custom_repo || data.app?.source_url || '';
            const cleaned = data.changelog ? this._cleanChangelog(data.changelog) : '';
            if (cleaned) {
              this.updateModal.changelogHtml = this._renderMarkdown(cleaned);
            } else if (data.changelog) {
              const msg = this.lang === 'vi'
                ? 'Bản phát hành này chỉ có mã checksum, không có ghi chú thay đổi. Xem chi tiết trên GitHub ↗'
                : 'This release only lists checksums and has no release notes. See GitHub ↗';
              this.updateModal.changelogHtml = `<p>${msg}</p>`;
            } else {
              this.updateModal.changelogHtml = '';
            }
            if (this.updateModal.changelogHtml) this.updateModal.showRepoInput = false;
          } catch (err) { this.showToast(err.message); }
          finally { this.updateModal.loading = false; }
        },

        async refreshSingleApp() {
          if (!this.updateModal.app || this.updateModal.checking) return;
          this.updateModal.checking = true;
          try {
            await this._fetchAppDetails(this.updateModal.app.name, true);
            await this.loadApps();
            const a = this.updateModal.app;
            this.showToast(a?.has_update ? this.t('checkOneNew').replace('{v}', a.remote_version || '') : this.t('checkOneLatest'));
          } finally { this.updateModal.checking = false; }
        },

        // Kiểm tra bản mới cho riêng một app (menu ⋯)
        async checkOneApp(app) {
          if (this.checkingOne[app.name]) return;
          this.checkingOne = { ...this.checkingOne, [app.name]: true };
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(app.name)}/check`, {});
            if (!res.ok) throw new Error(data.detail || 'Failed');
            await this.loadApps();
            if (data.error && !data.has_update) this.showToast(`${app.title}: ${data.error}`);
            else this.showToast(`${app.title}: ` + (data.has_update ? this.t('checkOneNew').replace('{v}', data.app?.remote_version || '') : this.t('checkOneLatest')));
          } catch (err) { this.showToast(err.message); }
          finally { const c = { ...this.checkingOne }; delete c[app.name]; this.checkingOne = c; }
        },

        async saveAppPref() {
          if (!this.updateModal.app) return;
          await fetch(`/api/apps/${encodeURIComponent(this.updateModal.app.name)}/prefs`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_update: this.updateModal.autoUpdate })
          });
          this.showToast(this.lang === 'vi' ? 'Đã lưu Auto-Update' : 'Auto-Update saved');
          await this.loadApps();
        },

        // Quy tắc tự cập nhật (0.20)
        togglePolicyDay(d) {
          const p = this.updateModal.policy;
          let days = (p.days || []).length ? [...p.days] : [0, 1, 2, 3, 4, 5, 6];
          days = days.includes(d) ? days.filter(x => x !== d) : [...days, d].sort();
          if (!days.length) return;  // ít nhất 1 ngày
          p.days = days.length === 7 ? [] : days;
          this.saveAppPolicy();
        },

        async saveAppPolicy() {
          const m = this.updateModal;
          if (!m.app || !m.policy) return;
          m.policySaving = true;
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(m.app.name)}/prefs`, { policy: m.policy });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            await this.loadApps();
            const fresh = this.apps.find(a => a.name === m.app.name);
            if (fresh) m.app = { ...m.app, auto_hold: fresh.auto_hold, policy: fresh.policy };
          } catch (err) { this.showToast(err.message); }
          finally { m.policySaving = false; }
        },

        holdText(h) {
          if (!h) return '';
          if (h.code === 'wait') return this.t('holdWait').replace('{n}', h.days_left);
          if (h.code === 'level') return this.t('holdLevel').replace('{to}', h.to || '?').replace('{kind}', this.t('chg_' + h.change));
          if (h.code === 'unknown_version') return this.t('holdUnknown');
          return '';
        },

        async toggleSkipUpdate() {
          const app = this.updateModal.app;
          if (!app) return;
          const nextToken = app.is_skipped ? '' : (app.skip_token || '');
          await fetch(`/api/apps/${encodeURIComponent(app.name)}/prefs`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skipped_digest: nextToken })
          });
          this.showToast(nextToken
            ? (this.lang === 'vi' ? 'Đã bỏ qua bản cập nhật này' : 'Version skipped')
            : (this.lang === 'vi' ? 'Đã hiện lại thông báo cập nhật' : 'Version unskipped'));
          await this._fetchAppDetails(app.name, false);
          await this.loadApps();
        },

        async saveCustomRepo() {
          if (!this.updateModal.app) return;
          const repo = (this.updateModal.customRepo || '').trim();
          const name = this.updateModal.app.name;
          this.updateModal.loading = true;
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(name)}/prefs`, { custom_repo: repo });
            if (!res.ok) throw new Error(data.detail || 'Failed to save repository');
            await this._fetchAppDetails(name, false);
            await this.loadApps();
            this.showToast(this.lang === 'vi' ? 'Đã lưu nguồn GitHub' : 'Repository saved');
          } catch (err) {
            this.showToast(err.message);
          } finally {
            this.updateModal.loading = false;
          }
        },

        closeUpdateModal() {
          if (this.updateModal.updating) {
            this.showToast(this.t('updatingWait'));
            return;
          }
          this.updateModal.open = false;
        },

        // ---------------- Helpers ----------------
        wsUrl(path) {
          const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
          return `${proto}//${window.location.host}${path}`;
        },

        async _postJson(url, body) {
          const res = await fetch(url, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
          });
          let data = {};
          try { data = await res.json(); } catch (_) {}
          if (res.status === 401) { window.location.href = '/login'; }
          return { res, data };
        },

        _scrollRef(name) {
          this.$nextTick(() => { const b = this.$refs[name]; if (b) b.scrollTop = b.scrollHeight; });
        },

        // Sau self-update: chờ container khởi động lại rồi tải lại trang
        async _waitAndReload() {
          this.showToast(this.lang === 'vi' ? 'AppManager Pro đang khởi động lại...' : 'AppManager Pro is restarting...');
          await new Promise(r => setTimeout(r, 8000));
          for (let i = 0; i < 40; i++) {
            try {
              const res = await fetch('/manifest.json', { cache: 'no-store' });
              if (res.ok) { window.location.reload(); return; }
            } catch (_) {}
            await new Promise(r => setTimeout(r, 2000));
          }
          window.location.reload();
        },

        // ---------------- Start / Stop / Restart ----------------
        async runAction(app, action) {
          this.busyId = app.id;
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(app.id)}/${action}`);
            if (!res.ok) throw new Error(data.detail || 'Action failed');
            const label = { start: this.t('start'), stop: this.t('stop'), restart: this.t('restart'), kill: this.t('kill') }[action] || action;
            this.showToast(`${app.title}: ${label} ✓`);
            await this.loadApps();
          } catch (err) {
            this.showToast(err.message);
          } finally {
            this.busyId = null;
          }
        },

        // ---------------- Logs: trực tiếp / theo khoảng thời gian, tìm, lọc mức, tải về (0.21) ----------------
        openLogs(app, server = null) {
          this._closeLogWs();
          this.logModal = { open: true, title: app.title, containerName: app.name, lines: '', ws: null,
                            mode: server ? '1h' : 'live', q: '', level: '', server, loading: false, info: null, error: '' };
          if (server) this.fetchLogs(); else this._openLogWs();
        },

        _openLogWs() {
          const m = this.logModal;
          const ws = new WebSocket(this.wsUrl(`/ws/logs/${encodeURIComponent(m.containerName)}`));
          m.ws = ws; m.lines = ''; m.info = null; m.error = '';
          ws.onmessage = (event) => {
            if (this.logModal.ws !== ws) return;
            let next = this.logModal.lines + event.data;
            if (next.length > 200000) next = next.slice(-150000);
            this.logModal.lines = next;
            const box = this.$refs.logBox;
            const nearBottom = !box || (box.scrollHeight - box.scrollTop - box.clientHeight < 80);
            if (nearBottom) this._scrollRef('logBox');
          };
          ws.onclose = (event) => {
            if (this.logModal.ws !== ws) return;
            if (event.code === 4401) { window.location.href = '/login'; }
          };
        },

        _closeLogWs() {
          if (this.logModal.ws) { try { this.logModal.ws.close(); } catch (_) {} }
          this.logModal.ws = null;
        },

        _logBase() {
          const m = this.logModal, n = encodeURIComponent(m.containerName);
          return m.server ? `/api/servers/${m.server.id}/apps/${n}/logs` : `/api/apps/${n}/logs`;
        },

        _logParams(range) {
          const m = this.logModal;
          return new URLSearchParams({ range, q: m.q.trim(), level: m.level }).toString();
        },

        setLogMode(mode) {
          const m = this.logModal;
          m.mode = mode;
          if (mode === 'live') { this._openLogWs(); return; }
          this._closeLogWs();
          this.fetchLogs();
        },

        setLogLevel(lv) {
          this.logModal.level = lv;
          if (this.logModal.mode !== 'live') this.fetchLogs();
        },

        onLogQuery() {
          clearTimeout(this._logQT);
          if (this.logModal.mode !== 'live') this._logQT = setTimeout(() => this.fetchLogs(), 450);
        },

        async fetchLogs() {
          const m = this.logModal, key = `${m.containerName}|${m.mode}|${m.q}|${m.level}`;
          m.loading = true; m.error = '';
          try {
            const res = await fetch(`${this._logBase()}?${this._logParams(m.mode)}&limit=3000`);
            const data = await res.json().catch(() => ({}));
            if (key !== `${m.containerName}|${m.mode}|${m.q}|${m.level}`) return;  // đã đổi bộ lọc trong lúc chờ
            if (!res.ok) throw new Error(data.detail || 'Failed');
            m.lines = data.text || ''; m.info = data;
            this._scrollRef('logBox');
          } catch (err) { m.error = err.message; m.lines = ''; m.info = null; }
          finally { m.loading = false; }
        },

        // Mức của một dòng log (giống app/core/logs.py) — dùng để lọc khi xem trực tiếp
        _logLevelOf(text) {
          if (/\b(error|err|fatal|fail(?:ed|ure)?|crit(?:ical)?|panic|emerg|alert|exception|traceback|segfault)\b|\[(?:e|err|error|fatal|crit)\]|\blevel=(?:error|fatal|crit)/i.test(text)) return 'error';
          if (/\b(warn(?:ing)?|deprecated)\b|\[(?:w|warn|warning)\]|\blevel=warn/i.test(text)) return 'warn';
          return '';
        },

        // Nội dung hiển thị: xem trực tiếp thì lọc ngay trên trình duyệt; theo khoảng thời gian thì máy chủ đã lọc
        logView() { return this._logShortTimes(this._logFiltered()); },

        // Log có mã màu ANSI (Portainer, Go, Node…) -> HTML có màu. Mọi chữ được escape trước; chỉ thêm <span style> của mình.
        logHtml() {
          const text = this.logView();
          return text ? this._ansiToHtml(text) : '';
        },

        _ansiToHtml(text) {
          const esc = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          const base = ['#4b5563', '#f87171', '#4ade80', '#facc15', '#60a5fa', '#e879f9', '#22d3ee', '#e5e7eb'];
          const bright = ['#9ca3af', '#fca5a5', '#86efac', '#fde047', '#93c5fd', '#f0abfc', '#67e8f9', '#ffffff'];
          const c256 = n => {
            if (n < 8) return base[n];
            if (n < 16) return bright[n - 8];
            if (n >= 232) { const v = 8 + (n - 232) * 10; return `rgb(${v},${v},${v})`; }
            n -= 16; const k = [0, 95, 135, 175, 215, 255];
            return `rgb(${k[Math.floor(n / 36)]},${k[Math.floor(n / 6) % 6]},${k[n % 6]})`;
          };
          let st = {}, out = '';
          // Bỏ mã điều khiển không phải màu (con trỏ, xoá dòng, tiêu đề OSC); giữ lại mã màu SGR "ESC[...m"
          const clean = text.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '').replace(/\x1b\[[0-9;?]*[ -\/]*[@-ln-~]/g, '').replace(/\x1b[@-Z\\-_]/g, '');
          const parts = clean.split(/\x1b\[([0-9;]*)m/);
          for (let i = 0; i < parts.length; i++) {
            if (i % 2) {
              const codes = parts[i] === '' ? [0] : parts[i].split(';').map(Number);
              for (let j = 0; j < codes.length; j++) {
                const c = codes[j];
                if (c === 0) st = {};
                else if (c === 1) st.b = 1; else if (c === 2) st.d = 1; else if (c === 3) st.i = 1; else if (c === 4) st.u = 1;
                else if (c === 22) { delete st.b; delete st.d; } else if (c === 23) delete st.i; else if (c === 24) delete st.u;
                else if (c >= 30 && c <= 37) st.fg = base[c - 30]; else if (c >= 90 && c <= 97) st.fg = bright[c - 90];
                else if (c === 39) delete st.fg;
                else if (c === 38 && codes[j + 1] === 5) { st.fg = c256(codes[j + 2] || 0); j += 2; }
                else if (c === 38 && codes[j + 1] === 2) { st.fg = `rgb(${codes[j + 2] || 0},${codes[j + 3] || 0},${codes[j + 4] || 0})`; j += 4; }
                else if (c === 48) j += codes[j + 1] === 5 ? 2 : codes[j + 1] === 2 ? 4 : 0;  // nền: bỏ qua (nền tối của cửa sổ log)
              }
              continue;
            }
            if (!parts[i]) continue;
            const css = [st.fg && `color:${st.fg}`, st.b && 'font-weight:700', st.d && 'opacity:.6', st.i && 'font-style:italic', st.u && 'text-decoration:underline'].filter(Boolean).join(';');
            out += css ? `<span style="${css}">${esc(parts[i])}</span>` : esc(parts[i]);
          }
          return out;
        },

        // Thời gian Docker (2026-11-26T22:33:48.414222022Z) -> giờ máy ngắn gọn "26/11 22:33:48" cho màn hình điện thoại
        _logShortTimes(text) {
          if (!text) return text;
          const pad = n => String(n).padStart(2, '0');
          return text.replace(/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z /gm, (all, base) => {
            const d = new Date(base + 'Z');
            return isNaN(d) ? all : `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} `;
          });
        },

        _logFiltered() {
          const m = this.logModal;
          if (m.mode !== 'live' || (!m.q.trim() && !m.level)) return m.lines;
          const words = m.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
          const inc = words.filter(w => !(w.startsWith('-') && w.length > 1)), exc = words.filter(w => w.startsWith('-') && w.length > 1).map(w => w.slice(1));
          let prev = '';
          return m.lines.split('\n').filter(line => {
            const text = line.replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, '').replace(/^\d{4}-\d\d-\d\dT[\d:.]+Z?\s?/, '');
            let lv = this._logLevelOf(text);
            if (!lv && /^[ \t]/.test(text) && prev) lv = prev;
            prev = lv;
            if (m.level === 'error' && lv !== 'error') return false;
            if (m.level === 'warn' && !lv) return false;
            const low = text.toLowerCase();
            return inc.every(w => low.includes(w)) && !exc.some(w => low.includes(w));
          }).join('\n');
        },

        logInfoText() {
          const m = this.logModal, i = m.info;
          if (m.mode === 'live') {
            if (!m.q.trim() && !m.level) return this.t('logLiveHint');
            const v = this._logFiltered();
            return this.t('logMatched').replace('{n}', v ? v.split('\n').filter(Boolean).length : 0);
          }
          if (!i) return '';
          let s = this.t('logMatched').replace('{n}', i.matched) + ' · ' + this.t('logScanned').replace('{n}', i.scanned);
          if (i.truncated) s += ' · ' + this.t('logTruncated');
          if (i.capped) s += ' · ' + this.t('logCapped');
          return s;
        },

        downloadLogs() {
          const m = this.logModal, range = m.mode === 'live' ? '24h' : m.mode;
          const a = document.createElement('a');
          a.href = `${this._logBase()}/download?${this._logParams(range)}`;
          a.rel = 'noopener'; document.body.appendChild(a); a.click(); a.remove();
          this.showToast(this.t('logDownloading').replace('{r}', this.t('logRange_' + range)));
        },

        closeLogs() {
          this._closeLogWs();
          clearTimeout(this._logQT);
          this.logModal.open = false;
        },

        // ---------------- Gợi ý tag cho ô Image & Tag ----------------
        _imageRepo(ref) {
          const r = String(ref || '').split('@')[0];
          const last = r.lastIndexOf('/'), colon = r.lastIndexOf(':');
          return colon > last ? r.slice(0, colon) : r;
        },

        async toggleTagMenu() {
          const m = this.tagMenu;
          if (m.open) { m.open = false; return; }
          const img = (this.editModal.ui?.service?.image || '').trim();
          if (!img) return;
          m.open = true;
          if (m.image === img && m.items.length) return;
          m.loading = true; m.error = ''; m.items = [];
          try {
            const res = await fetch(`/api/image-tags?image=${encodeURIComponent(img)}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            m.items = data.tags || []; m.image = img;
            if (!m.items.length) m.error = this.t('noTagsFound');
          } catch (err) { m.error = err.message; }
          finally { m.loading = false; }
        },

        pickTag(tag) {
          const s = this.editModal.ui.service;
          s.image = `${this._imageRepo(s.image)}:${tag}`;
          this.tagMenu.open = false;
          this.tagMenu.image = s.image;
          this.tagMenu.items = this.tagMenu.items.map(o => ({ ...o, current: o.tag === tag }));
        },

        // ---------------- Kênh phát hành (latest / beta ...) ----------------
        channelBadge(app) {
          const chs = app.channels || [];
          if (chs.length < 2) return null;
          const cur = chs.find(c => c.current || c.tag === app.image_tag);
          if (cur && cur.kind === 'pre') return { on: true, label: cur.channel, title: this.t('onPreChannel') };
          const pre = chs.filter(c => c.kind === 'pre');
          if (!pre.length) return null;
          // Có kênh thử nghiệm: viền nét đứt + tên kênh (BETA / DEV / RC...), nhiều kênh thì ghi "+1"
          return { on: false, label: pre[0].channel + (pre.length > 1 ? ` +${pre.length - 1}` : ''),
                   title: `${this.t('preChannelAvailable')}: ${pre.map(c => c.channel + (c.version ? ' ' + c.version : '')).join(', ')}` };
        },

        // Phiên bản hiển thị của một kênh: số phiên bản, hoặc ngày build nếu tag không ghi phiên bản (vd beszel:dev)
        channelVersion(ch) {
          if (!ch) return '';
          if (ch.version) return ch.version;
          if (ch.updated) {
            const d = new Date(ch.updated.replace(' ', 'T') + (ch.updated.endsWith('Z') ? '' : 'Z'));
            if (!isNaN(d)) return `build ${d.toLocaleDateString(this.lang === 'vi' ? 'vi-VN' : 'en-US', { day: '2-digit', month: '2-digit' })}`;
          }
          return ch.tag;
        },

        // Kênh của changelog đang hiển thị: kênh đang xem trước, hoặc kênh app đang chạy (nếu app có nhiều kênh)
        changelogChannel() {
          const m = this.updateModal;
          if (m.preview) return m.preview;
          const chs = m.app?.channels || [];
          return chs.length > 1 ? (chs.find(c => c.current || c.tag === m.app.image_tag) || null) : null;
        },

        confirmChannelSwitch(ch) {
          const app = this.updateModal.app;
          if (!app || this.updateModal.updating) return;
          if (ch.current || ch.tag === app.image_tag) { if (this.updateModal.preview) this.cancelChannelPreview(); return; }
          if (this.updateModal.preview?.tag === ch.tag) return;
          const toPre = ch.kind === 'pre';
          const curCh = (app.channels || []).find(c => c.current || c.tag === app.image_tag);
          const variantMsg = (ch.variant || curCh?.variant) ? this.t('switchVariantMsg') + ' ' : '';
          this.askConfirm({
            tone: toPre ? 'danger' : 'update',
            title: `${this.t('switchChannelTitle')} ${(ch.label || ch.channel).toUpperCase()}${ch.version ? ' (' + ch.version + ')' : ''}?`,
            message: `${app.image_tag} → ${ch.tag}. ${variantMsg}${toPre ? this.t('switchToPreMsg') : this.t('switchToStableMsg')} ${this.t('switchChannelMsg')}`,
            confirmLabel: this.t('switchChannel'), onConfirm: () => this.previewChannel(ch)
          });
        },

        // Chọn kênh: chỉ tải changelog của kênh đó; cập nhật thật khi người dùng bấm nút cập nhật
        async previewChannel(ch) {
          const m = this.updateModal;
          m.preview = ch; m.loading = true;
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(m.app.name)}/channel-preview?tag=${encodeURIComponent(ch.tag)}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            if (m.preview?.tag !== ch.tag) return;
            m.releaseTag = data.release_tag || ch.version || ch.tag;
            m.releaseUrl = data.release_url || m.releaseUrl;
            m.changelogError = data.changelog ? '' : (data.error || '');
            const cleaned = data.changelog ? this._cleanChangelog(data.changelog) : '';
            m.changelogHtml = cleaned ? this._renderMarkdown(cleaned) : '';
          } catch (err) { this.showToast(err.message); }
          finally { m.loading = false; }
        },

        // ---------------- Chọn phiên bản (lên / xuống bất kỳ phiên bản gần đây) ----------------
        _verNums(v) {
          const m = String(v || '').match(/(\d+(?:\.\d+)*)/);
          return m ? m[1].split('.').map(Number) : null;
        },
        // <0: a cũ hơn b, >0: mới hơn, 0: bằng; null nếu không so được
        compareVersions(a, b) {
          const x = this._verNums(a), y = this._verNums(b);
          if (!x || !y) return null;
          for (let i = 0; i < Math.max(x.length, y.length); i++) {
            const d = (x[i] || 0) - (y[i] || 0);
            if (d) return d;
          }
          return 0;
        },
        isOlderVersion(item) {
          if (!item || item.kind === 'channel' || item.current) return false;
          const c = this.compareVersions(item.version || item.tag, this.updateModal.app?.version);
          return c !== null && c < 0;
        },

        async openVersionPicker() {
          const app = this.updateModal.app;
          if (!app || this.updateModal.updating) return;
          const p = this.versionPicker;
          p.open = true; p.loading = true; p.error = ''; p.items = []; p.selected = '';
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(app.name)}/versions`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            p.items = data.tags || [];
            const firstOther = p.items.find(x => !x.current && x.kind === 'version');
            p.selected = this.updateModal.preview?.tag || firstOther?.tag || '';
          } catch (err) { p.error = err.message; }
          finally { p.loading = false; }
        },

        // Từ menu ⋯: mở cửa sổ cập nhật rồi mở luôn bảng chọn phiên bản
        async openVersionPickerFor(app) {
          await this.openUpdateModal(app);
          this.openVersionPicker();
        },

        pickVersion() {
          const p = this.versionPicker;
          const item = p.items.find(x => x.tag === p.selected);
          p.open = false;
          if (!item) return;
          if (item.current) { if (this.updateModal.preview) this.cancelChannelPreview(); return; }
          this.previewChannel({ tag: item.tag, channel: item.version || item.tag, kind: 'version',
                                version: item.version || '', older: this.isOlderVersion(item) });
        },

        async cancelChannelPreview() {
          this.updateModal.preview = null;
          await this._fetchAppDetails(this.updateModal.app.name, false);
        },

        // ---------------- Update 1 app (WebSocket Terminal) ----------------
        startAppUpdate(forceTag = '') {
          const app = this.updateModal.app;
          if (!app || this.updateModal.updating) return;
          this.updateModal.updating = true;
          this.updateModal.updateLogs = '';
          let selfUpdate = false;

          const q = forceTag ? `?tag=${encodeURIComponent(forceTag)}` : '';
          const ws = new WebSocket(this.wsUrl(`/ws/update/${encodeURIComponent(app.name)}${q}`));
          this.updateModal.ws = ws;

          ws.onmessage = (event) => {
            let text = event.data;
            if (text.includes('__SELF_UPDATE_RELOAD__')) {
              selfUpdate = true;
              text = text.replace('__SELF_UPDATE_RELOAD__\n', '').replace('__SELF_UPDATE_RELOAD__', '');
            }
            this.updateModal.updateLogs += text;
            this._scrollRef('updateLogBox');
          };

          ws.onclose = async (event) => {
            this.updateModal.updating = false;
            this.updateModal.ws = null;
            if (event.code === 4401) { window.location.href = '/login'; return; }
            if (selfUpdate) { this._waitAndReload(); return; }
            this.updateModal.preview = null;  // đã chuyển xong -> bỏ trạng thái "xem trước", không hiện lại nút chuyển
            await this.loadApps();
            if (this.updateModal.open && this.updateModal.app) {
              // phần đầu cửa sổ (image / phiên bản) lấy ngay số liệu mới, không chờ tải lại changelog
              const fresh = this.apps.find(a => a.name === this.updateModal.app.name);
              if (fresh) this.updateModal.app = { ...this.updateModal.app, ...fresh };
              await this._fetchAppDetails(this.updateModal.app.name, false);
            }
          };

          ws.onerror = () => {
            this.updateModal.updateLogs += '\n[ERROR] WebSocket connection failed.\n';
          };
        },

        // ---------------- Update All (Batch) ----------------
        startBatchUpdate() {
          if (this.batchModal.running) return;
          this.batchModal = { open: true, running: true, items: [], doneCount: 0, succeeded: 0, failed: 0, logs: '', ws: null };
          let selfUpdate = false;

          const ws = new WebSocket(this.wsUrl('/ws/update-all'));
          this.batchModal.ws = ws;

          ws.onmessage = (event) => {
            let msg;
            try { msg = JSON.parse(event.data); } catch (_) { return; }
            const m = this.batchModal;

            if (msg.type === 'init') {
              m.items = (msg.apps || []).map(a => ({ ...a, status: 'pending' }));
            } else if (msg.type === 'app_start') {
              if (m.items[msg.index]) m.items[msg.index].status = 'running';
            } else if (msg.type === 'log') {
              let text = msg.text || '';
              if (text.includes('__SELF_UPDATE_RELOAD__')) {
                selfUpdate = true;
                text = text.replace('__SELF_UPDATE_RELOAD__\n', '').replace('__SELF_UPDATE_RELOAD__', '');
              }
              m.logs += text;
              this._scrollRef('batchLogBox');
            } else if (msg.type === 'app_done') {
              const item = m.items[msg.index];
              if (item) {
                item.status = msg.ok ? 'success' : 'failed';
                if (msg.to_version) item.to_version = msg.to_version;
              }
              m.doneCount += 1;
            } else if (msg.type === 'complete') {
              m.succeeded = msg.succeeded || 0;
              m.failed = msg.failed || 0;
              m.running = false;
              if (msg.self_update) selfUpdate = true;
            }
          };

          ws.onclose = async (event) => {
            this.batchModal.running = false;
            this.batchModal.ws = null;
            if (event.code === 4401) { window.location.href = '/login'; return; }
            if (selfUpdate) { this._waitAndReload(); return; }
            await this.loadApps();
          };
        },

        closeBatchModal() {
          if (this.batchModal.running) return;
          if (this.batchModal.ws) { try { this.batchModal.ws.close(); } catch (_) {} }
          this.batchModal.open = false;
        },

        // ---------------- Edit App (Visual UI <-> YAML) ----------------
        async openRunCommand(app) {
          const r = this.runCmd;
          Object.assign(r, { open: true, app, text: '', loading: true, error: '' });
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(app.name)}/run-command`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            r.text = data.command;
          } catch (err) { r.error = err.message; }
          finally { r.loading = false; }
        },

        // ---------------- App không dùng được compose: lý do + khắc phục / chuyển sang compose ----------------
        async openComposeHint(app) {
          const h = this.composeHint;
          Object.assign(h, { open: true, app, loading: false, busy: false, preview: null, folder: '', yaml: '', log: '', error: '', done: false });
          if (app.compose_issue !== 'not_compose') return;
          h.loading = true;
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(app.name)}/compose-convert`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            h.preview = data; h.folder = data.folder; h.yaml = data.yaml;
          } catch (err) { h.error = err.message; }
          finally { h.loading = false; }
        },

        composeHintSnippet() {
          const m = this.composeHint.app?.compose_mount || '';
          return m ? `    volumes:\n      - ${m}:${m}` : '';
        },

        confirmConvertCompose() {
          const h = this.composeHint;
          this.askConfirm({
            tone: 'update', title: this.t('convertConfirmTitle'),
            message: `${h.app.title} → ${h.folder}/docker-compose.yml. ${this.t('convertConfirmMsg')}`,
            confirmLabel: this.t('convertToCompose'), onConfirm: () => this.runConvertCompose()
          });
        },

        async runConvertCompose() {
          const h = this.composeHint;
          h.busy = true; h.error = ''; h.log = this.t('converting') + '\n';
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(h.app.name)}/compose-convert`, { folder: h.folder, yaml: h.yaml });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            h.log = data.log || '';
            if (data.ok) { h.done = true; this.showToast(this.t('convertDone')); this.loadApps(); }
            else h.error = data.error || 'Failed';
          } catch (err) { h.error = err.message; }
          finally { h.busy = false; }
        },

        openDataSetupManual(path) {
          this.openDataSetup().then(() => {
            if (path) this.dataSetup.manualPath = path;
            this.dataSetup.step = 'manual';
          });
        },

        // ---------------- Thiết lập thư mục Data App (người dùng mới) ----------------
        async checkDataSetup() {
          try {
            const res = await fetch('/api/setup/data-status');
            if (!res.ok) return;
            const st = await res.json();
            this.dataSetup.status = st;
            if (st.prompt) this.openDataSetup(st);
          } catch (_) {}
        },

        async openDataSetup(st = null) {
          const d = this.dataSetup;
          Object.assign(d, { open: true, step: 'intro', error: '', candidates: [], selected: [], busy: false, elapsed: 0, source: '' });
          if (!st) {
            try { const res = await fetch('/api/setup/data-status'); if (res.ok) d.status = await res.json(); } catch (_) {}
          } else d.status = st;
          if (!d.manualPath) d.manualPath = (d.status?.mounted || []).length ? '' : '/DATA/AppData';
        },

        async dismissDataSetup() {
          this.dataSetup.open = false;
          this._scanPoll && clearTimeout(this._scanPoll);
          try { await this._postJson('/api/setup/data-dismiss', { dismissed: true }); } catch (_) {}
        },

        async checkManualPath() {
          const d = this.dataSetup;
          d.busy = true; d.error = '';
          try {
            const { res, data } = await this._postJson('/api/setup/data-check', { path: d.manualPath });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            d.candidates = [{ path: data.path, count: data.count, apps: data.apps || [], mounted: data.mounted, running: 0 }];
            d.selected = data.mounted ? [] : [data.path];
            d.source = 'manual'; d.step = 'results';
          } catch (err) { d.error = err.message; }
          finally { d.busy = false; }
        },

        async startDataScan() {
          const d = this.dataSetup;
          d.step = 'scan'; d.error = ''; d.elapsed = 0; d.busy = true;
          try {
            const { res, data } = await this._postJson('/api/setup/data-scan?mode=deep', {});
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this._pollDataScan();
          } catch (err) { d.error = err.message; d.busy = false; }
        },

        async _pollDataScan() {
          const d = this.dataSetup;
          if (!d.open || d.step !== 'scan') return;
          try {
            const res = await fetch('/api/setup/data-scan');
            const st = await res.json();
            d.elapsed = st.elapsed || 0;
            if (!st.running) {
              d.busy = false;
              if (st.error && !(st.candidates || []).length) {
                // Quét sâu lỗi -> vẫn dùng kết quả nhanh từ nhãn Docker
                const q = await this._postJson('/api/setup/data-scan?mode=quick', {});
                d.candidates = q.data.candidates || [];
                d.error = st.error;
              } else d.candidates = st.candidates || [];
              d.selected = d.candidates.filter(c => !c.mounted && (c.running || 0) > 0).map(c => c.path);
              d.source = 'scan'; d.step = 'results';
              return;
            }
          } catch (_) {}
          this._scanPoll = setTimeout(() => this._pollDataScan(), 2000);
        },

        toggleDataPath(c) {
          if (c.mounted) return;
          const sel = this.dataSetup.selected;
          const i = sel.indexOf(c.path);
          if (i >= 0) sel.splice(i, 1); else sel.push(c.path);
        },

        dataComposeSnippet() {
          return this.dataSetup.selected.map(p => `      - ${p}:${p}`).join('\n');
        },

        confirmApplyDataPaths() {
          const d = this.dataSetup;
          if (!d.selected.length) return;
          this.askConfirm({
            tone: 'update', title: this.t('dataApplyTitle'),
            message: `${d.selected.join(', ')} — ${this.t('dataApplyMsg')}`,
            confirmLabel: this.t('dataApplyBtn'), onConfirm: () => this.applyDataPaths()
          });
        },

        async applyDataPaths() {
          const d = this.dataSetup;
          d.busy = true; d.error = '';
          try {
            const { res, data } = await this._postJson('/api/setup/data-apply', { paths: d.selected });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            d.open = false;
            this._waitAndReload();
          } catch (err) { d.error = err.message; d.busy = false; }
        },

        // ---------------- Quản lý thư mục dữ liệu đã thêm (Cài đặt → Bộ nhớ) ----------------
        dataFolderSummary() {
          const st = this.dataSetup.status;
          const f = st?.folders || [];
          if (!f.length) return this.t('dataNoneMounted');
          let txt = this.t('dataFoldersCount').replace('{n}', f.length).replace('{a}', st.total_apps || 0);
          if (st.missing_count) txt += ' · ' + this.t('dataFoldersMissing').replace('{n}', st.missing_count);
          return txt;
        },

        async refreshDataStatus() {
          try { const res = await fetch('/api/setup/data-status'); if (res.ok) this.dataSetup.status = await res.json(); } catch (_) {}
        },

        async openDataFolders(mode = 'list') {
          Object.assign(this.dataFolders, { open: true, mode, folder: null, newPath: '', check: null, busy: true, error: '' });
          await this.refreshDataStatus();
          this.dataFolders.busy = false;
        },

        dataFolderEdit(f) {
          Object.assign(this.dataFolders, { mode: 'edit', folder: f, newPath: f.path, check: null, error: '' });
        },

        dataFolderRemove(f) {
          Object.assign(this.dataFolders, { mode: 'remove', folder: f, check: null, error: '' });
        },

        dataFolderAdd() {
          Object.assign(this.dataFolders, { mode: 'add', folder: null, newPath: '', check: null, error: '' });
        },

        async dataFolderCheck() {
          const d = this.dataFolders;
          d.busy = true; d.error = ''; d.check = null;
          try {
            const { res, data } = await this._postJson('/api/setup/data-check', { path: d.newPath });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            if (d.mode === 'edit' && data.path === d.folder.path) throw new Error(this.t('dataFolderSame'));
            if (d.mode === 'add' && data.mounted) throw new Error(this.t('dfAlreadyAdded'));
            d.check = data;
          } catch (err) { d.error = err.message; }
          finally { d.busy = false; }
        },

        // Các app nằm trong thư mục cũ mà thư mục mới không chứa -> AppManager không đọc được compose nữa
        dataFolderLostApps() {
          const d = this.dataFolders;
          if (!d.folder) return [];
          const kept = new Set(d.mode === 'edit' && d.check ? (d.check.covers_apps || []) : []);
          return (d.folder.apps || []).filter(n => !kept.has(n));
        },

        dataFolderPlan() {
          const d = this.dataFolders, f = d.folder;
          if (d.mode === 'add') {
            if (!d.check) return [];
            const n = (d.check.covers_apps || []).length;
            return [
              { tone: 'ok', text: this.t('dfPlanAdd').replace('{p}', d.check.path) },
              { tone: 'info', text: this.t('dfPlanFound').replace('{n}', d.check.count ?? 0) },
              ...(n ? [{ tone: 'ok', text: this.t('dfPlanGain').replace('{n}', n).replace('{apps}', d.check.covers_apps.slice(0, 8).join(', ') + (n > 8 ? '…' : '')) }] : []),
              { tone: 'info', text: this.t('dfPlanNoDelete') },
              { tone: 'warn', text: this.t('dfPlanRestart') },
            ];
          }
          if (!f) return [];
          const plan = [];
          if (d.mode === 'edit') {
            plan.push({ tone: 'ok', text: this.t('dfPlanAdd').replace('{p}', d.check?.path || d.newPath) });
            plan.push({ tone: 'info', text: this.t('dfPlanFound').replace('{n}', d.check?.count ?? 0) });
          }
          plan.push({ tone: 'danger', text: this.t('dfPlanRemove').replace('{p}', f.path) });
          const lost = this.dataFolderLostApps();
          if (lost.length) plan.push({ tone: 'warn', text: this.t('dfPlanLost').replace('{n}', lost.length).replace('{apps}', lost.slice(0, 8).join(', ') + (lost.length > 8 ? '…' : '')) });
          if (f.backup_root) plan.push({ tone: 'warn', text: this.t('dfPlanBackup') });
          plan.push({ tone: 'info', text: this.t('dfPlanNoDelete') });
          plan.push({ tone: 'warn', text: this.t('dfPlanRestart') });
          return plan;
        },

        confirmDataFolderChange() {
          const d = this.dataFolders;
          if (d.mode === 'add') {
            this.askConfirm({ tone: 'update', title: this.t('dfAddTitle'), message: d.check.path, confirmLabel: this.t('dfAddBtn'), onConfirm: () => this.applyDataFolderChange() });
            return;
          }
          const edit = d.mode === 'edit';
          this.askConfirm({
            tone: edit ? 'update' : 'danger',
            title: this.t(edit ? 'dfEditTitle' : 'dfRemoveTitle'),
            message: edit ? `${d.folder.path} → ${d.check.path}` : d.folder.path,
            confirmLabel: this.t(edit ? 'dfSaveBtn' : 'dfRemoveBtn'),
            onConfirm: () => this.applyDataFolderChange()
          });
        },

        async applyDataFolderChange() {
          const d = this.dataFolders;
          d.busy = true; d.error = '';
          const body = d.mode === 'add' ? { remove: [], add: [d.check.path] } : { remove: [d.folder.path], add: d.mode === 'edit' ? [d.check.path] : [] };
          try {
            const { res, data } = await this._postJson('/api/setup/data-update', body);
            if (!res.ok) throw new Error(data.detail || 'Failed');
            d.open = false;
            this._waitAndReload();
          } catch (err) { d.error = err.message; d.busy = false; }
        },

        // Biểu tượng xám (đã Bỏ qua): popup với cảnh báo ban đầu + Gộp / Huỷ
        async openDupPopup(app) {
          const p = this.dupPopup;
          Object.assign(p, { open: true, loading: true, busy: false, app, composePath: app.compose_path || '', files: [] });
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(app.name)}/compose`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            p.composePath = data.compose_path || p.composePath;
            p.files = [...(data.other_compose_files || []), ...(data.skipped_compose_files || [])];
            if (!p.files.length) { p.open = false; app.dup_compose = 0; this.loadApps(); }
          } catch (err) { p.open = false; this.showToast(err.message); }
          finally { p.loading = false; }
        },

        async mergeFromPopup() {
          const p = this.dupPopup;
          if (!p.app) return;
          p.busy = true;
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(p.app.name)}/compose/duplicates`, { action: 'merge' });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.showToast(data.message || 'OK');
            const card = this.apps.find(a => a.name === p.app.name);
            if (card) card.dup_compose = 0;
            p.open = false;
            this.loadApps();
          } catch (err) { this.showToast(err.message); }
          finally { p.busy = false; }
        },

        confirmMergeDuplicates() {
          const m = this.editModal;
          this.askConfirm({
            tone: 'danger', title: this.t('dupMergeTitle'),
            message: `${m.composePath} → ${m.otherComposeFiles.join(', ')}. ${this.t('dupMergeMsg')}`,
            confirmLabel: this.t('dupMerge'), onConfirm: () => this.resolveDuplicates('merge')
          });
        },

        async resolveDuplicates(action) {
          const m = this.editModal;
          m.dupBusy = true;
          try {
            const { res, data } = await this._postJson(`/api/apps/${encodeURIComponent(m.app.name)}/compose/duplicates`, { action });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.showToast(data.message || 'OK');
            // Merge: biểu tượng "nhiều file compose" trên thẻ mất ngay. Skip: biểu tượng vẫn còn (app vẫn có
            // nhiều file compose), chỉ chuyển sang dạng "đã bỏ qua"; danh sách được tải lại để đồng bộ với server
            const card = this.apps.find(a => a.name === m.app.name);
            for (const a of [card, m.app]) {
              if (!a) continue;
              if (action === 'merge') a.dup_compose = 0; else a.dup_skipped = true;
            }
            await this._loadCompose(m.app.name, m.lastService);
            this.loadApps();
          } catch (err) { this.showToast(err.message); }
          finally { m.dupBusy = false; }
        },

        async openEditModal(app) {
          this.tagMenu = { open: false, loading: false, items: [], error: '', image: '' };
          this.editModal = {
            open: true, loading: true, saving: false, tab: 'ui',
            app, composePath: '', runMode: false, rawYaml: '', ui: null, otherComposeFiles: [], skippedComposeFiles: [], dupBusy: false, lastService: '', yamlTouched: false,
            backups: [], feedback: '', feedbackOk: true, feedbackLogs: '',
            sec: { container: true, ports: true, volumes: false, env: false, casaos: false }
          };
          await this._loadCompose(app.name);
        },

        async _loadCompose(name, service) {
          this.editModal.loading = true;
          try {
            const q = service ? `?service=${encodeURIComponent(service)}` : '';
            const res = await fetch(`/api/apps/${encodeURIComponent(name)}/compose${q}`);
            if (res.status === 401) { window.location.href = '/login'; return; }
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Cannot load docker-compose.yml');
            this.editModal.composePath = data.compose_path || '';
            this.editModal.runMode = !!data.run_mode;
            this.editModal.otherComposeFiles = data.other_compose_files || [];
            this.editModal.skippedComposeFiles = data.skipped_compose_files || [];
            this.editModal.rawYaml = data.raw_yaml || '';
            this.editModal.ui = data.ui || null;
            this.editModal.lastService = data.ui?.selected_service || '';
            this.editModal.backups = data.backups || [];
            this.editModal.yamlTouched = false;
            if (!data.ui) this.editModal.tab = 'yaml';
          } catch (err) {
            this.editModal.feedbackOk = false;
            this.editModal.feedback = err.message;
            this.editModal.tab = 'yaml';
          } finally {
            this.editModal.loading = false;
          }
        },

        closeEditModal() {
          if (this.editModal.saving) return;
          this.editModal.open = false;
        },

        // UI -> YAML (giữ nguyên comment & x-casaos nhờ ruamel.yaml)
        async _syncUiToYaml() {
          const m = this.editModal;
          if (!m.ui) return true;
          const { res, data } = await this._postJson(
            `/api/apps/${encodeURIComponent(m.app.name)}/compose/to-yaml`,
            { base_yaml: m.rawYaml, ui: JSON.parse(JSON.stringify(m.ui)) }
          );
          if (!res.ok) {
            m.feedbackOk = false; m.feedback = data.detail || 'Cannot convert UI to YAML';
            return false;
          }
          m.rawYaml = data.raw_yaml;
          return true;
        },

        // YAML -> UI
        async _syncYamlToUi() {
          const m = this.editModal;
          const { res, data } = await this._postJson(
            `/api/apps/${encodeURIComponent(m.app.name)}/compose/to-ui`,
            { raw_yaml: m.rawYaml, selected_service: m.lastService || m.ui?.selected_service || null }
          );
          if (!res.ok) {
            m.feedbackOk = false; m.feedback = data.detail || 'Invalid YAML';
            return false;
          }
          m.ui = data.ui;
          m.lastService = data.ui?.selected_service || '';
          m.yamlTouched = false;
          return true;
        },

        async switchEditTab(next) {
          const m = this.editModal;
          if (next === m.tab || m.loading) return;
          m.feedback = '';

          if (m.tab === 'ui' && next !== 'ui') {
            if (!(await this._syncUiToYaml())) return;
          }
          if (m.tab === 'yaml') m.yamlTouched = true;
          if (next === 'ui' && (m.yamlTouched || !m.ui)) {
            if (!(await this._syncYamlToUi())) return;
          }
          m.tab = next;
        },

        async reloadServiceUi() {
          const m = this.editModal;
          if (!m.ui) return;
          const target = m.ui.selected_service;
          const prev = m.lastService || target;
          m.feedback = '';
          try {
            if (prev !== target) {
              // Lưu lại thay đổi của service cũ vào YAML trước khi chuyển sang service mới
              const snapshot = JSON.parse(JSON.stringify(m.ui));
              snapshot.selected_service = prev;
              const { res, data } = await this._postJson(
                `/api/apps/${encodeURIComponent(m.app.name)}/compose/to-yaml`,
                { base_yaml: m.rawYaml, ui: snapshot }
              );
              if (!res.ok) throw new Error(data.detail || 'Cannot convert UI to YAML');
              m.rawYaml = data.raw_yaml;
            }
            const { res: r2, data: d2 } = await this._postJson(
              `/api/apps/${encodeURIComponent(m.app.name)}/compose/to-ui`,
              { raw_yaml: m.rawYaml, selected_service: target }
            );
            if (!r2.ok) throw new Error(d2.detail || 'Invalid YAML');
            m.ui = d2.ui;
            m.lastService = d2.ui?.selected_service || '';
          } catch (err) {
            m.feedbackOk = false; m.feedback = err.message;
          }
        },

        async validateCompose() {
          const m = this.editModal;
          m.feedback = '';
          if (m.tab === 'ui' && !(await this._syncUiToYaml())) return;
          m.saving = true;
          try {
            const { res, data } = await this._postJson(
              `/api/apps/${encodeURIComponent(m.app.name)}/compose/validate`,
              { raw_yaml: m.rawYaml }
            );
            m.feedbackOk = !!data.ok;
            m.feedback = data.message || data.detail || (res.ok ? '' : 'Validation failed');
          } catch (err) {
            m.feedbackOk = false; m.feedback = err.message;
          } finally {
            m.saving = false;
          }
        },

        async applyCompose() {
          const m = this.editModal;
          m.feedback = '';
          if (m.tab === 'ui' && !(await this._syncUiToYaml())) return;
          m.saving = true;
          try {
            const { res, data } = await this._postJson(
              `/api/apps/${encodeURIComponent(m.app.name)}/compose/apply`,
              { raw_yaml: m.rawYaml }
            );
            m.feedbackLogs = '';
            if (!res.ok) {
              m.feedbackLogs = data.logs || '';
              if (data.backups) m.backups = data.backups;
              if (data.logs) this.loadApps();  // compose cũ đã được trả lại -> làm mới trạng thái app
              throw new Error(data.detail || 'Apply failed');
            }
            if (data.backups) m.backups = data.backups;
            m.feedbackOk = true;
            m.feedback = this.lang === 'vi' ? 'Đã lưu & áp dụng cấu hình ✓' : 'Configuration saved & applied ✓';
            this.showToast(m.feedback);
            if (data.self_update) { this._waitAndReload(); return; }
            await this.loadApps();
            const fresh = this.apps.find(a => a.name === m.app.name);
            if (fresh) m.app = fresh;
            await this._loadCompose(m.app.name, m.lastService);
            m.feedbackOk = true;
            m.feedback = this.lang === 'vi' ? 'Đã lưu & áp dụng cấu hình ✓' : 'Configuration saved & applied ✓';
          } catch (err) {
            m.feedbackOk = false; m.feedback = err.message;
          } finally {
            m.saving = false;
          }
        },

        async rollbackCompose(filename) {
          const m = this.editModal;
          m.feedback = '';
          m.saving = true;
          try {
            const { res, data } = await this._postJson(
              `/api/apps/${encodeURIComponent(m.app.name)}/compose/rollback`,
              { filename }
            );
            if (!res.ok) throw new Error(data.detail || 'Rollback failed');
            this.showToast(this.lang === 'vi' ? 'Đã khôi phục cấu hình ✓' : 'Configuration restored ✓');
            if (data.self_update) { this._waitAndReload(); return; }
            await this.loadApps();
            await this._loadCompose(m.app.name, m.lastService);
            m.tab = 'ui';
            m.feedbackOk = true;
            m.feedback = this.lang === 'vi' ? `Đã khôi phục từ ${filename} ✓` : `Restored from ${filename} ✓`;
          } catch (err) {
            m.feedbackOk = false; m.feedback = err.message;
          } finally {
            m.saving = false;
          }
        },

        // ---------------- Smart Uninstall ----------------
        async openUninstallModal(app) {
          this.uninstallModal = {
            open: true, running: false, app,
            removeCompose: true, removeImages: false, removeAppdata: false,
            confirmName: '', error: '', check: null, imageChoice: 'keep', resultLogs: ''
          };
          // Những gì bị ảnh hưởng: app khác dùng chung image / AppData, stack nhiều service
          try {
            const res = await fetch(`/api/apps/${encodeURIComponent(app.name)}/uninstall-check`);
            if (res.ok) this.uninstallModal.check = await res.json();
          } catch (_) {}
        },

        // Danh sách việc sẽ làm + ảnh hưởng (hiện trong cửa sổ gỡ trước khi bấm)
        uninstallPlan() {
          const u = this.uninstallModal, c = u.check || {}, a = u.app || {};
          const vi = this.lang === 'vi', out = [];
          const users = c.image_users || [];
          out.push({ tone: 'danger', text: vi ? `Dừng và xoá container ${a.name}. App sẽ ngừng hoạt động.` : `Stop and delete the container ${a.name}. The app stops working.` });
          if ((c.stack_others || []).length) out.push({ tone: 'info', text: vi
            ? `Chỉ gỡ service này. ${c.stack_others.length} service khác của stack "${c.project}" (${c.stack_others.join(', ')}) vẫn chạy.`
            : `Only this service is removed. ${c.stack_others.length} other service(s) of stack "${c.project}" (${c.stack_others.join(', ')}) keep running.` });
          if (a.source === 'casaos') out.push(u.removeCompose
            ? { tone: 'warn', text: vi ? 'Xoá thư mục app của CasaOS (docker-compose.yml). App biến mất khỏi CasaOS.' : 'Delete the CasaOS app folder (docker-compose.yml). The app disappears from CasaOS.' }
            : { tone: 'ok', text: vi ? 'Giữ docker-compose.yml của CasaOS.' : 'Keep the CasaOS docker-compose.yml.' });
          if (!u.removeImages) out.push({ tone: 'ok', text: vi ? `Giữ image ${c.image || ''} trên ổ đĩa (cài lại nhanh, không tải lại).` : `Keep the image ${c.image || ''} on disk (fast reinstall, no download).` });
          else if (!users.length) out.push({ tone: 'warn', text: vi ? `Xoá image ${c.image || ''} để giải phóng dung lượng. Cài lại sẽ phải tải lại.` : `Delete the image ${c.image || ''} to free disk space. A reinstall downloads it again.` });
          else if (u.imageChoice === 'keep') out.push({ tone: 'ok', text: vi
            ? `Giữ image: nó vẫn đang được ${users.map(x => x.name).join(', ')} dùng (xoá sẽ làm hỏng các app đó).`
            : `Keep the image: it is still used by ${users.map(x => x.name).join(', ')} (deleting it would break those apps).` });
          else out.push({ tone: 'danger', text: vi
            ? `Gỡ luôn ${users.map(x => x.name).join(', ')} (chỉ container; AppData của các app đó được giữ), rồi xoá image.`
            : `Also uninstall ${users.map(x => x.name).join(', ')} (containers only; their AppData is kept), then delete the image.` });
          if (a.appdata_path) out.push(u.removeAppdata
            ? { tone: 'danger', text: (vi ? `XOÁ VĨNH VIỄN dữ liệu trong ${a.appdata_path}. Không thể khôi phục.` : `PERMANENTLY delete the data in ${a.appdata_path}. This cannot be undone.`)
                + ((c.appdata_users || []).length ? (vi ? ` Thư mục này cũng đang được ${c.appdata_users.join(', ')} dùng: các app đó sẽ mất dữ liệu.` : ` This folder is also used by ${c.appdata_users.join(', ')}: those apps will lose data.`) : '') }
            : { tone: 'ok', text: vi ? `Giữ dữ liệu trong ${a.appdata_path} (cài lại app sẽ dùng lại dữ liệu này).` : `Keep the data in ${a.appdata_path} (a reinstall reuses it).` });
          out.push({ tone: 'info', text: vi ? 'Các bản sao lưu của AppManager cho app này vẫn được giữ trong Cài đặt.' : "AppManager's backups of this app are kept (Settings)." });
          return out;
        },

        requestUninstall() {
          const u = this.uninstallModal, users = (u.check?.image_users || []);
          const risky = u.removeAppdata || (u.removeImages && users.length && u.imageChoice === 'remove');
          if (!risky) return this.confirmUninstall();
          this.askConfirm({
            tone: 'danger', title: this.t('uninstallConfirmTitle').replace('{app}', u.app.title),
            message: this.uninstallPlan().filter(x => x.tone === 'danger').map(x => '• ' + x.text).join('\n'),
            confirmLabel: this.t('confirmUninstall'), onConfirm: () => this.confirmUninstall()
          });
        },

        async confirmUninstall() {
          const u = this.uninstallModal;
          if (!u.app || u.running) return;
          u.running = true; u.error = '';
          try {
            const { res, data } = await this._postJson(
              `/api/apps/${encodeURIComponent(u.app.name)}/uninstall`,
              {
                remove_compose: u.removeCompose, remove_images: u.removeImages,
                remove_appdata: u.removeAppdata, confirm_name: u.confirmName,
                remove_image_users: (u.removeImages && u.imageChoice === 'remove') ? (u.check?.image_users || []).map(x => x.name) : []
              }
            );
            if (!res.ok) throw new Error(data.detail || 'Uninstall failed');
            const title = u.app.title;
            this.showToast(this.lang === 'vi' ? `Đã gỡ ${title} ✓` : `${title} uninstalled ✓`);
            // Hiện kết quả từng bước (vd image được giữ vì app khác đang dùng) thay vì đóng ngay
            u.resultLogs = data.logs || '';
            if (!u.resultLogs) u.open = false;
            await this.loadApps();
          } catch (err) {
            u.error = err.message;
          } finally {
            u.running = false;
          }
        },

        // ---------------- Task Manager (WebSocket /ws/task-manager) ----------------
        get taskRows() {
          const rows = (this.taskModal.data && this.taskModal.data.tasks) || [];
          const by = this.taskSort;
          return [...rows].sort((a, b) => {
            const run = (b.status === 'running') - (a.status === 'running');
            if (run) return run;
            if (by === 'name') return (a.title || '').localeCompare(b.title || '');
            if (by === 'mem') return b.mem_bytes - a.mem_bytes;
            return b.cpu_pct - a.cpu_pct || b.mem_bytes - a.mem_bytes;
          });
        },

        formatBytesJs(n) {
          let v = Math.max(0, Number(n) || 0);
          const u = ['B', 'KB', 'MB', 'GB', 'TB'];
          let i = 0;
          while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
          return i === 0 ? `${Math.round(v)} B` : `${v.toFixed(2)} ${u[i]}`;
        },

        // Ước tính dung lượng sẽ giải phóng theo các mục đang chọn (-1 = chưa chọn mục nào)
        get pruneEstimateBytes() {
          const d = this.storageState.data, o = this.pruneOpts;
          if (!d) return -1;
          if (!o.prune_images && !o.prune_build_cache && !o.prune_containers && !o.prune_volumes) return -1;
          let sum = 0;
          if (o.prune_images) sum += o.all_unused_images ? d.images.unused_bytes : d.images.dangling_bytes;
          if (o.prune_build_cache) sum += d.build_cache.reclaimable_bytes;
          if (o.prune_containers) sum += d.containers.reclaimable_bytes;
          if (o.prune_volumes) sum += d.volumes.reclaimable_bytes;
          return sum;
        },

        // Thanh phân bổ dung lượng thu hồi
        get storageSegments() {
          const d = this.storageState.data;
          if (!d) return [];
          const parts = [
            { key: 'img', label: 'segImages', bytes: d.images.unused_bytes, text: d.images.unused_size, cls: 'bg-sky-400' },
            { key: 'cache', label: 'segCache', bytes: d.build_cache.reclaimable_bytes, text: d.build_cache.reclaimable_size, cls: 'bg-violet-400' },
            { key: 'cnt', label: 'segContainers', bytes: d.containers.reclaimable_bytes, text: d.containers.reclaimable_size, cls: 'bg-amber-400' },
            { key: 'vol', label: 'segVolumes', bytes: d.volumes.reclaimable_bytes, text: d.volumes.reclaimable_size, cls: 'bg-rose-400' },
          ];
          const total = parts.reduce((a, p) => a + p.bytes, 0) || 1;
          return parts.map(p => ({ ...p, pct: Math.round((p.bytes / total) * 1000) / 10 }));
        },

        confirmKill(app) {
          this.askConfirm({
            tone: 'danger', title: this.t('confirmKillTitle'),
            message: `"${app.title}" ${this.t('confirmKillMsg')}`,
            confirmLabel: this.t('kill'), onConfirm: () => this.runAction(app, 'kill')
          });
        },

        openTaskManager() {
          if (this.taskModal.ws) { try { this.taskModal.ws.close(); } catch (_) {} }
          const ws = new WebSocket(this.wsUrl('/ws/task-manager'));
          this.taskModal = { open: true, connected: false, data: null, ws };
          ws.onmessage = (event) => {
            if (this.taskModal.ws !== ws) return;
            try { this.taskModal.data = JSON.parse(event.data); this.taskModal.connected = true; } catch (_) {}
          };
          ws.onclose = (event) => {
            if (this.taskModal.ws !== ws) return;
            this.taskModal.connected = false;
            if (event.code === 4401) window.location.href = '/login';
          };
        },

        closeTaskManager() {
          if (this.taskModal.ws) { try { this.taskModal.ws.close(); } catch (_) {} }
          this.taskModal = { open: false, connected: false, data: null, ws: null };
        },

        // ---------------- Settings ----------------
        async openSettings() {
          this.settingsModal = { open: true, tab: 'home' };
          this.uiBase = { ...this.ui };
          if (this.isAdmin()) { this.refreshDataStatus(); this.loadUsers(); this.loadSso(); }
          try {
            const res = await fetch('/api/settings');
            if (res.status === 401) { window.location.href = '/login'; return; }
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed to load settings');
            this.settingsForm = { ...data.settings, github_token: '' };
            this._snapSettings();
            this.updateHistory = data.history || [];
          } catch (err) { this.showToast(err.message); }
          if (this.isAdmin()) { this.loadApiStatus(); this.loadNotify(); this.loadTokens(); }
          // tóm tắt trên trang đầu (2FA bật / tắt)
          fetch('/api/auth/security').then(r => r.ok ? r.json() : null).then(d => { if (d) this.security.totp_enabled = !!d.totp_enabled; }).catch(() => {});
        },

        openSettingsSection(tab) {
          this.settingsModal.tab = tab;
          if (tab === 'storage') { this.loadStorage(); this.loadBackups(); this.refreshDataStatus(); }
          else if (tab === 'notify') { this.loadNotify(); this.loadWebPush(); }
          else if (tab === 'security') this.loadSecurity();
          else if (tab === 'tokens') this.loadTokens();
          else if (tab === 'servers') this.loadServers(true);
          else if (tab === 'users') this.loadUsers();
          else if (tab === 'sso') this.loadSso();
          else if (tab === 'config') this.loadConfigBackup();
          else if (tab === 'cache' && this.isAdmin()) this.loadCaches();
        },

        // ---------------- Nhiều máy chủ (0.18) ----------------
        async loadServers(withStatus = false) {
          const v = this.srv;
          try {
            const res = await fetch('/api/servers');
            if (!res.ok) return;
            v.list = (await res.json()).servers || []; v.loaded = true;
            if (withStatus && v.list.length) this.refreshServerStatus();
          } catch (_) {}
        },

        async refreshServerStatus() {
          const v = this.srv;
          if (v.statusBusy) return;
          v.statusBusy = true;
          try {
            const res = await fetch('/api/servers/status');
            if (res.ok) v.list = (await res.json()).servers || v.list;
          } catch (_) {}
          finally { v.statusBusy = false; }
        },

        serverStatusText(s) {
          const st = s.status || {};
          if (!st.checked) return this.t('svChecking');
          if (!st.ok) return st.error || this.t('svOffline');
          const a = st.apps || {};
          return [`v${st.version}`, this.t('svApps').replace('{n}', a.total ?? 0),
                  a.updates ? this.t('svUpdates').replace('{n}', a.updates) : '', st.latency_ms != null ? `${st.latency_ms} ms` : ''].filter(Boolean).join(' · ');
        },

        openServerForm(s = null) {
          Object.assign(this.srv, { test: null, error: '', busy: false });
          this.srv.form = s ? { open: true, id: s.id, name: s.name, url: s.url, token: '', verify_tls: s.verify_tls }
                            : { open: true, id: '', name: '', url: '', token: '', verify_tls: true };
        },

        async testServerForm() {
          const v = this.srv;
          v.busy = true; v.error = ''; v.test = null;
          try {
            const { res, data } = await this._postJson('/api/servers/test', v.form);
            if (!res.ok) throw new Error(data.detail || 'Failed');
            v.test = data;
          } catch (err) { v.error = err.message; }
          finally { v.busy = false; }
        },

        async saveServerForm() {
          const v = this.srv;
          v.busy = true; v.error = '';
          try {
            const { res, data } = await this._postJson('/api/servers', v.form);
            if (!res.ok) throw new Error(data.detail || 'Failed');
            v.form.open = false;
            this.showToast(data.status?.ok ? this.t('svSaved') : this.t('svSavedOffline'));
            await this.loadServers();
          } catch (err) { v.error = err.message; }
          finally { v.busy = false; }
        },

        confirmDeleteServer(s) {
          this.askConfirm({
            tone: 'danger', title: this.t('svDeleteTitle'), message: `${s.name} (${s.url}) — ${this.t('svDeleteMsg')}`,
            confirmLabel: this.t('svDelete'),
            onConfirm: async () => {
              const { res, data } = await this._postJson('/api/servers/delete', { id: s.id });
              if (!res.ok) { this.showToast(data.detail || 'Failed'); return; }
              if (this.remote.id === s.id || (this.remote.id === '*' && this.srv.list.length <= 1)) this.selectServer('');
              this.loadServers();
            }
          });
        },

        currentServer() { return this.srv.list.find(x => x.id === this.remote.id) || null; },
        // Máy của một app trên thẻ (danh sách gộp mọi máy có trường _server; trang một máy thì là máy đang chọn)
        currentServerOf(app) { return (app && app._server && this.srv.list.find(x => x.id === app._server)) || this.currentServer(); },

        selectServer(id) {
          this.remote.id = id; this.remote.data = null; this.remote.error = '';
          if (id) { this.settingsModal.open = false; this.reloadRemote(); window.scrollTo(0, 0); }
          else this.loadApps();
        },

        reloadRemote() { return this.remote.id === '*' ? this.loadAllServersApps() : this.loadRemoteApps(); },

        // 0.21: gộp app của máy này + mọi máy phụ vào một danh sách (máy không trả lời -> báo lỗi riêng, máy khác vẫn hiện)
        async loadAllServersApps() {
          const r = this.remote;
          r.loading = true; r.error = '';
          try {
            const remotes = Promise.all(this.srv.list.map(async sv => {
              try {
                const res = await fetch(`/api/servers/${sv.id}/apps`);
                const d = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(d.detail || 'Failed');
                sv.status = { ...(sv.status || {}), ok: true, checked: Math.floor(Date.now() / 1000), apps: d.summary || {} };
                return { sv, apps: d.apps || [] };
              } catch (err) {
                sv.status = { ...(sv.status || {}), ok: false, checked: Math.floor(Date.now() / 1000), error: err.message };
                return { sv, apps: [], error: err.message };
              }
            }));
            await this.loadApps();
            const results = await remotes;
            if (r.id !== '*') return;
            const remoteApps = [];
            for (const x of results) for (const a of x.apps) remoteApps.push({ ...a, _server: x.sv.id, _serverName: x.sv.name });
            r.data = { apps: remoteApps, summary: {}, errors: results.filter(x => x.error).map(x => ({ name: x.sv.name, error: x.error })), servers: results.length + 1 };
            this._mergeLocal();
          } catch (err) { if (r.id === '*') r.error = err.message; }
          finally { if (r.id === '*') r.loading = false; }
        },

        // Thẻ app hiển thị ở chế độ máy phụ / gộp mọi máy (gộp: lọc theo ô tìm — tên app, image, tên máy)
        remoteApps() {
          const r = this.remote, list = r.data?.apps || [];
          const q = (r.q || '').trim().toLowerCase();
          if (r.id !== '*' || !q) return list;
          return list.filter(a => [a.title, a.name, a.image, a._serverName].some(x => String(x || '').toLowerCase().includes(q)));
        },

        // Danh sách gộp: thay phần app của máy này bằng dữ liệu mới (sau khi cập nhật / thao tác trên máy này)
        _mergeLocal() {
          const d = this.remote.data;
          this.apps.forEach(a => { a._server = ''; a._serverName = this.t('svThis'); });
          d.apps = [...this.apps, ...d.apps.filter(a => a._server)]
            .sort((a, b) => (!!b.has_update - !!a.has_update) || String(a.title).localeCompare(String(b.title)) || a._serverName.localeCompare(b._serverName));
          d.summary = { total: d.apps.length, updates: d.apps.filter(a => a.has_update).length };
        },

        rkey(app) { return `${app._server ?? this.remote.id}/${app.name}`; },

        async loadRemoteApps() {
          const r = this.remote, id = r.id;
          if (!id) return;
          r.loading = true; r.error = '';
          try {
            const res = await fetch(`/api/servers/${id}/apps`);
            const data = await res.json();
            if (r.id !== id) return;
            if (!res.ok) throw new Error(data.detail || 'Failed');
            data.apps.sort((a, b) => (b.has_update - a.has_update) || a.title.localeCompare(b.title));
            r.data = data;
            const sv = this.srv.list.find(x => x.id === id);  // số app / bản mới trên thanh chọn máy theo dữ liệu mới nhất
            if (sv) sv.status = { ...(sv.status || {}), ok: true, checked: Math.floor(Date.now() / 1000), apps: data.summary || {} };
          } catch (err) { if (r.id === id) { r.error = err.message; r.data = null; } }
          finally { if (r.id === id) r.loading = false; }
        },

        async remoteCheck() {
          const r = this.remote, id = r.id;
          r.checking = true; r.error = '';
          try {
            const { res, data } = await this._postJson(`/api/servers/${id}/check`, {});
            if (!res.ok) throw new Error(data.detail || 'Failed');
            await this.loadRemoteApps(); this.refreshServerStatus();
          } catch (err) { r.error = err.message; }
          finally { r.checking = false; }
        },

        confirmRemoteUpdate(app) {
          const s = this.currentServerOf(app);
          this.askConfirm({
            tone: 'update', title: this.t('svUpdateTitle').replace('{app}', app.title),
            message: this.t('svUpdateMsg').replace('{server}', s?.name || '').replace('{from}', app.version || '?').replace('{to}', app.remote_version || '?'),
            confirmLabel: this.t('updateNow'), onConfirm: () => this.startRemoteJob(app, `/api/servers/${s.id}/apps/${encodeURIComponent(app.name)}/update`, s)
          });
        },

        confirmRemoteUpdateAll() {
          const s = this.currentServer(), n = this.remote.data?.summary?.updates || 0;
          this.askConfirm({
            tone: 'update', title: this.t('svUpdateAllTitle').replace('{server}', s?.name || ''),
            message: this.t('svUpdateAllMsg').replace('{n}', n), confirmLabel: this.t('svUpdateAll'),
            onConfirm: () => this.startRemoteJob({ title: this.t('svAllApps') }, `/api/servers/${s.id}/update-all`)
          });
        },

        async startRemoteJob(app, url, server = null) {
          const s = server || this.currentServer(), j = this.remoteJob;
          Object.assign(j, { open: true, server: s, app: app.title, id: '', status: 'starting', log: '', result: {}, error: '' });
          try {
            const { res, data } = await this._postJson(url, {});
            if (!res.ok) throw new Error(data.detail || 'Failed');
            j.id = data.id; j.status = data.status;
            this._pollRemoteJob();
          } catch (err) { j.status = 'failed'; j.error = err.message; }
        },

        async _pollRemoteJob() {
          const j = this.remoteJob;
          if (!j.open || !j.id) return;
          try {
            const res = await fetch(`/api/servers/${j.server.id}/jobs/${j.id}`);
            const data = await res.json();
            if (res.ok) {
              j.log = data.log || ''; j.status = data.status; j.result = data.result || {};
              this.$nextTick(() => { const el = document.getElementById('remote-job-log'); if (el) el.scrollTop = el.scrollHeight; });
              if (data.status !== 'running') { this.reloadRemote(); this.refreshServerStatus(); return; }
            } else j.error = data.detail || 'Failed';
          } catch (err) { j.error = err.message; }
          setTimeout(() => this._pollRemoteJob(), 2000);
        },

        async remoteAction(app, action) {
          const s = this.currentServerOf(app), r = this.remote;
          const go = async () => {
            r.busy = this.rkey(app);
            try {
              const { res, data } = await this._postJson(`/api/servers/${s.id}/apps/${encodeURIComponent(app.name)}/${action}`, {});
              if (!res.ok) throw new Error(data.detail || 'Failed');
              this.showToast(this.t('svActionDone').replace('{app}', app.title));
              await this.reloadRemote();
            } catch (err) { this.showToast(err.message); }
            finally { r.busy = ''; }
          };
          if (action === 'stop') {
            this.askConfirm({ tone: 'danger', title: this.t('svStopTitle').replace('{app}', app.title),
                              message: this.t('svStopMsg').replace('{server}', s.name), confirmLabel: this.t('stop'), onConfirm: go });
          } else go();
        },

        // ---------------- API token (0.17) ----------------
        async loadTokens() {
          const st = this.tokenState;
          st.loading = true;
          try {
            const res = await fetch('/api/tokens');
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            st.items = data.tokens || []; st.loaded = true;
          } catch (err) { this.showToast(err.message); }
          finally { st.loading = false; }
        },

        tokenScopes() {
          return [
            { id: 'read', title: this.t('tkRead'), desc: this.t('tkReadDesc'), cls: 'bg-sky-500/15 text-sky-300' },
            { id: 'update', title: this.t('tkUpdate'), desc: this.t('tkUpdateDesc'), cls: 'bg-amber-500/15 text-amber-300' },
            { id: 'full', title: this.t('tkFull'), desc: this.t('tkFullDesc'), cls: 'bg-rose-500/15 text-rose-300' },
          ];
        },

        tokenScope(id) { return this.tokenScopes().find(s => s.id === id) || this.tokenScopes()[0]; },

        tokenExpiry(t) {
          if (!t.expires) return this.t('tkNoExpiry');
          return (t.expired ? this.t('tkExpired') : this.t('tkExpires')) + ' ' + this.formatTs(t.expires);
        },

        openTokenForm() {
          Object.assign(this.tokenState, { created: '', error: '' });
          this.tokenState.form = { open: true, name: '', scope: 'read', days: 90, ips: '' };
        },

        async createToken() {
          const st = this.tokenState, f = st.form;
          st.busy = true; st.error = '';
          try {
            const { res, data } = await this._postJson('/api/tokens', { name: f.name, scope: f.scope, days: Number(f.days) || 0, ips: f.ips });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            st.created = data.token;
            this.loadTokens();
          } catch (err) { st.error = err.message; }
          finally { st.busy = false; }
        },

        closeTokenForm() {
          this.tokenState.form.open = false;
          this.tokenState.created = '';  // token không còn trong bộ nhớ trang
        },

        confirmDeleteToken(t) {
          this.askConfirm({
            tone: 'danger', title: this.t('tkDeleteTitle'),
            message: `${t.name} (${t.hint}) — ${this.t('tkDeleteMsg')}`,
            confirmLabel: this.t('tkDelete'),
            onConfirm: async () => {
              try {
                const { res, data } = await this._postJson('/api/tokens/delete', { id: t.id });
                if (!res.ok) throw new Error(data.detail || 'Failed');
                this.showToast(this.t('tkDeleted')); this.loadTokens();
              } catch (err) { this.showToast(err.message); }
            }
          });
        },

        tokenExamples() {
          const base = location.origin;
          return [
            { title: 'curl', code: `curl -H "Authorization: Bearer amp_…" ${base}/api/health\n\n# ${this.t('tkExUpdate')}\ncurl -X POST -H "Authorization: Bearer amp_…" ${base}/api/apps/<app>/update\ncurl -H "Authorization: Bearer amp_…" ${base}/api/jobs/<job_id>` },
            { title: 'Home Assistant', code: `# configuration.yaml\nrest:\n  - resource: ${base}/api/health\n    headers:\n      Authorization: "Bearer amp_…"\n    scan_interval: 300\n    sensor:\n      - name: "AppManager updates"\n        value_template: "{{ value_json.apps.updates }}"\n\nrest_command:\n  appmanager_update_all:\n    url: ${base}/api/update-all\n    method: POST\n    headers:\n      Authorization: "Bearer amp_…"` },
            { title: 'Uptime Kuma', code: `${this.t('tkExKuma')}\nURL: ${base}/api/health\nKeyword: "ok"` },
          ];
        },

        settingsSectionTitle() {
          return {
            home: this.t('settingsTitle'), language: this.t('language'), appearance: this.t('appearance'), cache: this.t('setCache'), schedule: this.t('setGeneral'), storage: this.t('setStorage'), users: this.t('setUsers'), sso: this.t('setSso'), config: this.t('setConfig'),
            notify: this.t('setNotify'), servers: this.t('setServers'), security: this.t('tabSecurity'), tokens: this.t('setTokens'), history: this.t('tabHistory'), about: this.t('tabAbout'),
          }[this.settingsModal.tab] || this.t('settingsTitle');
        },

        // Trang đầu Cài đặt: nhóm mục (thêm mục mới cho 0.17+ ở đây: API token, máy chủ…)
        settingsMenu() {
          const st = this.dataSetup.status;
          const I = {
            gear: 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
            disk: 'M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125',
            bell: 'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0',
            lock: 'M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z',
            clock: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z',
            servers: 'M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z',
            key: 'M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z',
            info: 'M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z',
          };
          // tên class viết đầy đủ để Tailwind biên dịch được
          const C = { sky: 'bg-sky-500/15 border-sky-400/35 text-sky-400', emerald: 'bg-emerald-500/15 border-emerald-400/35 text-emerald-400',
            amber: 'bg-amber-500/15 border-amber-400/35 text-amber-400', rose: 'bg-rose-500/15 border-rose-400/35 text-rose-400',
            violet: 'bg-violet-500/15 border-violet-400/35 text-violet-400', slate: 'bg-slate-500/15 border-slate-400/35 text-slate-300' };
          const c = (x) => C[x];
          I.archive = 'M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m8.25 3v6.75m0 0l-3-3m3 3l3-3M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z';
          I.sso = 'M7.864 4.243A7.5 7.5 0 0119.5 10.5c0 2.92-.556 5.709-1.568 8.268M5.742 6.364A7.465 7.465 0 004.5 10.5a7.464 7.464 0 01-1.15 3.993m1.989 3.559A11.209 11.209 0 008.25 10.5a3.75 3.75 0 117.5 0c0 .527-.021 1.049-.064 1.565M12 10.5a14.94 14.94 0 01-3.6 9.75m6.633-4.596a18.666 18.666 0 01-2.485 5.33';
          I.users = 'M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z';
          const admin = this.isAdmin();
          // Không phải Quản trị: chỉ còn tài khoản của mình (mật khẩu / 2FA), lịch sử cập nhật, giới thiệu
          const keep = admin ? null : new Set(['appearance', 'language', 'security', 'history', 'about', 'cache']);
          I.swatch = 'M4.098 19.902a3.75 3.75 0 005.304 0l6.401-6.402M6.75 21A3.75 3.75 0 013 17.25V4.125C3 3.504 3.504 3 4.125 3h5.25c.621 0 1.125.504 1.125 1.125v4.072M6.75 21a3.75 3.75 0 003.75-3.75V8.197M6.75 21h13.125c.621 0 1.125-.504 1.125-1.125v-5.25c0-.621-.504-1.125-1.125-1.125h-4.072M10.5 8.197l2.88-2.88c.438-.439 1.15-.439 1.59 0l3.712 3.713c.44.44.44 1.152 0 1.59l-2.879 2.88M6.75 17.25h.008v.008H6.75v-.008z';
          I.globe = 'M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418';
          const f = this.settingsForm || {};
          const general = f.auto_update_enabled
            ? this.t('sumAuto').replace('{t}', f.auto_update_time || '03:30').replace('{h}', f.check_interval_hours || 6)
            : this.t('sumCheck').replace('{h}', f.check_interval_hours || 6);
          const chans = (this.notifyState.channels || []).filter(x => x.enabled).length;
          const toks = (this.tokenState.items || []).length;
          const menu = [
            { id: 'pref', label: this.t('grpPersonal'), items: [
              { tab: 'appearance', title: this.t('appearance'), desc: this.uiSummary(), icon: I.swatch, color: c('violet') },
              { tab: 'language', title: this.t('language'), desc: this.lang === 'vi' ? 'Tiếng Việt' : 'English', icon: I.globe, color: c('sky') },
            ] },
            { id: 'main', label: this.t('grpGeneral'), items: [
              { tab: 'schedule', title: this.t('setGeneral'), desc: this.settingsBase ? general : this.t('setGeneralDesc'), icon: I.gear, color: c('sky') },
              { tab: 'storage', title: this.t('setStorage'), desc: st?.missing_count ? this.t('dataFoldersMissing').replace('{n}', st.missing_count) : this.t('setStorageDesc'), warn: !!st?.missing_count, icon: I.disk, color: c('emerald') },
              { tab: 'notify', title: this.t('setNotify'), desc: chans ? this.t('sumChannels').replace('{n}', chans) : this.t('setNotifyDesc'), icon: I.bell, color: c('amber') },
              { tab: 'servers', title: this.t('setServers'), desc: this.srv.list.length ? this.t('svCount').replace('{n}', this.srv.list.length) : this.t('setServersDesc'), icon: I.servers, color: c('violet') },
            ] },
            { id: 'safety', label: this.t('grpSecurity'), items: [
              { tab: 'security', title: this.t('tabSecurity'), desc: this.security.totp_enabled ? this.t('sum2faOn') : this.t('sum2faOff'), icon: I.lock, color: c('rose') },
              { tab: 'sso', title: this.t('setSso'), desc: this.ssoState.cfg?.enabled ? this.t('ssoOnWith').replace('{p}', this.ssoState.cfg.label || 'SSO') : this.t('setSsoDesc'), icon: I.sso, color: c('violet') },
              { tab: 'users', title: this.t('setUsers'), desc: this.usersState.list.length > 1 ? this.t('usCount').replace('{n}', this.usersState.list.length) : this.t('setUsersDesc'), icon: I.users, color: c('emerald') },
              { tab: 'config', title: this.t('setConfig'), desc: this.t('setConfigDesc'), icon: I.archive, color: c('amber') },
              { tab: 'tokens', title: this.t('setTokens'), desc: toks ? this.t('sumTokens').replace('{n}', toks) : this.t('setTokensDesc'), icon: I.key, color: c('sky') },
            ] },
            { id: 'about', label: this.t('grpOther'), items: [
              { tab: 'history', title: this.t('tabHistory'), desc: (this.updateHistory || []).length ? this.t('sumHistory').replace('{n}', this.updateHistory.length) : this.t('setHistoryDesc'), icon: I.clock, color: c('violet') },
              { tab: 'about', title: this.t('tabAbout'), desc: this.t('setAboutDesc'), icon: I.info, color: c('slate') },
              { tab: 'cache', title: this.t('setCache'), desc: this.t('setCacheDesc'),
                icon: 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99', color: c('sky') },
            ] },
          ];
          if (!keep) return menu;
          return menu.map(g => ({ ...g, items: g.items.filter(it => keep.has(it.tab)) })).filter(g => g.items.length);
        },

        // ---------------- Thông báo ----------------
        notifyFields(type) {
          return {
            telegram: [{ k: 'bot_token', secret: true, ph: '123456789:AA…' }, { k: 'chat_id', ph: '123456789' }],
            discord: [{ k: 'webhook_url', secret: true, ph: 'https://discord.com/api/webhooks/…' }],
            slack: [{ k: 'webhook_url', secret: true, ph: 'https://hooks.slack.com/services/…' }],
            teams: [{ k: 'webhook_url', secret: true, ph: 'https://….logic.azure.com/workflows/…' }],
            googlechat: [{ k: 'webhook_url', secret: true, ph: 'https://chat.googleapis.com/v1/spaces/…' }],
            mattermost: [{ k: 'webhook_url', secret: true, ph: 'https://mattermost.example.com/hooks/…' }],
            matrix: [{ k: 'server', ph: 'https://matrix.org' }, { k: 'access_token', secret: true, ph: 'syt_…' }, { k: 'room_id', ph: '!abc123:matrix.org' }],
            signal: [{ k: 'server', ph: 'http://192.168.1.10:8080' }, { k: 'number', ph: '+84901234567' }, { k: 'recipients', ph: '+84912345678, group.abc…' }],
            ntfy: [{ k: 'server', ph: 'https://ntfy.sh', optional: true }, { k: 'topic', ph: 'appmanager-…' }, { k: 'token', secret: true, ph: 'tk_…', optional: true }],
            gotify: [{ k: 'server', ph: 'https://gotify.example.com' }, { k: 'app_token', secret: true, ph: 'A…' }],
            bark: [{ k: 'server', ph: 'https://api.day.app', optional: true }, { k: 'device_key', secret: true, ph: 'xxxxxxxxxxxxxxxxxxxx' }],
            pushover: [{ k: 'app_token', secret: true, ph: 'azGDORePK8gMaC0QOYAMyEEuzJnyUi' }, { k: 'user_key', secret: true, ph: 'uQiRzpo4DXghDmr9QzzfQu27cmVRsG' }],
            pushbullet: [{ k: 'access_token', secret: true, ph: 'o.xxxxxxxx' }],
            email: [{ k: 'host', ph: 'smtp.gmail.com' }, { k: 'security', options: ['starttls', 'ssl', 'none'] }, { k: 'port', ph: '587', optional: true },
                    { k: 'username', ph: 'you@gmail.com', optional: true }, { k: 'password', secret: true, ph: '…', optional: true },
                    { k: 'sender', ph: 'AppManager <you@gmail.com>' }, { k: 'to', ph: 'you@example.com, …' }],
            apprise: [{ k: 'server', ph: 'http://192.168.1.10:8000' }, { k: 'key', ph: 'appmanager', optional: true }, { k: 'urls', secret: true, ph: 'whatsapp://…, line://…', optional: true }],
            webhook: [{ k: 'url', ph: 'https://example.com/hook' }, { k: 'secret', secret: true, ph: '…', optional: true }],
          }[type] || [];
        },
        notifyGroups() {
          return [
            { id: 'chat', types: ['telegram', 'discord', 'slack', 'teams', 'googlechat', 'mattermost', 'matrix', 'signal'] },
            { id: 'push', types: ['webpush', 'ntfy', 'bark', 'pushover', 'pushbullet', 'gotify'] },
            { id: 'other', types: ['email', 'apprise', 'webhook'] },
          ];
        },
        // Thiết bị nhận được (để người dùng iPhone biết chọn kênh nào)
        notifyPlatforms(t) {
          const all = 'ios,android,windows,macos,linux,web';
          return ({
            telegram: all, discord: all, slack: all, mattermost: all, matrix: all, email: all,
            teams: 'ios,android,windows,macos,web', googlechat: 'ios,android,web', signal: 'ios,android,windows,macos,linux',
            ntfy: 'ios,android,web', bark: 'ios', pushover: 'ios,android,web', pushbullet: 'android,windows,web', gotify: 'android,web',
            apprise: '', webhook: '', webpush: all,
          }[t] || '').split(',').filter(Boolean);
        },
        platformLabel(p) { return { ios: 'iOS', android: 'Android', windows: 'Windows', macos: 'macOS', linux: 'Linux', web: 'Web' }[p] || p; },
        // Biểu tượng nền tảng (SVG 24×24, vẽ đơn giản, màu theo chữ)
        platformIcon(p) {
          return {
            ios: '<path fill="currentColor" d="M16.4 12.7c0-2.4 2-3.5 2.1-3.6-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.6.9-.8 0-1.9-.9-3.1-.8-1.6 0-3.1.9-3.9 2.4-1.7 2.9-.4 7.1 1.2 9.4.8 1.1 1.7 2.4 3 2.4 1.2-.1 1.7-.8 3.1-.8 1.5 0 1.9.8 3.2.8 1.3 0 2.1-1.2 2.9-2.3.9-1.3 1.3-2.6 1.3-2.7-.1 0-2.6-1-2.7-3.8zM14 5.6c.7-.8 1.1-1.9 1-3-1 0-2.1.7-2.8 1.5-.6.7-1.2 1.8-1 2.9 1.1.1 2.1-.6 2.8-1.4z"/>',
            android: '<g fill="currentColor"><path d="M5 10.5a7 6 0 0 1 14 0z"/><rect x="5" y="11.5" width="14" height="8" rx="1.6"/><rect x="2" y="11.5" width="2.2" height="6" rx="1.1"/><rect x="19.8" y="11.5" width="2.2" height="6" rx="1.1"/><rect x="8" y="18" width="2.4" height="4" rx="1.2"/><rect x="13.6" y="18" width="2.4" height="4" rx="1.2"/></g><g stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M7.6 4.2l1.6 2.6M16.4 4.2l-1.6 2.6"/></g><circle cx="9.3" cy="8.4" r=".9" fill="#0b1220"/><circle cx="14.7" cy="8.4" r=".9" fill="#0b1220"/>',
            windows: '<path fill="currentColor" d="M3 5.3l7.4-1v7.2H3zM11.4 4.1L21 2.8v8.7h-9.6zM3 12.5h7.4v7.2L3 18.7zM11.4 12.5H21v8.7l-9.6-1.3z"/>',
            macos: '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="1.6"/><path d="M1.5 19.5h21M9 16l-.5 3.5M15 16l.5 3.5"/></g>',
            linux: '<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="M6.5 9l3 3-3 3M12 15h5"/></g>',
            web: '<g fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.6 5.6 3.6 9S14.5 18.4 12 21c-2.5-2.6-3.6-5.6-3.6-9S9.5 5.6 12 3z"/></g>',
          }[p] || '';
        },
        notifyTypeLabel(t) {
          return { telegram: 'Telegram', discord: 'Discord', slack: 'Slack', teams: 'Teams', googlechat: 'Google Chat', mattermost: 'Mattermost',
                   matrix: 'Matrix', signal: 'Signal', ntfy: 'ntfy', gotify: 'Gotify', bark: 'Bark', pushover: 'Pushover', pushbullet: 'Pushbullet',
                   email: 'Email', apprise: 'Apprise', webhook: 'Webhook', webpush: 'Web Push' }[t] || t;
        },
        // Icon vector cho trạng thái (thay ký hiệu chữ / emoji): danger = X, warn = !, ok = ✓, info = i
        toneIcon(tone) {
          return {
            danger: '<path d="M6 6l12 12M18 6L6 18"/>',
            warn: '<path d="M12 4v10"/><circle cx="12" cy="19" r="0.6" fill="currentColor"/>',
            ok: '<path d="M4.5 12.5l5 5L19.5 7"/>',
            info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.6" r="0.5" fill="currentColor"/>',
          }[tone] || '';
        },
        notifyCanEncrypt(t) { return t === 'bark' || t === 'webhook'; },
        genNotifyKey() {
          const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
          const rnd = (n) => { const a = new Uint32Array(n); crypto.getRandomValues(a); return [...a].map(x => abc[x % abc.length]).join(''); };
          const c = this.notifyState.edit.config;
          c.enc_key = rnd(32);
          if (this.notifyState.edit.type === 'bark') c.enc_iv = rnd(16);
        },
        notifyIcon(t) { return (window.AMP_NOTIFY_ICONS || {})[t] || { bg: '#475569', svg: '' }; },
        notifyTypeShort(t) {
          return { telegram: 'TG', discord: 'DC', slack: 'SL', teams: 'MT', googlechat: 'GC', mattermost: 'MM', matrix: 'MX', signal: 'SG',
                   ntfy: 'NT', gotify: 'GO', bark: 'BK', pushover: 'PO', pushbullet: 'PB', email: '@', apprise: 'AP', webhook: 'WH', webpush: 'WP' }[t] || '?';
        },
        notifyColor(t) {
          return { telegram: 'bg-sky-500', discord: 'bg-indigo-500', slack: 'bg-fuchsia-700', teams: 'bg-violet-600', googlechat: 'bg-green-600',
                   mattermost: 'bg-blue-700', matrix: 'bg-zinc-700', signal: 'bg-blue-500', ntfy: 'bg-emerald-600', gotify: 'bg-cyan-600',
                   bark: 'bg-orange-500', pushover: 'bg-sky-700', pushbullet: 'bg-teal-600', email: 'bg-rose-600', apprise: 'bg-amber-600',
                   webhook: 'bg-slate-600', webpush: 'bg-violet-600' }[t] || 'bg-slate-600';
        },

        // ---------------- Web Push (0.25) ----------------
        _wpEnv() {
          const w = this.wp, ua = navigator.userAgent || '';
          w.secure = !!window.isSecureContext;
          w.ios = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
          w.standalone = !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || window.navigator.standalone === true;
          w.supported = w.secure && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
          w.perm = ('Notification' in window) ? Notification.permission : 'unsupported';
          if (!w.name) {
            const dev = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android' : /Mac OS X/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'Device';
            const br = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : '';
            w.name = br ? `${dev} · ${br}` : dev;
          }
        },

        async _wpHash(text) {
          const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
          return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
        },

        async loadWebPush() {
          const w = this.wp;
          this._wpEnv();
          try {
            const res = await fetch('/api/notify/webpush');
            if (res.ok) { const d = await res.json(); w.publicKey = d.public_key; w.devices = d.devices || []; }
          } catch (_) {}
          w.thisEp = '';
          if (w.supported) {
            try {
              const reg = await navigator.serviceWorker.getRegistration('/');
              const sub = reg && await reg.pushManager.getSubscription();
              if (sub) w.thisEp = await this._wpHash(sub.endpoint);
            } catch (_) {}
          }
        },

        wpThisDevice() { return this.wp.devices.find(d => d.ep && d.ep === this.wp.thisEp) || null; },

        async enableWebPush() {
          const w = this.wp;
          w.busy = true; w.msg = '';
          try {
            const perm = await Notification.requestPermission();
            w.perm = perm;
            if (perm !== 'granted') throw new Error(this.t('wpDenied'));
            const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
            await navigator.serviceWorker.ready;
            const raw = atob(w.publicKey.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - w.publicKey.length % 4) % 4));
            const key = Uint8Array.from(raw, c => c.charCodeAt(0));
            let sub = await reg.pushManager.getSubscription();
            if (sub && sub.options && sub.options.applicationServerKey) {
              const old = new Uint8Array(sub.options.applicationServerKey);
              if (old.length !== key.length || old.some((v, i) => v !== key[i])) { await sub.unsubscribe(); sub = null; }  // khoá VAPID đã đổi
            }
            sub = sub || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
            const { res, data } = await this._postJson('/api/notify/webpush/subscribe', { subscription: sub.toJSON(), name: w.name });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            w.ok = true; w.msg = this.t('wpEnabled');
            await this.loadWebPush(); this.loadNotify();
          } catch (err) { w.ok = false; w.msg = err.message || String(err); }
          finally { w.busy = false; }
        },

        async disableWebPushHere() {
          const w = this.wp, mine = this.wpThisDevice();
          w.busy = true; w.msg = '';
          try {
            const reg = await navigator.serviceWorker.getRegistration('/');
            const sub = reg && await reg.pushManager.getSubscription();
            if (sub) await sub.unsubscribe();
            if (mine) await this._postJson('/api/notify/webpush/delete', { id: mine.id });
            w.ok = true; w.msg = this.t('wpDisabled');
            await this.loadWebPush();
          } catch (err) { w.ok = false; w.msg = err.message; }
          finally { w.busy = false; }
        },

        async testWebPush(dev = null) {
          const w = this.wp;
          w.busy = true; w.msg = '';
          try {
            const { res, data } = await this._postJson('/api/notify/webpush/test', { id: dev ? dev.id : '' });
            w.ok = res.ok && data.ok; w.msg = data.message || data.detail || '';
            await this.loadWebPush();
          } catch (err) { w.ok = false; w.msg = err.message; }
          finally { w.busy = false; }
        },

        confirmDeleteWebPush(dev) {
          this.askConfirm({
            tone: 'danger', title: this.t('wpDeleteTitle').replace('{d}', dev.name), message: this.t('wpDeleteMsg'), confirmLabel: this.t('delete'),
            onConfirm: async () => {
              const { res, data } = await this._postJson('/api/notify/webpush/delete', { id: dev.id });
              if (!res.ok) { this.showToast(data.detail || 'Failed'); return; }
              this.loadWebPush();
            }
          });
        },

        async loadNotify() {
          const n = this.notifyState;
          n.loading = true;
          try {
            const res = await fetch('/api/notify');
            if (res.ok) {
              const d = await res.json();
              n.channels = d.channels || []; n.events = d.events || []; n.critical = d.critical || [];
              n.settings = { ...n.settings, ...(d.settings || {}) };
              if (!n.channels.length) n.settings.lang = this.lang;  // chưa có kênh: tin nhắn theo ngôn ngữ giao diện
            }
          } catch (_) {}
          finally { n.loading = false; }
        },
        newNotifyChannel() {
          const n = this.notifyState;
          n.msg = '';
          n.edit = { id: '', type: 'telegram', name: '', enabled: true, private: false, events: [...n.events], config: { server: '', security: 'starttls' } };
        },
        editNotifyChannel(ch) {
          this.notifyState.msg = '';
          this.notifyState.edit = JSON.parse(JSON.stringify(ch));
        },
        async saveNotifyChannel(andTest) {
          const n = this.notifyState, e = n.edit;
          n.busy = true; n.msg = '';
          try {
            const payload = { ...e, name: e.name || this.notifyTypeLabel(e.type), ui_lang: this.lang };
            const { res, data } = await this._postJson('/api/notify/channels', payload);
            if (!res.ok) throw new Error(data.detail || 'Failed');
            n.edit = null;
            await this.loadNotify();
            n.ok = true; n.msg = this.t('notifySavedMsg');
            if (andTest) await this.testNotifyChannel({ id: data.id });
          } catch (err) { n.ok = false; n.msg = err.message; }
          finally { n.busy = false; }
        },
        async testNotifyChannel(ch) {
          const n = this.notifyState;
          n.testing = ch.id;
          try {
            const { data } = await this._postJson('/api/notify/test', { id: ch.id });
            n.ok = !!data.ok; n.msg = data.ok ? this.t('notifyTestOk') : this.t('notifyTestFail') + ' ' + (data.detail || data.detail || '');
            await this.loadNotify();
          } catch (err) { n.ok = false; n.msg = err.message; }
          finally { n.testing = ''; }
        },
        async toggleNotifyChannel(ch, on) {
          await this._postJson('/api/notify/channels', { ...ch, enabled: on });
          await this.loadNotify();
        },
        deleteNotifyChannel(ch) {
          this.askConfirm({
            tone: 'danger', title: this.t('notifyDeleteTitle').replace('{n}', ch.name), message: this.t('notifyDeleteMsg'),
            confirmLabel: this.t('delete'),
            onConfirm: async () => { await this._postJson('/api/notify/channels/delete', { id: ch.id }); await this.loadNotify(); }
          });
        },
        async saveNotifySettings() {
          const { res, data } = await this._postJson('/api/notify/settings', this.notifyState.settings);
          if (res.ok) { this.notifyState.settings = data.settings; this.showToast(this.t('notifySavedMsg')); }
        },

        // ---------------- Nguồn cập nhật & giới hạn API ----------------
        async loadApiStatus() {
          const a = this.apiStatus;
          a.loading = true;
          try {
            const res = await fetch('/api/system/api-status');
            if (res.ok) { const d = await res.json(); a.sources = d.sources || []; a.logins = d.logins || []; }
          } catch (_) {}
          finally { a.loading = false; }
        },

        apiTime(ts) {
          if (!ts) return '';
          return new Date(ts * 1000).toLocaleTimeString(this.lang === 'vi' ? 'vi-VN' : 'en-US', { hour: '2-digit', minute: '2-digit' });
        },

        async saveRegistryLogin() {
          const a = this.apiStatus, f = a.form;
          const registry = f.registry === 'other' ? f.custom.trim() : f.registry;
          a.busy = true; a.msg = '';
          try {
            const { res, data } = await this._postJson('/api/system/registry-logins', { registry, username: f.username, token: f.token });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            a.ok = true; a.msg = `${registry}: ${data.message || 'OK'}`;
            f.username = ''; f.token = ''; f.custom = '';
            await this.loadApiStatus();
          } catch (err) { a.ok = false; a.msg = err.message; }
          finally { a.busy = false; }
        },

        confirmDeleteLogin(lg) {
          this.askConfirm({
            tone: 'danger', title: this.t('loginDeleteTitle').replace('{r}', lg.registry),
            message: this.t('loginDeleteMsg'), confirmLabel: this.t('delete'),
            onConfirm: async () => {
              await this._postJson('/api/system/registry-logins/delete', { registry: lg.registry });
              await this.loadApiStatus();
            }
          });
        },

        async resumeSource(src) {
          await this._postJson('/api/system/api-status/resume', { source: src.source });
          await this.loadApiStatus();
        },

        async clearApiCache() {
          const { data } = await this._postJson('/api/system/api-cache/clear', {});
          this.showToast(this.t('apiCacheCleared').replace('{n}', data.cleared ?? 0));
          await this.loadApiStatus();
        },

        // Cài đặt chung chỉnh như bản nháp: thanh dưới cùng "N thay đổi · Huỷ · Lưu" (kiểu Cài đặt iOS)
        _settingsPayload(f = this.settingsForm) {
          return {
            check_interval_hours: Math.max(1, Math.min(168, parseInt(f.check_interval_hours, 10) || 6)),
            auto_update_enabled: !!f.auto_update_enabled,
            auto_update_time: f.auto_update_time || '03:30',
            prune_old_images: !!f.prune_old_images,
            auto_rollback: !!f.auto_rollback,
            health_wait_seconds: Math.max(10, Math.min(120, parseInt(f.health_wait_seconds, 10) || 25)),
            auto_prune_enabled: !!f.auto_prune_enabled,
            auto_prune_freq: f.auto_prune_freq || 'weekly',
            auto_prune_weekday: Number.isInteger(f.auto_prune_weekday) ? f.auto_prune_weekday : 6,
            auto_prune_time: f.auto_prune_time || '04:00',
            auto_prune_images: f.auto_prune_images || 'dangling',
            auto_prune_cache: !!f.auto_prune_cache,
            backup_before_update: !!f.backup_before_update,
            backup_max_mb: Math.max(50, Math.min(102400, parseInt(f.backup_max_mb, 10) || 2048)),
            backup_file_max_mb: Math.max(1, Math.min(10240, parseInt(f.backup_file_max_mb, 10) || 50)),
            backup_keep: Math.max(1, Math.min(20, parseInt(f.backup_keep, 10) || 3))
          };
        },
        _snapSettings() { this.settingsBase = JSON.parse(JSON.stringify(this.settingsForm)); },
        settingsChanges() { return this.serverSettingsChanges() + this.uiChanges(); },
        serverSettingsChanges() {
          if (!this.settingsBase) return 0;
          const now = this._settingsPayload(), base = this._settingsPayload(this.settingsBase);
          return Object.keys(now).filter(k => now[k] !== base[k]).length + ((this.settingsForm.github_token || '').trim() ? 1 : 0);
        },
        discardSettings() {
          if (this.settingsBase) this.settingsForm = JSON.parse(JSON.stringify(this.settingsBase));
          if (this.uiBase) { this.ui = { ...this.uiBase }; this.applyUi(); }
        },
        async saveSettings() {
          if (this.uiChanges()) {
            try { localStorage.setItem('amp_ui', JSON.stringify(this.ui)); } catch (_) {}
            this.uiBase = { ...this.ui };
            if (!this.serverSettingsChanges()) { this.showToast(this.lang === 'vi' ? 'Đã lưu giao diện' : 'Appearance saved'); return; }
          }
          const f = this.settingsForm;
          const payload = this._settingsPayload();
          if ((f.github_token || '').trim()) payload.github_token = f.github_token.trim();
          try {
            const { res, data } = await this._postJson('/api/settings', payload);
            if (!res.ok) throw new Error(data.detail || 'Failed to save settings');
            this.settingsForm = { ...data.settings, github_token: '' };
            this._snapSettings();
            this.showToast(this.lang === 'vi' ? 'Đã lưu cài đặt' : 'Settings saved');
          } catch (err) { this.showToast(err.message); }
        },

        // ---------------- Security: 2FA, password, activity log ----------------
        async loadSecurity() {
          this.security.loading = true;
          try {
            const res = await fetch('/api/auth/security');
            if (res.status === 401) { window.location.href = '/login'; return; }
            const data = await res.json();
            this.security.totp_enabled = !!data.totp_enabled;
            this.security.backup_codes_left = data.backup_codes_left || 0;
          } catch (err) { this.showToast(err.message); }
          finally { this.security.loading = false; }
          if (this.isAdmin()) { this.loadAudit(); if (!this.usersState.list.length) this.loadUsers(); }
        },

        async start2fa() {
          this.security.busy = true;
          try {
            const { res, data } = await this._postJson('/api/auth/2fa/setup', {});
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.security.setup = data;
            this.security.code = '';
          } catch (err) { this.showToast(err.message); }
          finally { this.security.busy = false; }
        },

        async enable2fa() {
          this.security.busy = true;
          try {
            const { res, data } = await this._postJson('/api/auth/2fa/enable', { code: this.security.code });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.security.backupCodes = data.backup_codes || [];
            this.security.setup = null;
            this.security.code = '';
            await this.loadSecurity();
            this.showToast(this.t('tfaEnabledToast'));
          } catch (err) { this.showToast(err.message); }
          finally { this.security.busy = false; }
        },

        async disable2fa() {
          this.security.busy = true;
          try {
            const { res, data } = await this._postJson('/api/auth/2fa/disable', { password: this.security.disablePw, code: this.security.disableCode });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.security.disablePw = ''; this.security.disableCode = ''; this.security.backupCodes = [];
            await this.loadSecurity();
            this.showToast(this.t('tfaDisabledToast'));
          } catch (err) { this.showToast(err.message); }
          finally { this.security.busy = false; }
        },

        async regenBackupCodes() {
          this.security.busy = true;
          try {
            const { res, data } = await this._postJson('/api/auth/2fa/backup-codes', { code: this.security.regenCode });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.security.backupCodes = data.backup_codes || [];
            this.security.regenCode = '';
            await this.loadSecurity();
          } catch (err) { this.showToast(err.message); }
          finally { this.security.busy = false; }
        },

        copyText(text) {
          // navigator.clipboard chỉ có trên HTTPS / localhost; truy cập bằng http://IP trong mạng nhà -> dùng cách cũ
          const fallback = () => {
            const ta = document.createElement('textarea');
            ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, text.length);
            let ok = false; try { ok = document.execCommand('copy'); } catch (_) {}
            ta.remove();
            this.showToast(ok ? this.t('copied') : this.t('copyManual'));
          };
          if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(() => this.showToast(this.t('copied')), fallback);
          } else fallback();
        },

        async changePassword() {
          const f = this.pwForm;
          if (f.next !== f.confirm) { this.showToast(this.t('pwMismatch')); return; }
          if ((f.next || '').length < 8) { this.showToast(this.t('pwTooShort')); return; }
          f.busy = true;
          try {
            const { res, data } = await this._postJson('/api/auth/password', { current_password: f.current, new_password: f.next });
            if (!res.ok) throw new Error(data.detail || 'Failed');
            this.pwForm = { current: '', next: '', confirm: '', busy: false };
            this.showToast(this.t('pwChanged'));
            this.loadAudit();
          } catch (err) { this.showToast(err.message); }
          finally { this.pwForm.busy = false; }
        },

        async loadAudit() {
          try {
            if (!this.isAdmin()) return;
            const q = this.auditUser ? `&user=${encodeURIComponent(this.auditUser)}` : '';
            const res = await fetch('/api/audit?limit=150' + q);
            if (!res.ok) return;
            const data = await res.json();
            this.auditItems = data.items || [];
          } catch (_) {}
        },

        formatTs(epoch) {
          if (!epoch) return '';
          return new Date(epoch * 1000).toLocaleString(this.lang === 'vi' ? 'vi-VN' : 'en-US', { dateStyle: 'short', timeStyle: 'short' });
        },

        utcToLocal(ts) {
          if (!ts) return '';
          const d = new Date(String(ts).replace(' ', 'T') + (String(ts).endsWith('Z') ? '' : 'Z'));
          return isNaN(d) ? ts : d.toLocaleString(this.lang === 'vi' ? 'vi-VN' : 'en-US', { dateStyle: 'short', timeStyle: 'short' });
        },

        actionLabel(a) {
          const key = 'act_' + a;
          const v = this.t(key);
          return v === key ? a : v;
        },

        // ---------------- App data backups ----------------
        async loadBackups() {
          this.backupsState.loading = true;
          try {
            const res = await fetch('/api/backups');
            if (res.ok) this.backupsState.items = (await res.json()).items || [];
          } catch (_) {}
          finally { this.backupsState.loading = false; }
        },

        confirmRestoreBackup(b) {
          this.askConfirm({
            tone: 'danger', title: this.t('restoreBackupTitle'),
            message: `${b.app} • ${b.file} — ${this.t('restoreBackupMsg')}`,
            confirmLabel: this.t('restore'), onConfirm: () => this.restoreBackup(b)
          });
        },

        // Nút Khôi phục trên thẻ app: chọn bản muốn khôi phục (mặc định bản mới nhất)
        confirmRestoreApp(app) {
          const items = app.backups?.length ? app.backups : (app.latest_backup ? [app.latest_backup] : []);
          if (!items.length) return;
          this.restorePicker = { open: true, app, items, selected: items[0].file, server: null };
        },

        // Máy phụ (0.21): lấy danh sách bản sao lưu của app trên máy đó rồi mở cùng cửa sổ chọn bản
        async confirmRemoteRestore(app) {
          const s = this.currentServerOf(app), r = this.remote;
          r.busy = this.rkey(app);
          try {
            const res = await fetch(`/api/servers/${s.id}/backups?app_name=${encodeURIComponent(app.name)}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Failed');
            const items = data.items || [];
            if (!items.length) { this.showToast(this.t('svNoBackups').replace('{app}', app.title)); return; }
            this.restorePicker = { open: true, app, items, selected: items[0].file, server: s };
          } catch (err) { this.showToast(err.message); }
          finally { r.busy = ''; }
        },

        runRestorePicker() {
          const p = this.restorePicker;
          const b = p.items.find(x => x.file === p.selected) || p.items[0];
          p.open = false;
          if (b) this.restoreBackup(b, p.server);
        },

        // Khôi phục có cửa sổ tiến trình: đang chạy (đếm giây) -> kết quả + các bước đã làm
        async restoreBackup(b, server = null) {
          const app = server ? this.restorePicker.app : this.apps.find(a => a.name === b.app);
          if (this.restoreRun.timer) clearInterval(this.restoreRun.timer);
          this.restoreRun = { open: true, running: true, title: (server ? server.name + ' · ' : '') + (app?.title || b.app), version: b.version || '', run: app?.manage === 'run', status: '', message: '', log: [], elapsed: 0, timer: null };
          this.restoreRun.timer = setInterval(() => { this.restoreRun.elapsed += 1; }, 1000);
          this.backupsState.busyFile = b.file;
          try {
            const url = server ? `/api/servers/${server.id}/backups/restore` : '/api/backups/restore';
            const { res, data } = await this._postJson(url, { app: b.app, file: b.file });
            this.restoreRun.log = data.log || [];
            if (!res.ok) {
              this.restoreRun.status = 'error';
              this.restoreRun.message = data.detail || 'Restore failed';
            } else {
              this.restoreRun.status = data.warning ? 'warning' : 'success';
              this.restoreRun.message = data.warning || data.message || 'OK';
            }
            if (server) this.reloadRemote(); else this.loadApps();
            if (this.settingsModal.open) this.loadBackups();
          } catch (err) {
            this.restoreRun.status = 'error';
            this.restoreRun.message = err.message;
          } finally {
            clearInterval(this.restoreRun.timer);
            this.restoreRun.timer = null;
            this.restoreRun.running = false;
            this.backupsState.busyFile = '';
          }
        },

        confirmDeleteBackup(b) {
          this.askConfirm({
            tone: 'danger', title: this.t('deleteBackupTitle'), message: `${b.app} • ${b.file}`,
            confirmLabel: this.t('delete'), onConfirm: () => this.deleteBackup(b)
          });
        },

        async deleteBackup(b) {
          try {
            const { res, data } = await this._postJson('/api/backups/delete', { app: b.app, file: b.file });
            if (!res.ok) throw new Error(data.detail || 'Delete failed');
            await this.loadBackups();
          } catch (err) { this.showToast(err.message); }
        },

        // ---------------- Resource history (24h charts) ----------------
        async toggleHistory(name) {
          const key = name || '__total__';
          if (key === '__total__') this.histTotalOpen = !this.histTotalOpen;
          else this.histOpen = { ...this.histOpen, [key]: !this.histOpen[key] };
          const open = key === '__total__' ? this.histTotalOpen : this.histOpen[key];
          if (!open) return;
          try {
            const res = await fetch(`/api/system/history?hours=24&container=${encodeURIComponent(name || '')}`);
            if (!res.ok) return;
            const data = await res.json();
            this.histData = { ...this.histData, [key]: data.points || [] };
          } catch (_) {}
        },

        sparkPoints(points, field, w = 300, h = 56) {
          if (!points || points.length < 2) return '';
          const vals = points.map(p => Number(p[field]) || 0);
          const t0 = points[0].ts, t1 = points[points.length - 1].ts || t0 + 1;
          const max = Math.max(...vals, field === 'cpu_pct' ? 5 : 1);
          return points.map((p, i) => {
            const x = ((p.ts - t0) / Math.max(1, t1 - t0)) * w;
            const y = h - 2 - (vals[i] / max) * (h - 6);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
          }).join(' ');
        },

        histStats(points, field) {
          if (!points || !points.length) return { avg: 0, max: 0 };
          const vals = points.map(p => Number(p[field]) || 0);
          return { avg: vals.reduce((a, b) => a + b, 0) / vals.length, max: Math.max(...vals) };
        },

        async logout() {
          try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
          window.location.href = '/login';
        }
      };
    }
