# Changelog

## v0.5.0 (Phase 5 - Safe Updates, Scheduled Cleanup & Self-hosted UI)
- **Auto-rollback:** after an update the new container is health-checked (crash/restart loop/unhealthy); on failure the previous version is restored automatically (compose backup or previous image re-tag). Old images are only pruned after the new version is healthy. Toggle + check time in Settings.
- **Scheduled SSD cleanup:** daily/weekly/monthly cleanup of images and build cache with a live estimate, next/last run info and history entries. Containers and volumes are never cleaned automatically.
- **Changelog:** cloudflared (and similar) now read real notes from `RELEASE_NOTES` instead of SHA256-only releases; layout fixes (fixed frames, horizontal scroll inside changelog).
- **Self-hosted UI libraries:** Tailwind, Alpine.js, marked, DOMPurify and fonts are downloaded at image build (`scripts/fetch_vendor.py`) with automatic CDN fallback.
- **Code structure:** dashboard JavaScript moved out of `index.html` into `static/js/app.js` and translations into `static/js/i18n.js`.

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
