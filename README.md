<div align="center">

<img src="assets/icon.png" alt="AppManager Pro" width="120" />

# AppManager Pro

**Fast, glassmorphic Docker & CasaOS app manager — real registry-digest update checks, changelog viewer, safe Compose editor with rollback, Task Manager and SSD cleanup.**

[![Build & Release](https://github.com/boystyle2010/appmanager-pro/actions/workflows/release.yml/badge.svg)](https://github.com/boystyle2010/appmanager-pro/actions/workflows/release.yml)
[![Latest Release](https://img.shields.io/github/v/release/boystyle2010/appmanager-pro?label=release&color=2ea043)](https://github.com/boystyle2010/appmanager-pro/releases/latest)
[![Release Date](https://img.shields.io/github/release-date/boystyle2010/appmanager-pro?label=released)](https://github.com/boystyle2010/appmanager-pro/releases/latest)
[![GHCR](https://img.shields.io/badge/ghcr.io-appmanager--pro-2496ED?logo=docker&logoColor=white)](https://github.com/boystyle2010/appmanager-pro/pkgs/container/appmanager-pro)
[![Platforms](https://img.shields.io/badge/platform-linux%2Famd64%20%7C%20linux%2Farm64-informational?logo=linux&logoColor=white)](#-installation)
[![Signed](https://img.shields.io/badge/build%20provenance-signed%20by%20GitHub-6e40c9?logo=githubactions&logoColor=white)](https://github.com/boystyle2010/appmanager-pro/attestations)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Alpine.js](https://img.shields.io/badge/Alpine.js-3-8BC0D0?logo=alpinedotjs&logoColor=white)](https://alpinejs.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-3-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![CasaOS](https://img.shields.io/badge/CasaOS-ready-0A84FF)](https://casaos.io/)
[![License: MIT](https://img.shields.io/github/license/boystyle2010/appmanager-pro?color=yellow)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/boystyle2010/appmanager-pro)](https://github.com/boystyle2010/appmanager-pro/commits/main)
[![Stars](https://img.shields.io/github/stars/boystyle2010/appmanager-pro?style=social)](https://github.com/boystyle2010/appmanager-pro/stargazers)

[Features](#-features) • [Installation](#-installation) • [Configuration](#%EF%B8%8F-configuration) • [Usage](#-usage) • [Automation](#-automated-builds--releases) • [API](#-api-reference) • [FAQ](#-troubleshooting)

</div>

---

## 📖 Overview

AppManager Pro is a self-hosted web dashboard for managing the Docker containers on a home server — especially servers running **CasaOS**. It finds the `docker-compose.yml` behind each app, checks the registry for newer images by comparing **real digests** (not just tags), shows the upstream changelog, and updates apps safely with automatic backup and **automatic rollback** if the new version fails.

It runs as a single container, ships a mobile-first "liquid glass" UI in English and Vietnamese, and needs nothing more than access to the Docker socket.

## ✨ Features

### Updates & changelogs
- **Real update detection** — compares the local image digest with the registry digest (Docker Hub, GHCR, and other OCI registries), so `latest`-tagged apps are detected correctly.
- **Pinned-tag bumping** — apps pinned to a version (e.g. `cloudflare/cloudflared:2026.10.7`) are bumped to the new tag in `docker-compose.yml`, with an automatic `.bak` backup.
- **Changelog viewer** — reads GitHub release notes, falls back to `CHANGELOG.md`, `RELEASE_NOTES`, `CHANGES.md` and recent commits; checksum-only releases (SHA256 lists) are cleaned up automatically. Custom repo override per app.
- **One-click & batch updates** — update a single app or *Update All* with live streaming logs; AppManager Pro updates itself last via a detached helper.
- **Auto-update schedule** — opt-in per app, runs daily at the time you choose.
- **Skip version** — hide a specific release until the next one.
- **Auto-rollback** — after an update the new container is health-checked (crash, restart loop, `unhealthy`); if it fails, the previous version is restored automatically. Old images are pruned only once the new version is healthy.

### App management
- **Start / Stop / Restart / Kill** and **live logs** for every container.
- **Compose editor** — two-way *Visual UI ↔ YAML* editor (lossless `ruamel.yaml`), validation with `docker compose config`, timestamped backups and **one-click rollback**.
- **Deploy new apps** — paste YAML or use the quick form, validate, then deploy with live pull/up logs.
- **Smart uninstall** — four levels: container, CasaOS compose folder, Docker image, and (with confirmation) app data in `/DATA/AppData`.

### System
- **Task Manager** — live CPU, RAM, network and PIDs per container over WebSocket, plus **24-hour CPU/RAM charts** (sampled every 5 minutes, kept 7 days).
- **Storage / SSD cleanup** — disk-usage breakdown (images, build cache, containers, volumes), selective prune with size estimate.
- **Scheduled SSD cleanup** — daily / weekly / monthly cleanup of images and build cache (containers and volumes are never removed automatically).
- **Update history** — every update, rollback and cleanup is logged.
- **App data backups** — optional `.tar.gz` backup of the app's `/DATA/AppData` folder before each update, with size limit, retention and one-click restore.

### Security & UI
- **Admin account** with Argon2id password hashing, signed session cookies (`HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS) and **IP lockout** after 5 failed logins (15 minutes, persisted across restarts). Proxy headers are only trusted from configured proxies, so the lockout cannot be bypassed with fake IPs.
- **Two-factor authentication (TOTP)** with QR setup and one-time backup codes; works with Google Authenticator, 1Password, iOS Passwords and others.
- **Password change** from the UI (signs out other devices).
- **Activity log** — sign-ins, failed attempts, updates, uninstalls, compose edits, cleanups and settings changes with user and IP.
- **Hardened HTTP** — Content-Security-Policy, clickjacking protection, `nosniff`, and Origin checks on every API write and WebSocket (CSRF protection).
- **Glassmorphic, mobile-first UI**, dark/light theme, English & Vietnamese, installable as a PWA.
- **No runtime CDN dependency** — Tailwind, Alpine.js, marked, DOMPurify and fonts are bundled into the image at build time, with automatic CDN fallback.

## 🚀 Installation

### Requirements
- A Linux host with Docker Engine and Docker Compose v2 (`amd64` or `arm64`)
- Optional: CasaOS (apps in `/var/lib/casaos/apps`, data in `/DATA/AppData`)

### Docker Compose (recommended)

Create `/DATA/AppData/appmanager-pro/docker-compose.yml`:

```yaml
name: appmanager-pro

services:
  appmanager-pro:
    image: ghcr.io/boystyle2010/appmanager-pro:latest
    container_name: appmanager-pro
    restart: unless-stopped
    ports:
      - "8098:8000"
    environment:
      - TZ=America/Denver
      - CASAOS_APPS_DIR=/var/lib/casaos/apps
      - APPDATA_DIR=/DATA/AppData
      - RESET_AUTH=false
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/casaos/apps:/var/lib/casaos/apps
      - /DATA/AppData:/DATA/AppData
      - /DATA/AppData/appmanager-pro/data:/app/data
```

Then start it:

```bash
cd /DATA/AppData/appmanager-pro
docker compose up -d
```

Open **`http://<server-ip>:8098`** and create the admin account on first launch.

> **Note:** the container name must stay `appmanager-pro` so the app can recognise and update itself.

### CasaOS
Import the same compose file through **CasaOS → App Store → Custom Install → Import**. The repository's compose file already contains the `x-casaos` metadata (icon, port, descriptions).

### Updating
Use the **Update App** button on the AppManager Pro card, or manually:

```bash
cd /DATA/AppData/appmanager-pro
docker compose pull && docker compose up -d
```

## ⚙️ Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `TZ` | `UTC` | Time zone used for schedules and logs (e.g. `Asia/Ho_Chi_Minh`). |
| `CASAOS_APPS_DIR` | `/var/lib/casaos/apps` | Where CasaOS stores app compose files. |
| `APPDATA_DIR` | `/DATA/AppData` | Root folder for app data (used by uninstall & compose discovery). |
| `APP_DATA_DIR` | `/app/data` | AppManager Pro's own database & backups (inside the container). |
| `RESET_AUTH` | `false` | Set to `true` and restart to reset the admin account (also removes 2FA); set back to `false` afterwards. |
| `TRUSTED_PROXIES` | `127.0.0.0/8,::1/128,172.16.0.0/12` | Comma-separated IPs/CIDRs of reverse proxies whose `X-Forwarded-For` / `CF-Connecting-IP` headers are trusted. The default covers proxies on the same host (e.g. cloudflared, Nginx Proxy Manager in Docker). Add your proxy's IP if it runs on another machine. |
| `TRUST_CF_CONNECTING_IP` | `false` | Set to `true` only if requests reach the app exclusively through Cloudflare (Tunnel); then the `CF-Connecting-IP` header is used as the client IP. |
| `ALLOWED_ORIGINS` | — | Extra hostnames allowed to call the API/WebSockets when your reverse proxy rewrites the `Host` header (e.g. `am.example.com`). |

### Volumes

| Host path | Container path | Purpose |
|---|---|---|
| `/var/run/docker.sock` | `/var/run/docker.sock` | Docker API access (required). |
| `/var/lib/casaos/apps` | same | Read/edit CasaOS compose files. |
| `/DATA/AppData` | same | App data folders and compose files outside CasaOS. |
| `/DATA/AppData/appmanager-pro/data` | `/app/data` | SQLite database, settings, compose backups. |

### In-app settings (⚙️ Settings)

| Setting | Default | Description |
|---|---|---|
| Silent check interval | 6 h | How often registries are checked in the background. |
| Scheduled auto-update | off | Daily time to update apps that have *Auto-Update* enabled. |
| Auto-clean old images | on | Remove the previous image after a successful update. |
| Auto-rollback | on | Restore the previous version if the update fails the health check. |
| Health check time | 25 s | How long the new container is watched (10–120 s). |
| Scheduled SSD cleanup | off | Daily / weekly / monthly cleanup of images & build cache. |
| Back up app data before updates | off | Archive `/DATA/AppData/<app>` before each update (max size & number kept are configurable). |
| GitHub token | — | Optional; raises the GitHub API limit (60 → 5,000 requests/hour) and allows private repos. |
| Security tab | — | Two-factor authentication, password change, activity log. |

## 🧭 Usage

| Where | What you can do |
|---|---|
| **Dashboard** | Search, sort (smart, name A–Z / Z–A, running or stopped first), filter (All / Updates / Running / Stopped), *Update All*, re-check registries. |
| **App card → version row** | Open update details: changelog, auto-update toggle, skip version, *Update App*. |
| **App card → ⋯** | Logs, start/stop/restart, edit compose, uninstall. |
| **Header → activity icon** | Task Manager (live resources, restart/stop/kill). |
| **Header → ⚙️** | General settings, Storage / SSD cleanup & app data backups, Security (2FA, password, activity log), update history. |
| **Task Manager → 24h** | CPU/RAM charts for all containers or a single one. |
| **＋ button** | Deploy a new app from YAML or the quick form. |

## 🤖 Automated builds & releases

One GitHub Actions workflow ([`release.yml`](.github/workflows/release.yml)) runs **every day**, on **every push to `main`**, and **on demand**:

1. **Checks the source** — Python syntax, internal imports, Jinja templates, static files and JavaScript ([`scripts/check_project.py`](scripts/check_project.py)).
2. **Looks for updates** ([`scripts/auto_update.py`](scripts/auto_update.py)) of the Python base image, Docker CLI, Python packages and frontend libraries — **always the newest stable release, including new major versions** (Tailwind CSS stays on v3, whose in-browser build the UI relies on).
3. **Verifies** the result by building the real Docker image and starting the app inside it ([`scripts/verify.sh`](scripts/verify.sh)). If the newest versions fail, it automatically retries with same-major updates only and notes the held-back upgrades in the changelog. The result is **committed via the GitHub API**, so commits are signed by GitHub (*Verified*).
4. **Builds** the multi-arch image (`linux/amd64`, `linux/arm64`), pushes it to GHCR and **signs it** with a GitHub build-provenance attestation.
5. **Publishes a GitHub Release** whose notes come from `CHANGELOG.md` (Component & Version Matrix, Package Integrity, What's Changed).

Image tags: `latest`, `X.Y.Z` (on release) and `build-<commit>`.

Verify an image:

```bash
gh attestation verify oci://ghcr.io/boystyle2010/appmanager-pro:latest -R boystyle2010/appmanager-pro
```

6. **Scans the image with Trivy** (critical/high, fixable only) and adds the result to the release notes.

**Manual releases:** *Actions → Auto Update, Build & Release → Run workflow* — tick `force_release`, or type a version such as `1.0.0` in `version`.
The changelog only lists **component updates** (base image, Python packages, frontend libraries) — editing or uploading files on GitHub does not add entries. To add your own notes to the next release, write bullet lines in `RELEASE_NOTES_NEXT.md`; they are moved into the changelog automatically and the file is cleared.

## 🗂️ Project structure

```
appmanager-pro/
├── .github/workflows/release.yml   # daily update check, build, sign & release
├── Dockerfile                      # python:3.12-slim + Docker CLI & Compose v2
├── requirements.txt
├── CHANGELOG.md                    # maintained automatically
├── LICENSE                         # MIT
├── assets/                         # icon
├── scripts/
│   ├── auto_update.py              # finds new versions & writes the changelog
│   ├── check_project.py            # pre-build source checks
│   ├── verify.sh                   # builds the image & starts the app before committing updates
│   ├── fetch_vendor.py             # bundles UI libraries & fonts at build time
│   └── signed_commit.py            # commits through the GitHub API (signed)
└── app/
    ├── main.py                     # FastAPI app: pages, REST API, WebSockets
    ├── core/
    │   ├── app_backup.py           # app data backups & restore
    │   ├── auth.py                 # Argon2 login, sessions, lockout, TOTP 2FA
    │   ├── compose_manager.py      # compose discovery, editor, backups, uninstall
    │   ├── database.py             # SQLite settings, cache & history
    │   ├── docker_client.py        # container listing & actions
    │   ├── registry_checker.py     # digest checks & changelog fetching
    │   ├── scheduler.py            # background checks, auto-update, SSD cleanup
    │   ├── system_monitor.py       # Task Manager metrics
    │   ├── system_prune.py         # disk usage & prune
    │   └── updater.py              # pull/recreate, health check, rollback
    ├── static/
    │   ├── css/glass.css
    │   └── js/{app.js,i18n.js}
    └── templates/{index.html,auth.html}
```

## 🔌 API reference

All endpoints except login/setup require the session cookie.

<details>
<summary><b>REST</b></summary>

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/setup` | Create the first admin account |
| `POST` | `/api/auth/login` · `/api/auth/logout` | Sign in / out (`otp` field when 2FA is on) |
| `GET` | `/api/auth/security` | 2FA status |
| `POST` | `/api/auth/2fa/{setup,enable,disable,backup-codes}` | Manage two-factor authentication |
| `POST` | `/api/auth/password` | Change password |
| `GET` | `/api/audit` | Activity log |
| `GET` | `/api/apps` | List apps with update status |
| `POST` | `/api/updates/check` | Re-check all registries |
| `GET` | `/api/apps/{name}/details` | Changelog & update details |
| `POST` | `/api/apps/{name}/prefs` | Auto-update, skip version, custom repo |
| `POST` | `/api/apps/{id}/{action}` | `start`, `stop`, `restart`, `kill` |
| `GET` | `/api/apps/{name}/compose` | Read compose file & backups |
| `POST` | `/api/apps/{name}/compose/{to-yaml,to-ui,validate,apply,rollback}` | Compose editor |
| `POST` | `/api/apps/{name}/uninstall` | Layered uninstall |
| `POST` | `/api/deploy/generate` · `/api/deploy/validate` | Prepare a new deployment |
| `GET` | `/api/system/storage` | Docker disk usage |
| `POST` | `/api/system/prune` | Prune images / cache / containers / volumes |
| `GET` · `POST` | `/api/settings` | Read / save settings & history |
| `GET` | `/api/system/history?container=&hours=` | CPU/RAM samples (all containers when `container` is empty) |
| `GET` | `/api/backups` · `POST` `/api/backups/{restore,delete}` | App data backups |

</details>

<details>
<summary><b>WebSockets</b></summary>

| Path | Description |
|---|---|
| `/ws/logs/{id}` | Live container logs |
| `/ws/update/{name}` | Streamed update of one app |
| `/ws/update-all` | Streamed batch update |
| `/ws/deploy` | Streamed deployment |
| `/ws/task-manager` | Live resource metrics |

</details>

## 🛠️ Development

```bash
git clone https://github.com/boystyle2010/appmanager-pro.git
cd appmanager-pro
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
APP_DATA_DIR=./data uvicorn app.main:app --reload --port 8000
```

The dashboard needs access to a Docker daemon (`/var/run/docker.sock`). Before pushing, run the same checks as CI:

```bash
python scripts/check_project.py
node --check app/static/js/app.js && node --check app/static/js/i18n.js
```

Commit messages do not appear in the changelog; use `RELEASE_NOTES_NEXT.md` for release notes.

## 🔒 Security notes

- Mounting `/var/run/docker.sock` gives the app **root-equivalent control** of the host. Keep it on your LAN or behind a VPN (e.g. Tailscale) or an authenticated tunnel (e.g. Cloudflare Access) — do not expose it directly to the internet.
- Use HTTPS (reverse proxy) when accessing it remotely so session cookies are marked `Secure`.
- Turn on **two-factor authentication** (Settings → Security) and keep the backup codes somewhere safe.
- If you use a reverse proxy on another machine, add its IP to `TRUSTED_PROXIES`; otherwise every request appears to come from the proxy.
- Lost the admin password or your 2FA device and backup codes? Set `RESET_AUTH=true`, restart, create a new account, then set it back to `false`.

## ❓ Troubleshooting

| Problem | Fix |
|---|---|
| Changelog is empty or shows only checksums | Add a **GitHub token** in Settings (rate limit), or set the app's repo with **Repo** in the update dialog. |
| An app shows no update although one exists | Press **Re-check**; private registries may need `docker login` on the host. |
| Update failed and was rolled back | Open **Live Logs** of the app and check **Settings → History** for the reason. |
| UI looks unstyled | Hard-refresh the page; the app falls back to CDNs if bundled libraries are missing. |
| Container restarts with `ModuleNotFoundError` | A file in `app/core/` is missing or misnamed — CI's *Check source* step reports which one. |
| Everyone gets locked out together | All requests come through one proxy that is not trusted — add it to `TRUSTED_PROXIES`. |
| 2FA codes are always rejected | Check that the phone's and server's clocks are correct (`TZ` does not matter, the clock does). |
| "Cross-site request blocked" behind a reverse proxy | The proxy changes the `Host` header — add your domain to `ALLOWED_ORIGINS` (or forward `Host` / `X-Forwarded-Host`). |
| 24h chart says "Collecting data" | Samples are taken every 5 minutes; wait at least 10 minutes after starting. |

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) or the [Releases](https://github.com/boystyle2010/appmanager-pro/releases) page.

## 🙏 Acknowledgements

[FastAPI](https://fastapi.tiangolo.com/) · [docker-py](https://github.com/docker/docker-py) · [ruamel.yaml](https://yaml.readthedocs.io/) · [APScheduler](https://apscheduler.readthedocs.io/) · [Alpine.js](https://alpinejs.dev/) · [Tailwind CSS](https://tailwindcss.com/) · [marked](https://marked.js.org/) · [DOMPurify](https://github.com/cure53/DOMPurify) · [CasaOS](https://casaos.io/)

## 📄 License

Released under the [MIT License](LICENSE) — free to use, modify and distribute, provided the copyright notice is kept. The software is provided "as is", without warranty.

---

<div align="center">Made with ❤️ by <a href="https://github.com/boystyle2010">boystyle2010</a></div>
