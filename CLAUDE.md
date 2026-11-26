# CLAUDE.md — AppManager Pro

Hướng dẫn cho Claude khi làm việc trên repo này (Claude Code / phiên mới).

## Chủ dự án & cách làm việc
- Chủ repo: **boystyle2010**. Trả lời bằng **tiếng Việt**, ngắn gọn, nói rõ cái gì đã kiểm tra thật và cái gì chưa.
- Chủ repo thường dùng **iPhone (Safari)**: giao diện phải ưu tiên mobile; thư mục bắt đầu bằng dấu chấm (`.github/`) bị ẩn trên iPhone.
- Server chạy thật: CasaOS tại `192.168.68.101`, compose ở `/DATA/AppData/appmanager-pro/docker-compose.yml`, dữ liệu ở `/DATA/AppData/appmanager-pro/data`. Truy cập trong mạng nhà (không qua proxy).
- Được phép push thẳng vào `main` (chủ repo đã đồng ý). Mỗi push vào `main` sẽ build & đẩy image `latest`.

## Kiến trúc
- Backend: FastAPI (`app/main.py`), logic trong `app/core/`:
  - `docker_client.py` (liệt kê app, hành động container, `APP_VERSION`), `registry_checker.py` (so digest registry — HEAD trước để không tốn quota Docker Hub —, lấy changelog, lọc checksum),
  - `updater.py` (pull/recreate, health check, auto-rollback, khoá mỗi app), `compose_manager.py` (sửa/deploy/gỡ compose),
  - `scheduler.py` (APScheduler: kiểm tra định kỳ, auto-update, dọn SSD theo lịch, lấy mẫu CPU/RAM 5 phút),
  - `auth.py` (Argon2, TOTP 2FA + mã dự phòng, khoá IP bền vững, `TRUSTED_PROXIES`, kiểm tra Origin), `database.py` (SQLite: settings, cache, lịch sử, audit log, mẫu tài nguyên),
  - `app_backup.py` (sao lưu/khôi phục **chỉ file cài đặt** của app — json/yaml/toml/ini/conf/env/xml, database nhỏ + -wal/-shm, chứng chỉ, file văn bản không đuôi hoặc JSON ≤ 1 MB — trong các mount thuộc `/DATA/AppData`; không duyệt thư mục media/storage/share/downloads/sync/cache/backups; bỏ file > giới hạn mỗi file (50 MB); khôi phục chỉ thay đúng các file đó, log & dữ liệu khác giữ nguyên; kèm compose + image), `system_prune.py`, `system_monitor.py`.
  - `compose_snapshot.py`: nhớ "compose chạy tốt gần nhất" mỗi app (`<data>/compose-good/`). Cập nhật hỏng → **trước hết chỉ trả compose chạy tốt + image cũ, giữ nguyên dữ liệu** (lỗi thường ở image/compose); bản cũ vẫn không chạy mới khôi phục cấu hình từ bản sao lưu (log hiện tại luôn giữ); compose bị sửa sau lúc tạo container thì quay về bản chạy tốt chứ không phải file hiện tại.
  - `app/self_update_helper.py`: container phụ chạy bằng **image cũ** để tự cập nhật/tạo lại AppManager → kiểm tra `/login` trong container mới → hỏng thì trả compose + gắn lại tag image cũ (giữ database); bản cũ vẫn hỏng mới trả database (`self-update-db.bak`). Trao đổi qua `<data>/self-update-job.json` → `self-update-result.json` (AppManager đọc lúc khởi động & mỗi phút, ghi vào Lịch sử).
