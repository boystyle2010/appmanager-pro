<div align="center">

<img src="assets/icon.png" alt="AppManager Pro" width="120" />

# AppManager Pro

**Fast, glassmorphic Docker & CasaOS app manager — real registry-digest update checks, changelog viewer, safe Compose editor with rollback, Task Manager and SSD cleanup.**

[![Build & Release](https://github.com/boystyle2010/appmanager-pro/actions/workflows/release.yml/badge.svg)](https://github.com/boystyle2010/appmanager-pro/actions/workflows/release.yml)
[![Latest Release](https://img.shields.io/github/v/release/boystyle2010/appmanager-pro?label=release&color=2ea043)](https://github.com/boystyle2010/appmanager-pro/releases/latest)
[![Release Date](https://img.shields.io/github/release-date/boystyle2010/appmanager-pro?label=released)](https://github.com/boystyle2010/appmanager-pro/releases/latest)
[![GHCR](https://img.shields.io/badge/ghcr.io-appmanager--pro-2496ED?logo=docker&logoColor=white)](https://github.com/boystyle2010/appmanager-pro/pkgs/container/appmanager-pro)
[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-appmanager--pro-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/boystyle2010/appmanager-pro)
[![Platforms](https://img.shields.io/badge/platform-linux%2Famd64%20%7C%20linux%2Farm64%20%7C%20linux%2Farm%2Fv7-informational?logo=linux&logoColor=white)](#-installation)
[![Signed](https://img.shields.io/badge/build%20provenance-signed%20by%20GitHub-6e40c9?logo=githubactions&logoColor=white)](https://github.com/boystyle2010/appmanager-pro/attestations)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Alpine.js](https://img.shields.io/badge/Alpine.js-3-8BC0D0?logo=alpinedotjs&logoColor=white)](https://alpinejs.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![CasaOS](https://img.shields.io/badge/CasaOS-ready-0A84FF)](https://casaos.io/)
[![License: MIT](https://img.shields.io/github/license/boystyle2010/appmanager-pro?color=yellow)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/boystyle2010/appmanager-pro)](https://github.com/boystyle2010/appmanager-pro/commits/main)
[![Stars](https://img.shields.io/github/stars/boystyle2010/appmanager-pro?style=social)](https://github.com/boystyle2010/appmanager-pro/stargazers)

[Features](#-features) • [Installation](#-installation) • [Configuration](#%EF%B8%8F-configuration) • [Usage](#-usage) • [Automation](#-automated-builds--releases) • [API](#-api-reference) • [FAQ](#-troubleshooting)

</div>

---

## 📖 Overview

AppManager Pro is a self-hosted web dashboard for managing the Docker containers on a home server — especially servers running **CasaOS**. It finds the `docker-compose.yml` behind each app (the exact file the container was created from), checks the registry for newer images by comparing **real digests** (not just tags), shows the upstream changelog, lets you switch between **release channels** (stable ↔ beta / dev), and updates apps safely with a settings backup and **automatic rollback** if the new version fails — for every app and for AppManager Pro itself.

It runs as a single container, ships a mobile-first "liquid glass" UI in English and Vietnamese, and needs nothing more than access to the Docker socket.

## ✨ Features

### Updates & changelogs
- **Real update detection** — compares the local image digest with the registry digest (Docker Hub, GHCR, lscr.io and other OCI registries), so `latest`-tagged apps are detected correctly. On Docker Hub the real version of a rolling tag is resolved from the versioned tag with the same digest (e.g. `latest` → `v0.147.0`); version labels inherited from the base OS (e.g. Ubuntu `24.04`) are ignored.
- **Pinned-tag bumping** — apps pinned to a version (e.g. `php:8.5.12-apache`, `lscr.io/linuxserver/syncthing:v1.27.0-ls140`) get the newest tag **of the same variant and major version** written to `docker-compose.yml`. Works on large repositories (all tag pages are read), build-numbered tags and `version-1.2.3` style tags.
- **Release channels** — when an image also publishes `beta`, `next`, `rc`, `dev`… (or pre-release versions such as `3.0.0-beta.2`) that are newer than the stable one *and* exist for the server's CPU architecture, the app shows a **BETA / DEV** badge. Pick a channel in the app details: its changelog loads first, and nothing changes until you tap *Switch & update* (normal update flow, with rollback).
- **Changelog viewer** — GitHub release notes of the exact version or pre-release; when a beta has no release, the commits on the main branch since the last stable release; falls back to `CHANGELOG.md`, `RELEASE_NOTES`, `CHANGES.md` and recent commits. Checksum-only releases are cleaned up. Custom repo override per app.
- **One-click & batch updates** — update a single app or *Update All* with live streaming logs. **Customize Update All** to leave chosen apps out (remembered; by default everything is updated).
- **Auto-update schedule** — opt-in per app, runs daily at the time you choose.
- **Skip version** — hide a specific release until the next one.
- **Auto-rollback** — the new container is health-checked (crash, restart loop, `unhealthy`). If it fails, the previous image and the **last working `docker-compose.yml`** are restored while the app data stays untouched; only if the old version still does not start is the settings backup restored too. The full log (including the failing container's last log lines) is kept in *History*.
- **Safe self-update** — AppManager Pro updates itself through a helper container running the current image, checks that the new version answers, and rolls back image, compose and its own database if it does not.

### App management
- **Start / Stop / Restart / Kill** and **live logs** for every container.
- **Compose editor (Edit Config)** — two-way *Visual UI ↔ YAML* editor (lossless `ruamel.yaml`), validation with `docker compose config`, timestamped backups and **one-click rollback**. *Save & Apply* checks that the app really starts and restores the previous file automatically if it does not.
- **Tag suggestions** — the *Image & Tag* field has a dropdown with the rolling tag of the same variant and the 3 newest stable versions from the registry.
- **Duplicate compose files** — when an app has another `docker-compose.yml` with different content (e.g. a CasaOS copy and one in `/DATA/AppData`), the card shows a badge; *Merge* keeps the running, working file as the base (only missing `x-casaos` blocks are taken from the other), *Skip* hides the warning until a file changes.
- **Deploy new apps** — paste YAML or use the quick form, validate, then deploy with live pull/up logs.
- **Smart uninstall** — four levels: container, CasaOS compose folder, Docker image, and (with confirmation) app data in `/DATA/AppData`.

### System
- **Task Manager** — live CPU, RAM, network and PIDs per container over WebSocket, plus **24-hour CPU/RAM charts** (sampled every 5 minutes, kept 7 days).
- **Storage / SSD cleanup** — disk-usage breakdown (images, build cache, containers, volumes), selective prune with size estimate.
- **Scheduled SSD cleanup** — daily / weekly / monthly cleanup of images and build cache (containers and volumes are never removed automatically).
- **Update history** — every update, rollback and cleanup is logged.
- **Settings backups** — before each update the app's **settings files** are archived (json / yaml / conf / env / xml, small databases with their `-wal`/`-shm`, certificates, small text/JSON settings files) from the folders it mounts from `/DATA/AppData` — never media, storage, downloads, sync folders, caches or logs — together with the image (digest) and `docker-compose.yml`. Apps without a config folder still get an image + compose backup.
- **Restore** — a *Restore* button on every app card lets you pick the backup (newest preselected) and shows progress and each step. If the old image was removed, it is pulled again by digest (or version tag). Current logs and all other data are kept.

### Security & UI
- **Admin account** with Argon2id password hashing, signed session cookies (`HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS) and **IP lockout** after 5 failed logins (15 minutes, persisted across restarts). Proxy headers are only trusted from configured proxies, so the lockout cannot be bypassed with fake IPs.
- **Two-factor authentication (TOTP)** with QR setup and one-time backup codes; works with Google Authenticator, 1Password, iOS Passwords and others.
- **Password change** from the UI (signs out other devices).
- **Activity log** — sign-ins, failed attempts, updates, uninstalls, compose edits, cleanups and settings changes with user and IP.
- **Hardened HTTP** — Content-Security-Policy, clickjacking protection, `nosniff`, and Origin checks on every API write and WebSocket (CSRF protection).
- **Glassmorphic, mobile-first UI**, dark/light theme, English & Vietnamese, installable as a PWA.
- **No runtime CDN dependency** — Tailwind CSS v4 is compiled into a static stylesheet when the image is built, and Alpine.js, marked, DOMPurify and fonts are bundled too, with automatic CDN fallback. Requires a modern browser (Safari 16.4+, Chrome 111+, Firefox 128+).

## 🚀 Installation

### Requirements
- A Linux host with Docker Engine and Docker Compose v2 (`amd64`, `arm64` or 32-bit `armv7`)
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

> The image is also published on Docker Hub as `boystyle2010/appmanager-pro` (same tags: `latest`, `X.Y.Z`, `build-<sha>`). GHCR is the recommended source: Docker Hub limits anonymous pulls.


Then start it:

```bash
cd /DATA/AppData/appmanager-pro
docker compose up -d
```

Open **`http://<server-ip>:8098`** and create the admin account on first launch.

> **Note:** the container name must stay `appmanager-pro` so the app can recognise and update itself.

### Other environments

AppManager reads every app's `docker-compose.yml` **at the same path as on the host** (Docker Compose stores host paths in the container labels). Mount the folder that holds your apps **with the same path on both sides** (`/x:/x`). If you forget, a popup after the first login offers **Manual** entry or **Auto Scan** and adds the folder for you (also in *Settings → Storage → App data folder*). Cards of apps whose compose file cannot be read show the expected path and the line to add.

<details>
<summary><b>Plain Ubuntu / Debian</b> — apps in <code>/home/&lt;user&gt;/docker</code> (or any folder)</summary>

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
      - TZ=Europe/Berlin
      - APPDATA_DIR=/home/me/docker          # folder used for app settings backups
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /home/me/docker:/home/me/docker      # SAME path on both sides
      - ./data:/app/data
```
Save it as `/home/me/docker/appmanager-pro/docker-compose.yml`.
</details>

<details>
<summary><b>Dockge</b> — stacks in <code>/opt/stacks</code></summary>

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
      - TZ=Europe/Berlin
      - APPDATA_DIR=/opt/stacks
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks:/opt/stacks
      - ./data:/app/data
```
Create it as a new stack named `appmanager-pro` in Dockge.
</details>

<details>
<summary><b>Portainer stacks</b></summary>

Portainer keeps stack files in its own data volume (`/data/compose/<id>` inside Portainer). AppManager finds the Portainer container, maps that path to the host and runs the stack with its real project name and `stack.env`. Mount Portainer's compose folder at the same path:

```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      # named volume "portainer_data" (default install):
      - /var/lib/docker/volumes/portainer_data/_data/compose:/var/lib/docker/volumes/portainer_data/_data/compose
      # or, if Portainer uses a folder: - /srv/portainer/compose:/srv/portainer/compose
      - ./data:/app/data
```
Deploy AppManager itself with Docker Compose (not as a Portainer stack), so it can update itself.
</details>

<details>
<summary><b>Containers created with <code>docker run</code></b></summary>

They are managed **directly** (card badge `RUN`) — no compose file needed. Update, Update All, scheduled auto-update, *Choose version* and release channels work like for compose apps: AppManager pulls the new image, stops the old container and keeps it renamed as `<name>-amp-old`, creates a new container with the **same settings** (ports, volumes incl. anonymous ones, environment, networks with static IPs and aliases, devices, capabilities, healthcheck, restart policy…), checks it, and removes the old one only when the new one runs correctly — otherwise the old container is started again. Values that come from the image itself (default environment, command, labels) are not copied, so the new image's defaults apply. Containers sharing the network of the updated one (`--network container:<name>`) are recreated to join the new container. The last working configuration is saved in `data/run-snapshots/`. Backups taken before an update also store the container settings, so **Restore** brings back the image, the container settings and the config files — and can recreate the container even if it was deleted. If the previous version no longer starts after a failed update (the new version changed its config files), the config files are restored from that backup automatically. **⋯ → docker run command** shows the equivalent command to view or copy. **Edit Config** works for them too: the container's settings are shown in the visual editor / YAML (no file is written), and *Save & Apply* recreates the container with the new settings, checks it and starts the previous container again if it fails. AppManager itself can also run with `docker run`: self-update and *Save & Apply* on itself go through a helper container (health check on `/login`, rollback to the previous container, database restored only if needed); changes that would remove its data folder or the Docker socket are refused. Containers started with `--rm` are shown read-only, because Docker deletes them when they stop (no safe rollback). Containers linked with `--link` or sharing the network (`--network container:<name>`) are recreated so they keep reaching the updated container. If an update is interrupted (power loss, Docker or AppManager restart), AppManager puts the previous container back on its next start, and an interrupted self-update is finished or rolled back by the helper when Docker starts again. **Private images:** add the registry account in *Settings → Update sources & API limits → Registry accounts* (a read-only access token; it is tested before it is saved), or mount the host's `~/.docker/config.json`. Without credentials, updates of private images stop with a clear message and change nothing.

Containers managed by another tool (Docker Swarm, Kubernetes, Unraid, Synology, Portainer agent…) are only shown and can be started / stopped. Converting a `docker run` container to compose stays available as an option (**⋯ → Convert to compose**).
</details>

<details>
<summary><b>Podman</b> (experimental)</summary>

Enable the Docker-compatible API socket and mount it as the Docker socket:

```bash
systemctl enable --now podman.socket          # rootful: /run/podman/podman.sock
```
```yaml
    volumes:
      - /run/podman/podman.sock:/var/run/docker.sock
```
`docker compose` inside AppManager talks to Podman through that socket. Self-update and rollback use helper containers; report issues if something behaves differently from Docker.
</details>

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
| `TRUSTED_PROXIES` | `127.0.0.0/8,::1/128` | Comma-separated IPs/CIDRs of reverse proxies whose `X-Forwarded-For` header is trusted. Only localhost by default. If you use Cloudflare Tunnel or Nginx Proxy Manager in Docker, add that container's exact IP (e.g. `172.18.0.5`) — not the whole `172.16.0.0/12` range, which any other container could use to fake IPs. |
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
| Periodic check | 6 h | How often registries are checked in the background. |
| Scheduled auto-update | off | Daily time to update apps that have *Auto-Update* enabled. |
| Auto-clean old images | on | Remove the previous image after a successful update. |
| Auto-rollback | on | Restore the previous version if the update fails the health check. |
| Health check time | 25 s | How long the new container is watched (10–120 s). |
| Scheduled SSD cleanup | off | Daily / weekly / monthly cleanup of images & build cache. |
| Back up app data before updates | on | Archive the app's settings files + image + compose before each update (max per file, total size and number kept are configurable). |
| GitHub token | — | Optional; raises the GitHub API limit (60 → 5,000 requests/hour) and allows private repos. |
| Security tab | — | Two-factor authentication, password change, activity log. |

### Notifications

*Settings → Notifications*: add one or more channels and choose the events per channel. 16 channel types:

| Group | Channels | iPhone |
|---|---|---|
| Chat apps | **Telegram**, **Discord**, **Slack**, **Microsoft Teams** (Workflows webhook), **Google Chat**, **Mattermost** (also Rocket.Chat webhooks), **Matrix**, **Signal** (via signal-cli-rest-api) | ✅ all |
| Push to your phone | **ntfy**, **Bark** (iPhone only), **Pushover**, **Pushbullet**, **Gotify** | ✅ ntfy, Bark, Pushover — ❌ Gotify (Android / web only), Pushbullet (mainly Android / browser) |
| Other | **Email** (SMTP: STARTTLS / SSL / none), **Apprise API** (100+ more services: WhatsApp, LINE, SMS…), generic **Webhook** (JSON, optional HMAC signature in `X-AppManager-Signature`) | ✅ Email, Apprise |

**Privacy options (per channel):**
- **Encrypt message content** — Bark (AES-128/192/256-CBC, decrypted by the Bark app on your iPhone; enter the same key and IV in Bark → Push Encryption) and Webhook (AES-256-GCM, key = SHA-256 of your passphrase, body `{"encrypted": base64(nonce + ciphertext + tag), "alg": "AES-256-GCM"}`). Other apps cannot decrypt messages, so they rely on transport encryption (HTTPS / TLS).
- **Private mode** — any channel: only a generic title (e.g. "❌ Update failed") is sent, without app names, IP addresses or details.

Self-hosted ntfy + iPhone: add `upstream-base-url: "https://ntfy.sh"` to the ntfy `server.yml` so iPhones are woken up instantly (only a wake-up signal goes through ntfy.sh; the message stays on your server).

Events:

| Event | When |
|---|---|
| Updates available | new versions found (one grouped message, each version only once) |
| Update finished / failed / rolled back | every update, version switch, restore and settings change |
| AppManager self-update | result of AppManager's own update |
| App problem | a container keeps restarting, is unhealthy, or exits with an error code (and when it recovers) |
| Disk almost full | usage above the threshold (at most once a day per folder) |
| Security | IP locked after failed logins, password changed, 2FA disabled |

*Send test* checks a channel. **Quiet hours** hold regular messages and send them as one summary afterwards; important ones (failures, app problems, disk, security) are always sent. Messages are in English or Vietnamese.

### Rate limits (Docker Hub, GitHub)

Docker Hub and GitHub limit how many requests an IP can make (GitHub: 60/hour without a token, 5,000/hour with one). AppManager:

- caches answers — content-addressed blobs and release notes of a tag permanently, tag lists for an hour, GitHub answers revalidated with ETag (a `304` does not count against the limit); update detection itself always asks the registry (`HEAD`, which Docker Hub does not count);
- pauses only the limited source until the time given by `Retry-After` / `X-RateLimit-Reset` (remembered across restarts) and **keeps the last known update status** — cards show "Checks paused until HH:MM";
- limits parallel requests per source;
- shows requests, cache hits, remaining quota and pauses in *Settings → Update sources & API limits*, where you can also add a GitHub token and registry accounts (Docker Hub, GHCR, any registry) to raise the limits.

### API tokens (automation)

*Settings → API tokens*: create a token for **Home Assistant**, scripts / CI or **Uptime Kuma** and send it as `Authorization: Bearer amp_…`.

| Permission | Allows |
|---|---|
| Read only | every `GET`: apps, versions, updates, history, health |
| Update | read + check for updates, update an app or all apps (health check + rollback as usual), start / stop / restart |
| Full access | everything except your account, 2FA, API tokens and registry passwords |

- The token is shown **once**; AppManager stores only its SHA-256 fingerprint. Optional expiry (30 days, 90 days, 1 year or never) and IP / network allow-list; the list shows when and from which IP each token was last used.
- Tokens are never accepted in the URL; 5 wrong tokens lock the IP for 15 minutes (as for sign-in). Creating a token sends a *Security* notification; every action is in the activity log as `token:<name>`.
- `GET /api/health` needs no token and returns only `{"status": "ok"}` (Uptime Kuma keyword monitor); with a token it adds the version, app counts and apps with an update.
- Updates run in the background: `POST /api/apps/{name}/update` (optional `{"tag": "<version>"}`) or `POST /api/update-all` returns a job; poll `GET /api/jobs/{id}`.
- **API docs** for your server (curl examples, permission per endpoint) at `/docs` when signed in; OpenAPI 3 at `/openapi.json`.

```yaml
# Home Assistant — configuration.yaml
rest:
  - resource: http://192.168.1.10:8098/api/health
    headers:
      Authorization: "Bearer amp_…"
    scan_interval: 300
    sensor:
      - name: "AppManager updates"
        value_template: "{{ value_json.apps.updates }}"
rest_command:
  appmanager_update_all:
    url: http://192.168.1.10:8098/api/update-all
    method: POST
    headers:
      Authorization: "Bearer amp_…"
```

### Multiple servers

*Settings → Servers*: manage the AppManager of other machines from this one.

| | |
|---|---|
| **Protocol** | This AppManager calls the **REST API** of the AppManager on the other machine over **HTTP or HTTPS**, authenticated with an **API Token** (`Authorization: Bearer amp_…`). The Docker socket is never exposed to the network and no extra agent is installed. |
| **Requirements** | The other machine runs **AppManager 0.17.0 or newer**; this machine can reach its address and port (same LAN, a VPN such as Tailscale / WireGuard, or HTTPS through a reverse proxy). |
| **API Token** | On the other machine: *Settings → API Token* → permission **Update** (update, start / stop / restart) or **Read only** (view). Limit it to this machine's IP. |
| **Security** | Over the Internet use **HTTPS** — plain HTTP sends the Token unencrypted. A self-signed certificate works if you turn off certificate checking for that server. Redirects are never followed, so the Token is only sent to the address you entered. Tokens are stored in this machine's database and never returned to the browser; API Tokens of this machine cannot use the server list. |
| **Who does the work** | The other machine still pulls, recreates, health-checks and rolls back by itself; this machine only sends the command and shows the live log. Both activity logs record the action. |

Once a server is added, a switcher appears above the app list (**This server** / other servers, with update counts and a red dot when a server is unreachable). For another server you can see its apps, check for updates, update one app or all apps and start / stop / restart containers; logs, Edit Config, restore and uninstall stay on that server's own AppManager (*Open ↗*).

## 🧭 Usage

| Where | What you can do |
|---|---|
| **Dashboard** | Search, sort (smart, name A–Z / Z–A, running or stopped first), filter (All / Updates / Running / Stopped), *Update All* and its ⚙ customize button, re-check registries. |
| **App card → version row** | Open update details: changelog, release channel, auto-update toggle, skip version, *Update App*. |
| **App card → Restore** | Go back to a saved version (image + compose + settings). |
| **App card → badges** | **BETA / DEV** (channel available / in use), **AUTO** (auto-update on), **2** (duplicate compose files — tap to review). |
| **App card → ⋯** | Logs, start/stop/restart, Edit Config, uninstall. |
| **Header → activity icon** | Task Manager (live resources, restart/stop/kill). |
| **Header → ⚙️** | Section list: General, Storage & SSD (data folders, cleanup, app data backups), Notifications, Security (2FA, password, activity log), API tokens, History, About. |
| **Task Manager → 24h** | CPU/RAM charts for all containers or a single one. |
| **＋ button** | Deploy a new app from YAML or the quick form. |

## 🤖 Automated builds & releases

One GitHub Actions workflow ([`release.yml`](.github/workflows/release.yml)) runs **every day**, on **every push to `main`**, and **on demand**:

1. **Checks the source** — Python syntax, internal imports, Jinja templates, static files and JavaScript ([`scripts/check_project.py`](scripts/check_project.py)).
2. **Looks for updates** ([`scripts/auto_update.py`](scripts/auto_update.py)) of the Python base image, Docker CLI, Python packages, frontend libraries and — with the `WORKFLOW_TOKEN` secret — the GitHub Actions used by the workflow. Always the newest stable release, **including new major versions**.
3. **Verifies** the result by building the real image (amd64 + arm64 + armv7, with build cache) and starting the app inside it with a smoke test ([`scripts/verify.sh`](scripts/verify.sh)). If the newest versions fail, it retries with same-major updates only and notes the held-back upgrades. The result is **committed via the GitHub API**, so commits are signed by GitHub (*Verified*).
4. **Builds** the multi-arch image (`linux/amd64`, `linux/arm64`, `linux/arm/v7`), pushes it to **GHCR** and **Docker Hub**, and **signs** both with a GitHub build-provenance attestation.
5. **Scans the image with Trivy** (critical/high, fixable only).
6. **Publishes a GitHub Release** whose notes come from `CHANGELOG.md` (Component & Version Matrix, Package Integrity with the Trivy result, What's Changed), and syncs this README to Docker Hub.

Image tags (same on both registries): `latest`, `X.Y.Z` (on release) and `build-<commit>`.

Verify an image:

```bash
gh attestation verify oci://ghcr.io/boystyle2010/appmanager-pro:latest -R boystyle2010/appmanager-pro
```

**Manual releases:** *Actions → Auto Update, Build & Release → Run workflow* — tick `force_release`, or type a version such as `1.0.0` in `version`.
The changelog lists **component updates** plus your own notes: write bullet lines in `RELEASE_NOTES_NEXT.md`; they are moved into the changelog on the next release and the file is cleared.

**Repository secrets (optional):** `WORKFLOW_TOKEN` (fine-grained token, Contents + Workflows read/write, this repo only) lets the bot upgrade workflow actions; `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` (Read, Write, Delete) publish to Docker Hub and sync its description.

## 🗂️ Project structure

```
appmanager-pro/
├── .github/workflows/release.yml   # daily update check, build, sign & release
├── Dockerfile                      # python slim + Docker CLI & Compose v2 (pip removed after install)
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
    ├── self_update_helper.py       # helper container: self-update with health check & rollback
    ├── core/
    │   ├── app_backup.py           # app data backups & restore
    │   ├── auth.py                 # Argon2 login, sessions, lockout, TOTP 2FA
    │   ├── compose_manager.py      # compose editor, Save & Apply with rollback, merge, uninstall
    │   ├── compose_snapshot.py     # remembers the last working compose of each app
    │   ├── database.py             # SQLite settings, cache & history
    │   ├── docker_client.py        # container listing & actions
    │   ├── registry_checker.py     # digest checks, tags, release channels, changelogs
    │   ├── scheduler.py            # background checks, auto-update, SSD cleanup
    │   ├── system_monitor.py       # Task Manager metrics
    │   ├── system_prune.py         # disk usage & prune
    │   └── updater.py              # pull/recreate, health check, rollback
    ├── static/
    │   ├── css/glass.css               # glass UI (CSS layer "components")
    │   ├── css/tailwind.input.css      # Tailwind v4 source, compiled in the Dockerfile
    │   └── js/{app.js,i18n.js}
    └── templates/{index.html,auth.html}
```

## 🔌 API reference

All endpoints except login/setup and `/api/health` require the session cookie or an API token (`Authorization: Bearer amp_…`, see [API tokens](#api-tokens-automation)). Full, always up-to-date reference for your version: `/docs` (signed in).

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
| `GET` | `/api/backups` · `POST` `/api/backups/{restore,delete}` | Settings backups & restore |
| `GET` | `/api/apps/{name}/channel-preview?tag=` | Changelog of a release channel (read-only) |
| `GET` | `/api/image-tags?image=` | Tag suggestions for the compose editor |
| `POST` | `/api/apps/{name}/compose/duplicates` | `merge` / `skip` duplicate compose files |
| `POST` | `/api/update-all/excluded` | Apps left out of *Update All* |
| `GET` | `/api/history/{id}/log` | Full log of one update |
| `GET` | `/api/health` | Health (no token: status only) |
| `POST` | `/api/apps/{name}/update` · `/api/update-all` | Update in the background → job |
| `GET` | `/api/jobs` · `/api/jobs/{id}` | Background job status & log |
| `GET` · `POST` | `/api/tokens` · `/api/tokens/delete` | Manage API tokens (web sign-in only) |
| `GET` · `POST` | `/api/servers` · `/api/servers/{test,delete,status}` | Other servers (web sign-in only) |
| `GET` · `POST` | `/api/servers/{id}/apps` · `…/check` · `…/update-all` · `…/apps/{name}/{update,start,stop,restart}` · `…/jobs/{job}` | Manage apps on another server |

</details>

<details>
<summary><b>WebSockets</b></summary>

| Path | Description |
|---|---|
| `/ws/logs/{id}` | Live container logs |
| `/ws/update/{name}` | Streamed update of one app (`?tag=` switches release channel) |
| `/ws/update-all` | Streamed batch update |
| `/ws/deploy` | Streamed deployment |
| `/ws/task-manager` | Live resource metrics |

</details>

## 🛠️ Development

```bash
git clone https://github.com/boystyle2010/appmanager-pro.git
cd appmanager-pro
python3 -m venv .venv && source .venv/bin/activate
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
| Update failed and was rolled back | **Settings → History → View log** shows each step and the failing container's last log lines. |
| An app runs from a different compose file than CasaOS shows | The card shows a **2** badge — open Edit Config and use *Merge* (keeps the running file) or *Skip*. |
| A BETA / DEV channel is missing | Channels are only offered when newer than stable and built for the server's CPU architecture. Press **Re-check**. |
| UI looks unstyled | Hard-refresh the page; the app falls back to CDNs if bundled libraries are missing. |
| Container restarts with `ModuleNotFoundError` | A file in `app/core/` is missing or misnamed — CI's *Check source* step reports which one. |
| Everyone gets locked out together | All requests come through one proxy that is not trusted — add that proxy's IP to `TRUSTED_PROXIES` (find it with `docker inspect <proxy-container>`). |
| 2FA codes are always rejected | Check that the phone's and server's clocks are correct (`TZ` does not matter, the clock does). |
| "Cross-site request blocked" behind a reverse proxy | The proxy changes the `Host` header — add your domain to `ALLOWED_ORIGINS` (or forward `Host` / `X-Forwarded-Host`). |
| 24h chart says "Collecting data" | Samples are taken every 5 minutes; wait at least 10 minutes after starting. |

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) or the [Releases](https://github.com/boystyle2010/appmanager-pro/releases) page.

## 🙏 Acknowledgements

[FastAPI](https://fastapi.tiangolo.com/) · [docker-py](https://github.com/docker/docker-py) · [ruamel.yaml](https://yaml.readthedocs.io/) · [APScheduler](https://apscheduler.readthedocs.io/) · [Alpine.js](https://alpinejs.dev/) · [Tailwind CSS](https://tailwindcss.com/) · [marked](https://marked.js.org/) · [DOMPurify](https://github.com/cure53/DOMPurify) · [CasaOS](https://casaos.io/)

Notification channel logos (Telegram, Discord, Google Chat, Mattermost, Matrix, Signal, ntfy, Pushbullet) come from [Simple Icons](https://simpleicons.org/) (CC0); all trademarks belong to their owners and are used only to name the service. Slack, Microsoft Teams, Pushover, Gotify, Bark, Apprise, Email and Webhook use generic icons drawn for AppManager, not the companies' logos.

## 📄 License

Released under the [MIT License](LICENSE) — free to use, modify and distribute, provided the copyright notice is kept. The software is provided "as is", without warranty.

Copyright (c) 2026 boystyle2010. The app icon is original work by the author. Third-party components (Python packages, Alpine.js, Tailwind CSS, marked, DOMPurify, fonts, Docker CLI & Compose) keep their own licenses — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [`licenses/`](licenses/).

---

<div align="center">Made with ❤️ by <a href="https://github.com/boystyle2010">boystyle2010</a></div>
