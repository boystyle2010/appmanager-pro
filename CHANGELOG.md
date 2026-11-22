# Changelog

## 0.5.1

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.5.0` ➡️ `v0.5.1`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12.16`
- **Docker CLI:** `docker 27.5.1`
- **Core Python Stack:** `FastAPI 0.115.14` • `Uvicorn 0.34.3` • `Docker SDK 7.2.0` • `ruamel.yaml 0.18.17` • `Argon2 23.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** Alpine.js `3.14.8` ➡️ `3.17.5` • Tailwind CSS `3.4.17` ➡️ `3.4.19` • marked `15.0.6` ➡️ `15.0.12` • DOMPurify `3.2.3` ➡️ `3.4.18`

### 🚀 What's Changed

- Upgraded **Alpine.js** to `3.17.5`.
- Upgraded **Tailwind CSS** to `3.4.19`.
- Upgraded **marked** to `15.0.12`.
- Upgraded **DOMPurify** to `3.4.18`.
- First stable release 🎉
- Two-factor authentication (TOTP) with QR setup and one-time backup codes
- Change password from Settings → Security (signs out other devices)
- Activity log: sign-ins, failed attempts, updates, uninstalls, compose edits, cleanups
- Login lockout can no longer be bypassed with fake X-Forwarded-For headers; lockout survives restarts (`TRUSTED_PROXIES`)
- Security headers (CSP, clickjacking protection) and Origin checks on WebSockets
- Optional app data backup before each update, with one-click restore
- 24-hour CPU/RAM charts in Task Manager
- Trivy vulnerability scan for every image build
- CSRF protection: API writes and WebSockets must come from the app's own page
- Update checks use HEAD requests first, so they no longer use up the Docker Hub pull limit
- Failed compose edits now restart the app with the previous file instead of leaving it stopped
- Health check after updates ignores restarts that happened before the update (no more false rollbacks)
- Only one update per app can run at a time
- Live Logs no longer leak connections when closed on quiet containers
- Backup restore keeps file permissions and owners
- Daily CI runs only rebuild the image when something changed

## 0.5.3

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.5.2` ➡️ `v0.5.3`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12` ➡️ `python 3.12.16`
- **Docker CLI:** `docker 27` ➡️ `docker 27.5.1`
- **Core Python Stack:** FastAPI `0.115.6` ➡️ `0.115.14` • Uvicorn `0.34.0` ➡️ `0.34.3` • Docker SDK `7.1.0` ➡️ `7.2.0` • ruamel.yaml `0.18.6` ➡️ `0.18.17` • `Argon2 23.1.0` • `itsdangerous 2.2.0` • Jinja2 `3.1.5` ➡️ `3.1.6` • python-multipart `0.0.20` ➡️ `0.0.34` • `HTTPX 0.28.1` • APScheduler `3.10.4` ➡️ `3.11.3` • segno `1.6.1` ➡️ `1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • `Tailwind CSS 3.4.19` • `marked 15.0.12` • `DOMPurify 3.4.18`

### 🚀 What's Changed

- Upgraded **Python Base Image** to `3.12.16`.
- Upgraded **Docker CLI** to `27.5.1`.
- Upgraded **FastAPI** to `0.115.14`.
- Upgraded **Uvicorn** to `0.34.3`.
- Upgraded **Docker SDK** to `7.2.0`.
- Upgraded **ruamel.yaml** to `0.18.17`.
- Upgraded **Jinja2** to `3.1.6`.
- Upgraded **python-multipart** to `0.0.34`.
- Upgraded **APScheduler** to `3.11.3`.
- Upgraded **segno** to `1.6.6`.
- Add files via upload
- Update release.yml
- Create LICENSE
- Create README.md

## 0.5.2