- Module thêm từ 0.13–0.16 (`app/core/`):
  - `run_manager.py`: quản lý trực tiếp container **docker run** (nhãn `RUN`): cập nhật = tạo lại cùng cấu hình từ `docker inspect` (giữ container cũ tên `<tên>-amp-old` tới khi bản mới khoẻ, hỏng thì trả lại), sửa cấu hình qua YAML (`body_from_yaml`), lệnh `docker run` tương đương, sidecar `--network container:` / `--link`, phục hồi sau sự cố lúc khởi động (`recover_interrupted_sync`), `--rm` = chỉ xem. `manage_kind()`: compose / run / external (Swarm, K8s, Unraid, Synology…) / helper.
  - `compose_convert.py` (docker run -> compose, tuỳ chọn), `data_setup.py` (popup thiết lập thư mục Data: nhập tay / tự quét), `net.py` (MỌI lời gọi HTTP ra ngoài phải dùng `net.client()`: cache SQLite, tạm dừng nguồn khi 429/hết lượt, tài khoản registry -> `DOCKER_CONFIG` trong `<data>/docker-config`), `notify.py` (thông báo).
  - `api_tokens.py` (0.17): token `amp_…` (chỉ lưu SHA-256 trong setting `api_tokens`), quyền read / update / full (`scope_allows`: read = mọi GET; update = + `_UPDATE_POST`; full = mọi thứ trừ `_NEVER`: `/api/auth*`, `/api/tokens*`, `/api/system/registry-logins*`), hạn dùng, giới hạn IP. `auth.require_user` nhận cả cookie phiên lẫn `Authorization: Bearer` (`token_user`; sai token tính vào khoá IP như đăng nhập sai). Thêm API mới cho tự động hoá → cân nhắc thêm vào `_UPDATE_POST` và `_API_GUIDE` (main.py, hiện ở `/docs`).
  - `jobs.py` (0.17): việc chạy nền cho API HTTP (`POST /api/apps/{name}/update`, `POST /api/update-all` → `GET /api/jobs/{id}`), giữ trong bộ nhớ 50 việc. `/api/health` công khai (chỉ `status`), có token thì thêm chi tiết. `/docs` = `templates/api_docs.html` (render phía server, không CDN); `/openapi.json` chỉ khi đăng nhập / có token.
  - `servers.py` (0.18, nhiều máy chủ): máy chính gọi REST API của AppManager máy phụ qua HTTP(S) + API Token (setting `remote_servers`, Token lưu thô vì cần gọi, KHÔNG trả về trình duyệt). `call()` qua `net.client(verify=…, follow_redirects=False)`, lỗi -> `RemoteError` dễ hiểu; Token bị từ chối trả **424** (không dùng 401 vì trình duyệt sẽ đăng xuất). `/api/servers*` chỉ cho phiên đăng nhập (`_NEVER` trong api_tokens). Proxy: apps (bớt trường `trim_app`), check, update / update-all (job của máy phụ), start/stop/restart, jobs. Giao diện: mục Cài đặt "Máy chủ" (giải thích giao thức / yêu cầu), thanh chọn máy trên trang chính (`remote.id`), cửa sổ theo dõi job (`remoteJob`). Yêu cầu máy phụ >= 0.17.0.
  - Cài đặt (0.17): trang đầu là danh sách mục (`settingsMenu()` trong app.js, `settingsModal.tab = 'home'`), mỗi mục mở trang con có nút ‹. Thêm mục mới = thêm 1 dòng vào `settingsMenu()` + `<template x-if="settingsModal.tab === '…'">` + tiêu đề trong `settingsSectionTitle()`.
  - `self_update_helper.py`: hỗ trợ cả AppManager chạy bằng docker run (`run_body` trong job), chạy với `restart=on-failure`, chỉ kết thúc khi AppManager chắc chắn chạy (`finish()`), phục hồi khi bị chạy lại (`self-update-progress.json`).
- Frontend: Alpine.js — `app/templates/index.html` (markup), `app/static/js/app.js` (logic), `app/static/js/i18n.js` (EN/VI, **mọi key phải có ở cả hai ngôn ngữ**), `app/templates/auth.html`.
- CSS: **Tailwind v4** biên dịch lúc build image từ `app/static/css/tailwind.input.css` (stage `css` trong Dockerfile). `glass.css` và khối `<style>` trong `index.html` nằm trong `@layer components` để class tiện ích Tailwind luôn thắng. File `tailwind.css` là sản phẩm build, không commit.
- Thư viện JS (Alpine, marked, DOMPurify) và font được tải vào image bởi `scripts/fetch_vendor.py`, có CDN dự phòng trong HTML.

## Quy tắc quan trọng
- **Không sửa tay phiên bản** trong `Dockerfile`, `requirements.txt`, `scripts/fetch_vendor.py`, link CDN dự phòng, `APP_VERSION`, `CHANGELOG.md` — bot (`scripts/auto_update.py`) quản lý và tự commit. Luôn `git pull` trước khi sửa.
- Changelog **chỉ** ghi thay đổi thành phần nền. Ghi chú tự viết cho bản kế tiếp → thêm dòng `- ...` **bằng tiếng Anh** vào `RELEASE_NOTES_NEXT.md` (không tự tạo release). Changelog / release notes luôn viết tiếng Anh.
- Starlette 1.0: dùng `templates.TemplateResponse(request, "x.html", {...})`.
- Mọi POST/PUT/PATCH/DELETE `/api/*` và WebSocket phải qua kiểm tra Origin (`origin_allowed`). Ghi audit log (`audit(...)`) cho hành động quan trọng.
- Báo cáo cho chủ repo: tiếng Việt, nói rõ đã test thật cái gì (Docker thật trong sandbox, xem `tests/docker/README.md`) và cái gì chưa; gửi ảnh chụp giao diện (Playwright, khổ 390×844, deviceScaleFactor 2).
- UI đã thống nhất: popup căn giữa màn hình; thẻ app có nhãn nguồn (CASAOS/DOCKER/RUN) cao 24px như nút ⋯; công tắc bật/tắt (đỏ cho thao tác nguy hiểm như gỡ app); mọi thao tác nguy hiểm có mục "Sẽ thực hiện" + hộp xác nhận; thuật ngữ tiếng Việt dễ hiểu.
- Tailwind v4: dùng `shadow-xs` (thay `shadow-sm` cũ), `backdrop-blur-xs`, `bg-linear-to-*`.

