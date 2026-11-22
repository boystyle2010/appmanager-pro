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
  - `app_backup.py` (sao lưu/khôi phục `/DATA/AppData/<app>`), `system_prune.py`, `system_monitor.py`.
- Frontend: Alpine.js — `app/templates/index.html` (markup), `app/static/js/app.js` (logic), `app/static/js/i18n.js` (EN/VI, **mọi key phải có ở cả hai ngôn ngữ**), `app/templates/auth.html`.
- CSS: **Tailwind v4** biên dịch lúc build image từ `app/static/css/tailwind.input.css` (stage `css` trong Dockerfile). `glass.css` và khối `<style>` trong `index.html` nằm trong `@layer components` để class tiện ích Tailwind luôn thắng. File `tailwind.css` là sản phẩm build, không commit.
- Thư viện JS (Alpine, marked, DOMPurify) và font được tải vào image bởi `scripts/fetch_vendor.py`, có CDN dự phòng trong HTML.

## Quy tắc quan trọng
- **Không sửa tay phiên bản** trong `Dockerfile`, `requirements.txt`, `scripts/fetch_vendor.py`, link CDN dự phòng, `APP_VERSION`, `CHANGELOG.md` — bot (`scripts/auto_update.py`) quản lý và tự commit. Luôn `git pull` trước khi sửa.
- Changelog **chỉ** ghi thay đổi thành phần nền. Ghi chú tự viết cho bản kế tiếp → thêm dòng `- ...` vào `RELEASE_NOTES_NEXT.md` (không tự tạo release).
- Starlette 1.0: dùng `templates.TemplateResponse(request, "x.html", {...})`.
- Mọi POST/PUT/PATCH/DELETE `/api/*` và WebSocket phải qua kiểm tra Origin (`origin_allowed`). Ghi audit log (`audit(...)`) cho hành động quan trọng.
- Tailwind v4: dùng `shadow-xs` (thay `shadow-sm` cũ), `backdrop-blur-xs`, `bg-linear-to-*`.

## Kiểm tra trước khi push
```bash
python -m compileall -q app scripts
python scripts/check_project.py          # import nội bộ, Jinja, file tĩnh (cần jinja2)
node --check app/static/js/app.js && node --check app/static/js/i18n.js
bash scripts/verify.sh amp-test smoke    # cần Docker: build image, chạy uvicorn, smoke test
```

## CI (`.github/workflows/release.yml`)
- Chạy hằng ngày, khi push `main` (bỏ qua thay đổi chỉ `*.md`/LICENSE), hoặc bấm tay (`force_release`, `version`).
- Bot nâng **mọi** thành phần lên bản mới nhất (kể cả major) → build & chạy thử thật (uvicorn + smoke test + build arm64) → hỏng thì lùi về nâng cùng major → commit qua GitHub API (có chữ ký) → build multi-arch, ký attestation, quét Trivy → tạo Release.
- Bot không sửa được file trong `.github/workflows/` (giới hạn của GITHUB_TOKEN); các action trong workflow phải nâng tay. Trivy ghim theo commit SHA.

## Việc còn mở
- Trivy: `golang.org/x/net` v0.60.0 trong `docker-compose` (CVE-2026-78661, tạm bỏ qua trong `.trivyignore` tới 2027-02-28) — chờ Docker Compose phát hành bản dùng x/net ≥ 0.62.0 (v5.8.0 và nhánh main ngày 2026-11-18 vẫn là v0.60.0).
- Ý tưởng tính năng: thông báo Telegram/Discord/ntfy; loại trừ/ghim app khỏi Update All; API token cho tự động hoá; sao lưu/khôi phục cấu hình AppManager; tìm & tải log container.