*Released: 2026-11-21*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.5.1` ➡️ `v0.5.2`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12.16`
- **Docker CLI:** `docker 27.5.1`
- **Core Python Stack:** `FastAPI 0.115.14` • `Uvicorn 0.34.3` • `Docker SDK 7.2.0` • `ruamel.yaml 0.18.17` • `Argon2 23.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3`
- **Frontend Libraries:** Alpine.js `3.14.8` ➡️ `3.17.5` • Tailwind CSS `3.4.17` ➡️ `3.4.19` • marked `15.0.6` ➡️ `15.0.12` • DOMPurify `3.2.3` ➡️ `3.4.18`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Version Tag:** `ghcr.io/boystyle2010/appmanager-pro:0.5.2` (`sha256:198a20426b24cc0b0b26cd45f145e23c0c479fb57b153933e49682d010e64dbc`)
- **Latest Tag:** `ghcr.io/boystyle2010/appmanager-pro:latest`
- **Provenance:** signed by GitHub — verify with `gh attestation verify oci://ghcr.io/boystyle2010/appmanager-pro@sha256:198a20426b24cc0b0b26cd45f145e23c0c479fb57b153933e49682d010e64dbc -R boystyle2010/appmanager-pro`

### 🚀 What's Changed

- Upgraded **Alpine.js** to `3.17.5`.
- Upgraded **Tailwind CSS** to `3.4.19`.
- Upgraded **marked** to `15.0.12`.
- Upgraded **DOMPurify** to `3.4.18`.
- Update fetch_vendor.py
- Update auth.html
- Update index.html

## 0.5.1

*Released: 2026-11-21*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.5.0` ➡️ `v0.5.1`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12` ➡️ `python 3.12.16`
- **Docker CLI:** `docker 27` ➡️ `docker 27.5.1`
- **Core Python Stack:** FastAPI `0.115.6` ➡️ `0.115.14` • Uvicorn `0.34.0` ➡️ `0.34.3` • Docker SDK `7.1.0` ➡️ `7.2.0` • ruamel.yaml `0.18.6` ➡️ `0.18.17` • `Argon2 23.1.0` • `itsdangerous 2.2.0` • Jinja2 `3.1.5` ➡️ `3.1.6` • python-multipart `0.0.20` ➡️ `0.0.34` • `HTTPX 0.28.1` • APScheduler `3.10.4` ➡️ `3.11.3`
- **Frontend Libraries:** Alpine.js `3.14.8` ➡️ `3.17.5` • Tailwind CSS `3.4.17` ➡️ `3.4.19` • marked `15.0.6` ➡️ `15.0.12` • DOMPurify `3.2.3` ➡️ `3.4.18`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Version Tag:** `ghcr.io/boystyle2010/appmanager-pro:0.5.1` (`sha256:59b772160c4a7baf34743afd63938a772233b82245ade9f917cf7377a29f3d8c`)
- **Latest Tag:** `ghcr.io/boystyle2010/appmanager-pro:latest`
- **Provenance:** signed by GitHub — verify with `gh attestation verify oci://ghcr.io/boystyle2010/appmanager-pro@sha256:59b772160c4a7baf34743afd63938a772233b82245ade9f917cf7377a29f3d8c -R boystyle2010/appmanager-pro`

### 🚀 What's Changed

- Upgraded **Python Base Image** to `3.12.16`.
- Upgraded **Docker CLI** to `27.5.1`.
- Upgraded **FastAPI** to `0.115.14`.
- Upgraded **Uvicorn** to `0.34.3`.
- Upgraded **Docker SDK** to `7.2.0`.
- Upgraded **ruamel.yaml** to `0.18.17`.
- Upgraded **Jinja2** to `3.1.6`.
- Upgraded **python-multipart** to `0.0.34`.
- Upgraded **APScheduler** to `3.11.3`.
- Upgraded **Alpine.js** to `3.17.5`.
- Upgraded **Tailwind CSS** to `3.4.19`.
- Upgraded **marked** to `15.0.12`.
- Upgraded **DOMPurify** to `3.4.18`.
- Add files via upload
- Add files via upload
- Add files via upload
- Add files via upload
- Add files via upload
- Add files via upload
- Add files via upload
- Update release.yml
- Delete release-please-config.json
- Delete .release-please-manifest.json
- Delete .github/workflows/vendor-updates.yml
- Delete .github/dependabot.yml

