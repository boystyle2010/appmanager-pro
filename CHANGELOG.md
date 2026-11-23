# Changelog

## 0.10.0

*Released: 2026-11-23*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.9.4` ➡️ `v0.10.0`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.15.2`
- **Docker CLI:** `docker 29.10.0`
- **Core Python Stack:** `FastAPI 0.165.0` • `Uvicorn 0.54.0` • `Docker SDK 7.2.0` • `ruamel.yaml 0.19.1` • `Argon2 25.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • `Tailwind CSS 4.3.5` • `marked 18.2.1` • `DOMPurify 3.5.0`

### 🚀 What's Changed

- Fixed changelogs failing with "Can't find variable: marked" (marked v18 no longer ships `marked.min.js`); changelogs fall back to plain text if the library is missing, and the build now fails instead of shipping a missing library
- Updates, rollback and compose editing now use the exact compose file the container was started from; previously an app re-deployed from the terminal (e.g. in /DATA/AppData/<app>) could be recreated from an older CasaOS copy and become unhealthy
- Restoring a backup now restarts an app that was stuck restarting
- Update history now shows why an update failed and keeps the full update log (View log), including the failing container's last log lines and healthcheck output captured before rollback
- Rollback after a failed update now also restores the app data backed up just before the update (the new version may have changed the data), not only the old image
- Restoring an app data backup also brings back the app version from that backup when the app now runs a different one (if the old image is still on the server), and always starts the app again
- The compose editor keeps extra settings of long-syntax ports and volumes (e.g. `bind.create_host_path`, `mode`) instead of dropping them, and no longer adds empty `icon`/`port_map` values
- The compose editor warns when the app has another compose file with different content (e.g. a CasaOS copy and one in /DATA/AppData), which can bring back an old configuration
- AppManager Pro now checks itself after a self-update or an edit of its own compose file: if the new version does not start (web UI not answering, crash loop, unhealthy), it automatically goes back to the previous image and compose file; the result and full log appear in Settings → History
- A failed update now restores everything for every app: the app data backed up just before the update, the docker-compose.yml that last ran correctly (also when the file had been edited but never applied), and the previous image; "docker compose up" errors are rolled back too
- Save & Apply in the compose editor checks that the app really starts; if not, the previous docker-compose.yml is restored automatically and the log is shown in the editor
- AppManager Pro backs up its own database before a self-update and restores it if the new version is rolled back
- "Back up app data before updating" is now on by default for new installs
- App data backups now contain only the app's own configuration: folders mounted from /DATA/AppData, without media, storage/share, downloads, sync folders, caches, the app's own backups, media files and files above a per-file limit (default 50 MB, e.g. large history databases). Restoring replaces only those files; media and large files are left untouched
- Rollback first restores only the previous image and docker-compose.yml and keeps the app data as it is (settings and logs stay); the configuration backup is used only if the previous version still does not start. Restoring a backup never replaces current log files
- App backups now contain only settings files (json, yaml, conf, env, small databases, certificates, small JSON/text settings files such as Home Assistant's .storage), not whole data folders, media or logs
- Settings backups also include Samba databases (.tdb, e.g. SMB passwords) and session/secret files; .jsonl audit logs are treated as logs and never replaced on restore
- App cards: a Restore button next to Update brings the app back to the version, docker-compose.yml and settings saved before its last update; the ⋯ menu moved to the top-right corner next to the CasaOS / Docker badge
- The Restore button lets you choose which saved version to go back to (the newest is preselected); the ⋯ button on app cards has a frame like the CasaOS / Docker badge; "Edit docker-compose" is always listed in the ⋯ menu (greyed out with a reason when the app has no compose file)
- UI polish: the ⋯ button matches the CasaOS / Docker badge size, "Edit Config (UI/YAML)" label, cleaner restore version picker with technical descriptions
- Settings → Storage: aligned backup limit fields, version shown per backup, backup list and SSD schedule stay visible even if Docker disk usage cannot be read; restore picker uses amber accents; internal reload marker no longer saved in update logs
- UI: centered port column headers and update-time / check-interval fields (incl. the time picker on iOS Safari); AppManager Pro's own ⋯ menu shows Restart next to the close button
- Restore shows a progress window (elapsed time, then the result and each step performed); if the previous image was removed (e.g. by "auto-clean old images"), it is pulled again from the registry by its saved digest, or by its version tag for older backups
- Version detection: version labels inherited from the base OS image (e.g. Ubuntu "24.04") are ignored; for images on generic tags (latest, full…) the real version is resolved from the Docker Hub tag with the same digest (e.g. Scrypted v0.147.0)
- Pinned tags with a variant suffix on large Docker Hub repos (e.g. php:8.5.12-apache) now find newer tags of the same variant (8.6.0-apache)
- Update check for pinned version tags reworked for every app: Docker Hub tags are searched by variant / major line (not only the 60 newest), GHCR / lscr.io / other registries read all tag pages, build-numbered tags (e.g. linuxserver 1.2.3-ls45) and word prefixes (version-1.2.3) are recognised, and suggestions stay on the same major version (e.g. postgres 16.x is not moved to 17; calendar versions like 2026.x may move to the next year)
- Release channels: apps on a channel tag (latest, stable, latest-full…) show which other channels exist (beta, next, rc, dev…, only when newer than stable) with their versions; a β / BETA badge on the card, and a "Release channel" switcher in the app details that changes the tag through the normal update flow (backup, health check, automatic rollback)
- Release channels also for pinned version tags: a pre-release line (3.0.0-beta.2, v3.8.0-rc.3, 8.6.0RC7-apache, or a versioned tag that the "beta" tag points to) is offered next to the stable line when it is newer; versioned tags above the "latest" version are no longer suggested as stable updates
- Changelog follows the channel: apps on a pre-release channel show the GitHub release notes of that exact pre-release (or the newest pre-release), refreshed after a channel switch
- Channel switch is now two steps: confirming a channel only loads that channel's changelog (header shows the target version); the switch starts when "Switch to BETA & update" is tapped, and Cancel goes back
- Channel badges (BETA / DEV / RC…, dashed when available, filled when in use) are shown in the status line of every app card, including apps with a pending update; fixed an empty badge on apps without channels
- Pre-release changelog falls back to the commits between the last stable release and the pre-release tag when no GitHub release exists (e.g. Scrypted betas); Ubuntu base-image version labels (24.04…) are no longer shown as the app version
- App cards: channel (BETA / DEV…) and AUTO badges sit aligned on the image line of the version box; the selected-channel note and the changelog header show the selected channel's name and version (LATEST, STABLE, BETA, DEV…), in blue for stable and violet for pre-release channels
- Fixed a stale Ubuntu base-image version (24.04) kept in the update cache being shown again as the app version; the real version is resolved on the next check (e.g. Scrypted beta v0.148.6)
- Pre-release changelog for projects that build betas from the main branch without tags (e.g. Scrypted): commits on the default branch since the last stable release
- Every update now creates a restorable backup: apps without config folders in /DATA/AppData (e.g. cloudflared) get an image + docker-compose.yml backup, so the Restore button works for them; when a pinned tag is bumped, the previous compose also appears under Edit Config → Backups
- Edit Config → Image & Tag has a dropdown with the rolling tag of the same variant (latest / latest-full / apache…) and the 3 newest stable versions from the registry (pre-release builds excluded)
- Duplicate compose files: the warning in Edit Config has Merge (keeps the running, working file as the base and only adds missing x-* blocks such as x-casaos from the other file; refused while the container is not running correctly) and Skip (hides the warning until one of the files changes)
- Tag suggestions cover more tag styles: major-only tags (redis:7-alpine, node:20), build-numbered tags (one entry per version), "release"/"stable" rolling tags, and old tags with a different numbering scheme are ignored

## 0.9.4

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.9.3` ➡️ `v0.9.4`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.15.2`
- **Docker CLI:** `docker 29.10.0`
- **Core Python Stack:** `FastAPI 0.165.0` • `Uvicorn 0.54.0` • `Docker SDK 7.2.0` • `ruamel.yaml 0.19.1` • `Argon2 25.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • `Tailwind CSS 4.3.5` • `marked 18.2.1` • DOMPurify `3.4.18` ➡️ `3.5.0`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Image:** `boystyle2010/appmanager-pro:0.9.4`
- **Digest:** `sha256:47e821112f5c…`
- **Provenance:** ✅ Signed by GitHub · [View attestation](https://github.com/boystyle2010/appmanager-pro/attestations)
- **Vulnerability Scan (Trivy):** 0 critical • 1 high (fixable only) — setuptools in Python ×1

### 🚀 What's Changed

- Upgraded **DOMPurify** to `3.5.0`.
- Uninstalling one service of a multi-service stack now removes only that service (the rest of the stack and its folders are kept)
- Changelogs keep notes that contain commit links; only real checksum lines are hidden
- Trusted proxies default to localhost only; add your proxy's IP in `TRUSTED_PROXIES`
- One failing app no longer stops "Update All" or the nightly auto-update
- Self-update uses AppManager Pro's own image (no more outdated helper image)
- Safer "Open" links, clearer "check already running" message, AppManager Pro can no longer be stopped from its own menu
- CI now boots the real app with uvicorn and builds the arm64 image before publishing; Trivy results list the affected packages

## 0.9.3

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.9.2` ➡️ `v0.9.3`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.15.2`
- **Docker CLI:** `docker 29.10.0`
- **Core Python Stack:** `FastAPI 0.165.0` • `Uvicorn 0.54.0` • `Docker SDK 7.2.0` • `ruamel.yaml 0.19.1` • `Argon2 25.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • Tailwind CSS `4.3.3` ➡️ `4.3.5` • `marked 18.2.1` • `DOMPurify 3.4.18`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Image:** `boystyle2010/appmanager-pro:0.9.3`
- **Digest:** `sha256:1da572a9acc1…`
- **Provenance:** ✅ Signed by GitHub · [View attestation](https://github.com/boystyle2010/appmanager-pro/attestations)
- **Vulnerability Scan (Trivy):** 0 critical • 6 high (fixable only)

### 🚀 What's Changed

- Upgraded **Tailwind CSS** to `4.3.5`.
- UI moved to Tailwind CSS v4, compiled when the image is built (faster page load, no in-browser CSS compiler)
- Debian security updates are applied during the image build

## 0.9.2

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.9.1` ➡️ `v0.9.2`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.15.2`
- **Docker CLI:** `docker 29.10.0`
- **Core Python Stack:** `FastAPI 0.165.0` • `Uvicorn 0.54.0` • `Docker SDK 7.2.0` • `ruamel.yaml 0.19.1` • `Argon2 25.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • `Tailwind CSS 3.4.19` • `marked 18.2.1` • `DOMPurify 3.4.18`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Image:** `boystyle2010/appmanager-pro:0.9.2`
- **Digest:** `sha256:f91e97a1484b…`
- **Provenance:** ✅ Signed by GitHub · [View attestation](https://github.com/boystyle2010/appmanager-pro/attestations)
- **Vulnerability Scan (Trivy):** 0 critical • 7 high (fixable only)

### 🚀 What's Changed

- Maintenance release.

## 0.9.1

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.9.0` ➡️ `v0.9.1`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12.16` ➡️ `python 3.15.2`
- **Docker CLI:** `docker 27.5.1` ➡️ `docker 29.10.0`
- **Core Python Stack:** FastAPI `0.115.14` ➡️ `0.165.0` • Uvicorn `0.34.3` ➡️ `0.54.0` • `Docker SDK 7.2.0` • ruamel.yaml `0.18.17` ➡️ `0.19.1` • Argon2 `23.1.0` ➡️ `25.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • `Tailwind CSS 3.4.19` • marked `15.0.12` ➡️ `18.2.1` • `DOMPurify 3.4.18`

### 🚀 What's Changed

- Upgraded **Python Base Image** to `3.15.2`.
- Upgraded **Docker CLI** to `29.10.0`.
- Upgraded **FastAPI** to `0.165.0`.
- Upgraded **Uvicorn** to `0.54.0`.
- Upgraded **ruamel.yaml** to `0.19.1`.
- Upgraded **Argon2** to `25.1.0`.
- Upgraded **marked** to `18.2.1`.

## 0.9.0

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.5.1` ➡️ `v0.9.0`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12.16`
- **Docker CLI:** `docker 27.5.1`
- **Core Python Stack:** `FastAPI 0.115.14` • `Uvicorn 0.34.3` • `Docker SDK 7.2.0` • `ruamel.yaml 0.18.17` • `Argon2 23.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** `Alpine.js 3.17.5` • `Tailwind CSS 3.4.19` • `marked 15.0.12` • `DOMPurify 3.4.18`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Version Tag:** `ghcr.io/boystyle2010/appmanager-pro:0.9.0` (`sha256:7d74ca1150d9fd92e5d4f23cacf27182c6c03597f6373c4931768c1da98c8c12`)
- **Latest Tag:** `ghcr.io/boystyle2010/appmanager-pro:latest`
- **Provenance:** signed by GitHub — verify with `gh attestation verify oci://ghcr.io/boystyle2010/appmanager-pro@sha256:7d74ca1150d9fd92e5d4f23cacf27182c6c03597f6373c4931768c1da98c8c12 -R boystyle2010/appmanager-pro`
- **Vulnerability Scan (Trivy):** 3 critical • 88 high (fixable only)

### 🚀 What's Changed

- Maintenance release.

## 0.5.1

*Released: 2026-11-22*

### 📦 Component & Version Matrix

- **App Release:** Bumped from `v0.5.0` ➡️ `v0.5.1`
- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*
- **Python Base Image:** `python 3.12.16`
- **Docker CLI:** `docker 27.5.1`
- **Core Python Stack:** `FastAPI 0.115.14` • `Uvicorn 0.34.3` • `Docker SDK 7.2.0` • `ruamel.yaml 0.18.17` • `Argon2 23.1.0` • `itsdangerous 2.2.0` • `Jinja2 3.1.6` • `python-multipart 0.0.34` • `HTTPX 0.28.1` • `APScheduler 3.11.3` • `segno 1.6.6`
- **Frontend Libraries:** Alpine.js `3.14.8` ➡️ `3.17.5` • Tailwind CSS `3.4.17` ➡️ `3.4.19` • marked `15.0.6` ➡️ `15.0.12` • DOMPurify `3.2.3` ➡️ `3.4.18`

### 🔐 Package Integrity (GHCR Multi-Arch)

- **Version Tag:** `ghcr.io/boystyle2010/appmanager-pro:0.5.1` (`sha256:0f9899f43f337ef0c6595db741aa4f1d7422942f59f2d737ab0296b2ced13b4a`)
- **Latest Tag:** `ghcr.io/boystyle2010/appmanager-pro:latest`
- **Provenance:** signed by GitHub — verify with `gh attestation verify oci://ghcr.io/boystyle2010/appmanager-pro@sha256:0f9899f43f337ef0c6595db741aa4f1d7422942f59f2d737ab0296b2ced13b4a -R boystyle2010/appmanager-pro`
- **Vulnerability Scan (Trivy):** 3 critical • 88 high (fixable only)

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