## Kiểm tra trước khi push
```bash
python -m compileall -q app scripts
python scripts/check_project.py          # import nội bộ, Jinja, file tĩnh (cần jinja2)
node --check app/static/js/app.js && node --check app/static/js/i18n.js
bash scripts/verify.sh amp-test smoke    # cần Docker: build image, chạy uvicorn, smoke test
```
Test kịch bản trên Docker thật (20 bộ, ~2,5 giờ): làm đúng theo **`tests/docker/README.md`** (dựng dockerd, image mirror, registry/ntfy/Gotify, build image test, chạy `run_everything.sh`, chụp ảnh). Thay đổi lớn ở cập nhật/rollback/docker run/thông báo → chạy lại các bộ liên quan trước khi phát hành; thêm kịch bản mới vào `tests/docker/` (không để chỉ trong scratchpad).

## CI (`.github/workflows/release.yml`)
- Chạy hằng ngày, khi push `main` (bỏ qua thay đổi chỉ `*.md`/LICENSE), hoặc bấm tay (`force_release`, `version`).
- Bot nâng **mọi** thành phần lên bản mới nhất (kể cả major) → build & chạy thử thật (uvicorn + smoke test + build arm64) → hỏng thì lùi về nâng cùng major → commit qua GitHub API (có chữ ký) → build multi-arch, ký attestation, quét Trivy → tạo Release.
- Image đẩy lên **GHCR** (nguồn chính) và **Docker Hub** (`<DOCKERHUB_USERNAME>/appmanager-pro`, khi có secret `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`), cùng tag `latest`/`X.Y.Z`/`build-<sha>`; mô tả Docker Hub đồng bộ từ README khi có bản phát hành.
- Bot nâng cả action trong `.github/workflows/` (lên major mới nhất, bỏ qua nếu bản mới mất input đang dùng) khi có secret `WORKFLOW_TOKEN` (fine-grained PAT: Contents + Workflows Read/Write, chỉ repo này). Không có secret thì phải nâng tay. Commit của bot có `[skip ci]`. Trivy ghim theo commit SHA (không tự nâng).

### Phát hành — lưu ý quan trọng
- Push lên `main` có thể **tự phát hành** nếu bot thấy thành phần nền có bản mới (đã xảy ra: 0.14.1 lấy hết ghi chú của bản định làm 0.15.0). Muốn tự đặt số phiên bản: push với `[skip ci]` trong commit message, rồi chạy workflow `release.yml` (workflow_dispatch) với `force_release=true`, `version=X.Y.Z`. Đề xuất (chưa làm, cần chủ repo đồng ý): lần build khi push chỉ nâng thành phần, không tự tạo Release.
- Ghi chú phát hành viết **tiếng Anh** vào `RELEASE_NOTES_NEXT.md` (bot gom vào CHANGELOG khi phát hành rồi xoá).

## Việc còn mở
- Trivy: `golang.org/x/net` v0.60.0 trong `docker-compose` (CVE-2026-78661, tạm bỏ qua trong `.trivyignore` tới 2027-02-28) — chờ Docker Compose phát hành bản dùng x/net ≥ 0.62.0 (v5.8.0 và nhánh main ngày 2026-11-18 vẫn là v0.60.0).
- Phiên bản đã phát hành gần nhất: **v0.17.0** (2026-11-26: API token, API cập nhật chạy nền, `/api/health`, trang `/docs`, Cài đặt dạng danh sách, quản lý thư mục dữ liệu). Trước đó v0.16.0 (thông báo), v0.14.1 (gồm phần chống giới hạn API định làm 0.15.0 — bỏ qua số 0.15.0).
- 0.17.0 đã test thật trên Docker trong sandbox: 18 bộ `tests/docker/` đều đạt (bộ 2 = 41/42, `P4` là điều kiện test đã biết). Chưa thử với Home Assistant / Uptime Kuma thật và máy CasaOS của chủ repo.

### Lộ trình tiếp theo (đã thống nhất với chủ repo)
- ~~0.17 — API token~~: đã xong (v0.17.0).
- **0.18+ — quản lý nhiều máy chủ** (mô hình agent): mỗi máy chạy AppManager; một máy "chính" thêm máy khác bằng địa chỉ + API token, gộp danh sách app, bấm cập nhật/khôi phục từ xa; việc thật vẫn do AppManager từng máy làm; KHÔNG mở Docker socket ra mạng.
- Ý tưởng khác: sao lưu/khôi phục cấu hình AppManager; tìm & tải log container; Podman/GPU/ARM thật/Docker cũ chưa test được trong sandbox (cần chủ repo thử trên máy thật).