## v0.5.0 (Phase 5 - Safe Updates, Scheduled Cleanup & Self-hosted UI)
- **Auto-rollback:** after an update the new container is health-checked (crash/restart loop/unhealthy); on failure the previous version is restored automatically (compose backup or previous image re-tag). Old images are only pruned after the new version is healthy. Toggle + check time in Settings.
- **Scheduled SSD cleanup:** daily/weekly/monthly cleanup of images and build cache with a live estimate, next/last run info and history entries. Containers and volumes are never cleaned automatically.
- **Changelog:** cloudflared (and similar) now read real notes from `RELEASE_NOTES` instead of SHA256-only releases; layout fixes (fixed frames, horizontal scroll inside changelog).
- **Self-hosted UI libraries:** Tailwind, Alpine.js, marked, DOMPurify and fonts are downloaded at image build (`scripts/fetch_vendor.py`) with automatic CDN fallback.
- **Code structure:** dashboard JavaScript moved out of `index.html` into `static/js/app.js` and translations into `static/js/i18n.js`.
- **CI/CD (fully automatic):** one GitHub Actions workflow checks for new base images / Python packages / frontend libraries every day, commits the updates (signed by GitHub), writes this changelog, builds & signs the multi-arch image and publishes the GitHub Release.

## v0.4.0 (Phase 4 - Task Manager, Storage Cleanup & Deploy)
- **Task Manager:** Live CPU / RAM / Network / PIDs per container over WebSocket (`/ws/task-manager`), sorted by load.
- **Storage / SSD cleanup:** Docker disk usage analysis with selective prune (dangling/unused images, build cache, stopped containers, volumes).
- **+ Deploy New App:** Paste YAML or Quick Form UI, validate, and deploy with live pull/up logs.
- Added `kill` container action and fixed missing dashboard handlers (logs, update, batch update, compose editor, uninstall, settings, logout).

## v0.3.0 (Phase 3 - Visual Compose UI, Rollback, Smart Uninstall & Option 1 Liquid Glass)
- **Home Assistant-style Compose Editor:** Added seamless two-way **Visual UI ↔ YAML Code** editor with lossless `ruamel.yaml` preservation, auto-detected boolean toggles for `true`/`false` environment variables, Ports/Volumes/CasaOS card editors, syntax validation (`docker compose config -q`), and timestamped **1-Click Rollback**.
- **Smart Layered Uninstall:** Added 4-level uninstall (Container, CasaOS compose folder, Docker image, and protected `/DATA/AppData` deletion requiring container-name confirmation).
- **Skip Version:** Added Skip / Unskip version toggle in the Update & Changelog modal.
- **Refined Liquid Glass UI (Option 1):** Simplified card footer to Primary CTA + `•••` iOS Glass Action Sheet (with 2-tap safe Stop), brighter icon frames for dark logos, self-app logo/version auto-detection, universal clickable chevrons, and aligned Settings inputs.

## v0.2.0 (Phase 2 - Real Updates, Changelog & Auto-Update)
- Fixed iPhone Safari top/bottom dark seams with seamless edge blending, `100lvh` full-height coverage, and PWA `manifest.json`.
- Added asynchronous **Registry v2 SHA256 Digest** checker (Docker Hub, GHCR, LSCR, Quay) with real remote OCI version detection.
- Added silent background update scanning and instant notification banner on page load.
- Added **App Update Detail Modal** displaying app icon, name, current vs. server version, rendered **GitHub Releases Changelog**, custom GitHub repo override, per-app **Auto-Update** toggle, and real-time **WebSocket Update Terminal**.
- Added configurable **Auto-Update Scheduler**, automatic old-image pruning, self-update support, and **Update History** log.

## v0.1.0 (Phase 1 - Foundation)
- Initial release of **AppManager Pro** (multi-arch `amd64` / `arm64`).
- Added secure First-Run Admin setup and Login screen with Argon2id hashing, Signed HttpOnly Cookies, and IP brute-force protection (`CF-Connecting-IP` / `X-Forwarded-For` aware).
- Built Liquid Glass UI with Dark/Light modes, EN/VN language switch, and mobile responsiveness.
- Added instant container discovery with automatic CasaOS `x-casaos` metadata extraction (icon, title, WebUI port) and standalone Docker fallback.
- Added Start, Stop, Restart actions and real-time WebSocket Live Logs viewer.
