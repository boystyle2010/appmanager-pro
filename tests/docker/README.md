# Bộ test trên Docker thật (cho phiên Claude Code)

Tài liệu này đủ để một phiên mới **dựng lại môi trường và chạy lại toàn bộ test trong ~10 phút chuẩn bị**,
không cần đọc lại lịch sử. Không chạy trong CI. Kết quả lần gần nhất (0.16.0, 2026-11-25; bộ 16 thêm 2026-11-26): mọi bộ đạt,
trừ dòng `P4` của bộ 2 (điều kiện test đã biết, xem bảng).

## 0. Cách các test hoạt động (đọc trước)
- **Hai kiểu test:**
  1. `t_*.py` — Python chạy **từ gốc repo** (`sys.path.insert(0, ".")`), import thẳng `app.core.*`
     (vd. `run_manager.recreate_stream`, `updater.update_app_stream`, `notify.upsert_channel`) và gọi Docker thật
     qua `/var/run/docker.sock`. Mỗi bộ dùng thư mục dữ liệu riêng qua biến môi trường
     `APP_DATA_DIR=$S/ampdataN` (database SQLite, snapshot, sao lưu), `APPDATA_DIR=$S/AppData`,
     `CASAOS_APPS_DIR=$S/casa/apps`. In `PASS/FAIL <mã> <mô tả>` và cuối cùng `SUMMARY đạt / tổng`.
  2. `e2e*.js` — Playwright (Chromium có sẵn, `require('playwright')` chạy được ngay, **không** `playwright install`),
     khổ 390×844, `deviceScaleFactor: 2`. Đăng nhập bằng API rồi điều khiển giao diện qua
     `Alpine.$data(document.body)` (hàm `D(code)`), chụp ảnh vào thư mục truyền ở `argv[2]`.
     Tài khoản test: `admin` / `Test-Passw0rd!x` (tạo bằng `POST /api/auth/setup`, header `Origin` bắt buộc).
- **Biến `S`** = scratchpad của phiên (vd. `/tmp/claude-0/<...>/scratchpad`). Mọi script tham chiếu nhau qua `$S`
  (`S=${S}` ở đầu script) → **phải `export S` và copy các script vào `$S`** trước khi chạy.
- **Image:** Docker Hub ẩn danh bị giới hạn lượt tải → luôn dùng `mirror.gcr.io/library/<image>` (biến `M` trong script).
- **Test servers giữ lại giữa các bộ:** `registry` (:5000), `ntfy` (:8091), `gotify` (:8092). `setup.sh`/`setup2.sh`
  xoá mọi container khác (`grep -vE "^(registry|ntfy|gotify)$"`), vì vậy test đếm số app phải loại 3 cái này.
- **Image AppManager để test tự cập nhật** (`build_amp.sh`): build từ code hiện tại bằng `Dockerfile.test`
  (Python 3.15 slim + docker CLI/compose từ `docker:29.10.0-cli`, cài từ wheel offline vì lúc `docker build` không có mạng)
  → `localhost:5000/amp:1`, `amp:2` (khác `BUILD_TAG`), `amp:bad` (`Dockerfile.bad`: khởi động là chết → thử rollback).
  **Sửa code xong phải chạy lại `build_amp.sh`** thì bộ 6/7/8/10 mới test code mới.
- **AppManager chạy trong container** (`start_amp.sh`, cho bộ 7–8): `--network host` (cổng 8000), truyền proxy của sandbox
  (`HTTPS_PROXY` đọc lúc chạy — cổng có thể đổi) + `SSL_CERT_FILE=/ca.crt` (mount `/root/.ccr/ca-bundle.crt`),
  mount docker.sock, `$S/selfdata2:/app/data`, `$S/AppData`, `$S/casa/apps` cùng đường dẫn; tạo admin xong.
- **Chụp ảnh lẻ** (`e2e7/9/10/11.js`) dùng uvicorn chạy trực tiếp từ repo ở cổng riêng (xem mục 3).
- Giao diện cần CSS: `app/static/css/tailwind.css` phải được build (Tailwind v4) trước khi chụp; **không commit** file này —
  `git checkout app/static/css/tailwind.css` (hoặc `git status` kiểm tra) trước khi commit.

## 1. Chuẩn bị (một lần mỗi phiên)

```bash
export S=/tmp/claude-0/<...>/scratchpad      # scratchpad của phiên hiện tại
cd /home/user/appmanager-pro
pip install -q -r requirements.txt jinja2 pyflakes 2>/dev/null   # để import app.core.* trên máy sandbox

# Docker daemon: khởi động TÁCH khỏi shell (setsid), nếu không sẽ chết khi lệnh Bash kết thúc
pgrep -x dockerd || (setsid nohup dockerd > $S/dockerd.log 2>&1 < /dev/null &); sleep 6; docker info >/dev/null && echo OK

for i in nginx:1.26-alpine nginx:1.27-alpine busybox:1.35 busybox:1.36 busybox:1.38 redis:7.2-alpine registry:2 httpd:2 \
         postgres:16.4-alpine postgres:16.6-alpine python:3.15.2-slim docker:29.10.0-cli; do docker pull -q mirror.gcr.io/library/$i; done
docker pull -q mirror.gcr.io/binwiederhier/ntfy:latest; docker pull -q mirror.gcr.io/gotify/server:latest
docker pull -q mirror.gcr.io/axllent/mailpit:latest; docker pull -q mirror.gcr.io/caronc/apprise:latest   # bộ 21 (mirror có thể báo 'Quota exceeded': đợi ~1 phút rồi tải lại)

# test servers — BẮT BUỘC --restart unless-stopped (bộ 9/10 tắt/bật dockerd)
docker run -d --name registry --restart unless-stopped -p 5000:5000 mirror.gcr.io/library/registry:2
docker run -d --name ntfy --restart unless-stopped -p 8091:80 mirror.gcr.io/binwiederhier/ntfy:latest serve
docker run -d --name gotify --restart unless-stopped -p 8092:80 -e GOTIFY_DEFAULTUSER_PASS=adminpw mirror.gcr.io/gotify/server:latest
sleep 6
APPTOK=$(curl -s -u admin:adminpw -X POST localhost:8092/application -H 'Content-Type: application/json' -d '{"name":"amp"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
CLITOK=$(curl -s -u admin:adminpw -X POST localhost:8092/client -H 'Content-Type: application/json' -d '{"name":"reader"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
echo "$APPTOK $CLITOK" > $S/gotify.tok     # t_notify.py đọc file này

# Tailwind CLI (build CSS cho ảnh chụp)
mkdir -p $S/tw && (cd $S/tw && npm install --silent tailwindcss @tailwindcss/cli)

# wheel offline cho image test (Python 3.15)
mkdir -p $S/ampbuild/ctx/wheels && pip download -q -d $S/ampbuild/ctx/wheels --only-binary=:all: \
  --platform manylinux_2_36_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --platform linux_x86_64 \
  --python-version 3.15 --implementation cp -r requirements.txt
cp requirements.txt LICENSE $S/ampbuild/ctx/ && cp tests/docker/Dockerfile.test $S/ampbuild/ctx/Dockerfile && cp tests/docker/Dockerfile.bad $S/ampbuild/
for f in tests/docker/*; do cp "$f" $S/; done
```
Nếu `requirements.txt` có bản chưa có wheel cho 3.15 → đổi `python:3.15.2-slim` trong `Dockerfile.test` và `--python-version` cho khớp.

## 2. Chạy

```bash
cd /home/user/appmanager-pro
bash $S/run_everything.sh > $S/all.out 2>&1     # chạy NỀN (run_in_background), ~1,5–2 giờ
# theo dõi: grep -E "^===|SUMMARY|FAIL" $S/all.out   (kết thúc khi có dòng FINALDONE)
```
`run_everything.sh` = build Tailwind → `build_amp.sh` → `run_all.sh` (bộ 1–8) → bộ 9–15. Chạy lại vài bộ:
copy dòng tương ứng từ `run_all.sh`/`run_everything.sh` vào một file như `run_redo.sh` (mẫu có sẵn: bộ 2, 7, 15).
Xem chi tiết lỗi một bộ: chạy đúng dòng đó nhưng bỏ `| grep ...`.

| Bộ | Script (chuẩn bị) | Nội dung | Kỳ vọng |
|---|---|---|---|
| 1 | `t_run.py` (`setup.sh`) | docker run: cập nhật, rollback, mạng/IP tĩnh/alias, volume ẩn danh, sidecar `--network container:` | 33/33 |
| 2 | `t_full.py` (`setup2.sh`) | sao lưu/khôi phục docker run + hồi quy compose/CasaOS/trùng tên | 41/42 — `P4` luôn FAIL (image cũ vẫn được app compose dùng nên không bị xoá; bộ 3 kiểm tra đúng việc này) |
| 3 | `t_p4.py` | khôi phục khi image cũ đã bị xoá (tải lại theo digest) | 2 PASS |
| 4 | `t_edit.py` (`setup.sh`) | Edit Config cho container docker run (YAML ↔ cấu hình) | 20/20 |
| 5 | `t_extra.py` (`setup.sh`) | khoá cập nhật/sửa, container dừng, `--rm`, ghim digest, alias, Lịch sử đồng thời | 13/13 |
| 6 | `t_self.py` (`setup2.sh`, cần `build_amp.sh`) | AppManager (docker run / compose) tự cập nhật, rollback với `amp:bad`, sửa chính nó | 16/16 |
| 7 | `e2e5.js` (`setup2.sh` + `start_amp.sh`) | toàn bộ giao diện với AppManager trong container | 16/16 |
| 8 | `e2e6.js` | phần đầu cửa sổ cập nhật hiện phiên bản mới | 1 PASS |
| 9 | `t_recover.py` (+`child_update.py`) | kill tiến trình giữa lúc cập nhật + khởi động lại dockerd → phục hồi lúc khởi động | 8/8 |
| 10 | `t_selfcrash.py` | mất điện khi AppManager tự cập nhật (helper chạy lại, `self-update-progress.json`) | 6/6 |
| 11 | `t_more.py` | registry riêng tư, app chậm, Postgres, macvlan, `--link`, tên dài, gỡ kèm AppData, 120 container | 13/13 (macvlan có thể SKIP) |
| 12 | `t_uninst.py` | gỡ app + image dùng chung | 10/10 |
| 13 | `t_net.py` | giới hạn API (Docker Hub/GitHub giả lập bằng `httpx.MockTransport`) | 12/12 |
| 14 | `t_net_real.py` | tài khoản registry thật (`privreg` :5001, registry:2 + htpasswd, user `tester`/`s3cret`) | 8/8 |
| 15 | `t_notify.py` (`setup.sh`) | thông báo: ntfy/Gotify thật, webhook thật (:8093, HMAC), Telegram/Discord giả lập, cập nhật thật, giờ im lặng, crash-loop, ổ đĩa | 21/21 |
| 16 | `t_datafolders.py` (`setup2.sh`, cần `build_amp.sh`) | thư mục dữ liệu: ẩn docker.sock, kiểm tra, đổi đường dẫn, gỡ, chặn gỡ thư mục chứa compose của AppManager, mở rộng sang thư mục cha | 21/21 |
| 17 | `t_tokens.py` (`setup.sh`) | API token: quyền chỉ đọc / cập nhật / toàn quyền, hạn dùng, giới hạn IP, khoá IP khi sai, cập nhật app thật qua HTTP job, `/api/health`, `/docs`, audit, thông báo bảo mật (uvicorn :8795, webhook :8094) | 39/39 |
| 18 | `e2e12.js` + `e2e13.js` | giao diện 0.17: Cài đặt dạng danh sách, thư mục dữ liệu (AppManager compose :8770), API token + trang tài liệu (uvicorn :8794) | 9/9 + 8/8 |
| 19 | `t_servers.py` (`setup.sh`) | 0.18 nhiều máy chủ: máy chính :8793 + máy phụ HTTP :8792 + HTTPS tự ký :8791 (uvicorn từ repo, cùng Docker), máy giả bản cũ / chuyển hướng :8790, địa chỉ chết :8799; Token sai / chỉ đọc / bị xoá, cập nhật + start/stop/restart thật từ xa, audit 2 máy, bảo mật | 26/26 |
| 20 | `e2e14.js` (+`srv_setup.sh`) | giao diện nhiều máy chủ: Cài đặt → Máy chủ (giải thích giao thức), thêm máy, thanh chọn máy, cập nhật thật từ xa | 7/7 |
| 21 | `t_notify2.py` | 11 kênh thông báo mới: Email qua Mailpit thật (SMTP :1025, xem :8025), Apprise API thật (:8095, cần `-e IPV4_ONLY=yes` vì sandbox không có IPv6) chuyển tiếp tới ntfy thật, Slack/Teams/Google Chat/Mattermost/Matrix/Signal/Bark/Pushover/Pushbullet đúng định dạng API (giả lập `httpx.MockTransport`); tự dựng và xoá Mailpit/Apprise | 18/18 |
| 22 | `e2e15.js` | giao diện chọn kênh (3 nhóm, icon từng app, biểu tượng nền tảng, form Email, mã hoá Bark + chế độ riêng tư) | 13/13 |
| 23 | `t_notify3.py` (cần `pip install cryptography` để đối chiếu) | mã hoá Bark AES-128/192/256-CBC và Webhook AES-256-GCM (giải mã lại bằng thư viện `cryptography`), chế độ riêng tư, kiểm tra khoá / IV | 12/12 |
| 24 | `e2e16.js` (`setup.sh`, uvicorn :8794) | kiểm tra bản mới cho 1 app: dòng trong menu ⋯, nút làm mới trong cửa sổ cập nhật, `POST /api/apps/{tên}/check` với Token Cập nhật / Chỉ đọc | 5/5 |
| 25 | `t_channels.py` | kênh phát hành: dữ liệu Docker Hub thật (glances `latest` có `dev` + biến thể `latest-full`, `latest-full` có `latest` thường nhưng không có `dev`), registry 503/429 không xoá kênh đã biết, container thật `bb-latest` | 12/12 |
| 26 | `t_policy.py` (`setup.sh`) | quy tắc tự cập nhật: mức phiên bản, đợi N ngày (mốc `first_seen`), ngày / giờ riêng, chạy bù, 1 lần / ngày, tắt chung; cập nhật thật bb-none 1.35 → 1.38 | 14/14 |
| 27 | `e2e17.js` (uvicorn :8794) | giao diện quy tắc: phần quy tắc trong cửa sổ cập nhật, dòng "đang giữ lại" trên thẻ, cảnh báo khi tự cập nhật chung tắt | 5/5 |
| 28 | `e2e18.js` (uvicorn :8795) | kênh theo biến thể: glances `latest-full` có thêm `latest` thường (không có `dev`), `latest` có `latest-full` + `dev`, cảnh báo đổi biến thể, nhãn changelog (container busybox gắn tag glances, kênh lấy từ Docker Hub thật) | 6/6 |
| 29 | `e2e19.js` (uvicorn :8796) | trang cũ (Safari giữ tab sau khi AppManager cập nhật) tự tải lại đúng 1 lần theo mã build; HTML `Cache-Control: no-cache`; file tĩnh `?v=<mã build>` | 5/5 |
| 30 | `t_v021.py` (`setup.sh`) | 0.21: log theo khoảng thời gian / tìm (nhiều từ, `-từ`) / lọc mức (khối Traceback đi cùng dòng lỗi) / tải về + audit; Token Chỉ đọc đọc / tải log, không khôi phục được; máy chính :8783 → máy phụ :8782: log, tải log (luồng), danh sách sao lưu, khôi phục thật bb-none + audit 2 máy, Token Chỉ đọc bị 403, tên file lạ bị từ chối; theo dõi máy phụ (2 lần lỗi mới báo, không báo lặp, nhớ qua khởi động lại, báo kết nối lại + thời gian mất); sự kiện mới tự bật cho kênh cũ đúng 1 lần; log có mã màu ANSI (container `lgc`, kiểu Portainer): tìm / lọc trên chữ thật, giữ màu cho giao diện, file tải về không còn mã màu | 33/33 |
| 31 | `e2e20.js` (+`srv_setup.sh`, container `lg` + `lgc`, bản sao lưu bb-none trên máy phụ) | giao diện 0.21: cửa sổ log (trực tiếp + tìm, 1 giờ + Lỗi, số dòng, tải .txt), "Tất cả máy" (thẻ ghi tên máy, tìm theo tên máy), log máy phụ, khôi phục máy phụ (chọn bản → kết quả); log màu ANSI hiện màu thật, không còn ký tự lạ | 13/13 |
| 32 | `t_users.py` (`setup.sh`, uvicorn :8781) | 0.22: tài khoản đầu / cũ là Quản trị; thêm tài khoản (trùng tên mọi kiểu chữ, tên sai, `token:`, mật khẩu ngắn, vai trò lạ bị từ chối); Chỉ xem / Cập nhật: từng API được / bị chặn (compose, lệnh docker run, Token, tài khoản, nhật ký, thông báo, máy chủ), cập nhật thật bằng vai trò Cập nhật; WebSocket theo vai trò (4403); đổi vai trò / khoá / đặt lại mật khẩu thu hồi phiên ngay; luôn 1 Quản trị; đổi mật khẩu của mình chỉ đăng xuất thiết bị khác của mình; Token Toàn quyền không đụng được tài khoản; nhật ký lọc theo người | 25/25 |
| 33 | `e2e21.js` (uvicorn :8797) | giao diện 0.22: Tài khoản & quyền (thêm 2 tài khoản qua giao diện, sửa / khoá), Chỉ xem (không nút cập nhật / thao tác, cửa sổ cập nhật chỉ xem, Cài đặt chỉ còn mục của mình), Cập nhật (có Khởi động lại, không Sửa / Gỡ), khoá tài khoản → trang đang mở bị 401, nhật ký lọc theo người | 10/10 |
| 34 | `t_sso.py` (+`oidc_mock.py` HTTP :8790 / HTTPS tự ký :8789, uvicorn :8780) | 0.23 SSO: cấu hình (Redirect URI, kiểm tra kết nối, không trả Client Secret), đăng nhập đầy đủ (PKCE, Basic / post), tự tạo tài khoản, nhóm → vai trò + đồng bộ mỗi lần đăng nhập (đường dẫn nhóm Keycloak, không phân biệt hoa thường), vai trò mặc định; bị từ chối: state giả, sai aud, hết hạn, sai nonce, sai chữ ký, alg none, người dùng huỷ, ES256 qua HTTP, issuer khác; ES256 qua HTTPS được nhận; chứng chỉ tự ký; sai secret; tài khoản mật khẩu trùng tên (mặc định từ chối, bật gắn thì giữ vai trò cũ); tắt tự tạo; trùng tên khác sub; tên có dấu; nhóm chỉ trong userinfo; userinfo của người khác bị bỏ qua; tài khoản bị khoá; quyền xem cấu hình | 34/34 |
| 35 | `t_sso_keycloak.py` (+`kc-realm.json`, Keycloak 26.4 :8088) | SSO với Keycloak thật: kiểm tra kết nối (scope `groups` Keycloak không có → tự bỏ), đăng nhập qua form thật, chữ ký RS256 thật, nhóm amp-admins / amp-ops / family → Quản trị / Cập nhật / từ chối, sai mật khẩu ở lại Keycloak, nhật ký | 9/9 |
| 36 | `e2e22.js` (+`oidc_mock.py` :8790, uvicorn :8780) | giao diện SSO: trang cài đặt (hướng dẫn, Redirect URI, nhóm → vai trò, Kiểm tra, Lưu), trang đăng nhập có nút "Đăng nhập bằng Authentik" + lỗi tiếng Việt, đăng nhập SSO tới trang chính, Bảo mật của tài khoản SSO, nhãn SSO trong danh sách tài khoản (+ biểu tượng nhà cung cấp, tab Đăng ký có "Đăng ký bằng …" khi SSO tự tạo tài khoản) | 11/11 |
| 37 | `t_config.py` (`setup.sh`, uvicorn :8778 máy A + :8777 máy B) | 0.24: tóm tắt cấu hình, mật khẩu ngắn bị từ chối, xuất `.ampbak` (scrypt + AES-256-GCM, không đọc được bí mật nào trong file); sai mật khẩu / không phải file sao lưu / sửa phần đầu / sửa dữ liệu / định dạng mới hơn bị từ chối; khôi phục một phần (chỉ thông báo); khôi phục toàn bộ sang máy mới: đăng nhập bằng mật khẩu + 2FA của máy A (mã đã dùng bị chặn dùng lại), Vai trò, Token của A dùng được trên B, máy chủ, SSO, quy tắc từng app, cài đặt chung, registry → `docker-config`; bản tự lưu trước khi khôi phục (2 bản, tải về, mở được, hoàn tác); file không có Quản trị bị từ chối; Chỉ xem / Token Toàn quyền bị 403 | 27/27 |
| 38 | `e2e23.js` (uvicorn :8776) | giao diện sao lưu cấu hình: trang giải thích + từng phần có số mục, tạo & tải file, sai mật khẩu, xem trước, chỉ khôi phục API Token, hộp xác nhận, kết quả + bản tự lưu | 8/8 |
| 39 | `t_webpush.py` (uvicorn :8774, push giả HTTPS :8775) | 0.25 Web Push: véc-tơ RFC 8291 / RFC 6979, đối chiếu P-256 với thư viện cryptography, điểm ngoài đường cong bị từ chối; `/sw.js` + manifest; khoá VAPID cố định; đăng ký sai bị từ chối; kênh Web Push tự tạo; đăng ký lại không trùng; giải mã nội dung bằng cryptography + kiểm chữ ký VAPID; Gửi thử qua kênh; 410 → tự xoá thiết bị; xoá; Chỉ xem bị 403; kiểu thông báo của app điện thoại (không emoji / "•", tiêu đề gọn, gộp nhiều app + "+N more", mở danh sách cập nhật, số trên biểu tượng app) | 25/25 |
| 40 | `e2e24.js` (+`push_mock.py` :8775, uvicorn :8773 trên 0.0.0.0) | giao diện Web Push: mở qua http IP mạng → cần HTTPS + hướng dẫn Tailscale / reverse proxy / Cloudflare Tunnel; iPhone chưa thêm vào MH chính; localhost bật được; danh sách thiết bị, Gửi thử, xoá có xác nhận (đăng ký push thật trong Chromium headless bị từ chối nên thiết bị thêm qua API) | 9/9 |
| 41 | `e2e25.js` (uvicorn :8771 + máy chưa có tài khoản :8768) | trang đăng nhập "phòng máy": tắt thì ô đăng nhập ẩn, bấm nút nguồn máy chủ (LED + máy chiếu, ô đăng nhập hiện), đổi màu ánh sáng, đăng nhập thật, lần sau tự bật, khổ máy tính, tắt JavaScript vẫn đăng nhập được, tab Đăng nhập / Đăng ký, gợi ý SSO, chùm sáng cuộn theo máy chiếu, thu nhỏ cửa sổ không còn dư khoảng trống; lần đầu: vẫn trang Đăng nhập / Đăng ký, đăng nhập báo "chưa có tài khoản", tạo Quản trị ở tab Đăng ký | 13/13 |
| 42 | `e2e26.js` (uvicorn :8769) | Cài đặt toàn màn hình kiểu iOS: tiêu đề lớn ngang nút X (không còn nút i), thẻ Chế độ tối, nhóm có nhãn chữ in hoa + giá trị hiện tại, trang Ngôn ngữ, thanh "N thay đổi · Huỷ · Lưu"; trang Giao diện: màu chủ đạo (đổi biến màu Tailwind), cỡ chữ, kiểu bo góc, kiểu icon, biểu tượng app (link apple-touch-icon + `/manifest.json?icon=`), xem trước ngay, Huỷ trả lại, Lưu giữ sau khi tải lại; trang Bộ nhớ đệm (giải thích "Nên xoá khi", số mục trên máy chủ, xác nhận trước khi xoá, xoá bộ đệm mạng, đặt lại Giao diện, "Xoá & tải lại" giữ đăng nhập + Giao diện) | 25/25 |
| 43 | `t_setup.py` (uvicorn :8767) | tạo Quản trị đầu tiên chỉ khi máy chưa có tài khoản: 12 yêu cầu cùng lúc → đúng 1 thành công (`BEGIN IMMEDIATE`), sau đó luôn bị từ chối (kể cả đã đăng nhập), trang đăng nhập hết form tạo Quản trị, `RESET_AUTH=true` mở lại một lần | 8/8 |

Fixture: `setup.sh` — `web` (nginx 1.26, 2 mạng, IP tĩnh 172.30.0.50, alias, volume tên + ẩn danh, bind `$S/bind`
chứa `hello-from-bind`, healthcheck), `bb-sidecar` (`--network container:web`), `bb-fail` (bản 1.36 sẽ chết → rollback),
`bb-stopped`, `bb-none`, `ext-swarm` (nhãn Swarm → external), `redis` + `redis-amp-old` (rác cần ẩn), stack compose `$S/stack/demo`.
`setup2.sh` — `$S/AppData/{stableapp,cmpweb,casaapp,cfgapp,cfgmig}`, CasaOS `$S/casa/apps/{casaapp,oldcasa}`,
docker run trùng tên project compose (`stableapp`), app có file cài đặt + media/log (`cfgapp`), app "chuyển đổi dữ liệu rồi lỗi" (`cfgmig`).

## 3. Ảnh chụp giao diện (gửi chủ repo)
Chạy uvicorn trực tiếp từ repo (CSS đã build), tạo admin, rồi chạy script:
```bash
cd /home/user/appmanager-pro && rm -rf $S/ampui && mkdir -p $S/ampui $S/shots
(APP_DATA_DIR=$S/ampui APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps nohup python -m uvicorn app.main:app --port 8797 > $S/uvui.log 2>&1 &); sleep 6
curl -s -X POST localhost:8797/api/auth/setup -H 'Content-Type: application/json' -H 'Origin: http://localhost:8797' \
  -d '{"username":"admin","password":"Test-Passw0rd!x","confirm_password":"Test-Passw0rd!x"}'
node $S/e2e9.js $S/shots
```
Cổng cố định trong từng script: `e2e7.js` (gỡ app) :8798, `e2e9.js`/`e2e10.js` (giới hạn API) :8797,
`e2e12.js` (9 kiểm tra + ảnh: Cài đặt dạng danh sách, Thiết lập = menu cũ, bấm ô / Nhập tay = popup mới, thêm thật 1 thư mục, ô dung lượng sao lưu; chạy `$S/df_setup.py` = phần đầu `t_datafolders.py` tới trước `D3`, rồi `node $S/e2e12.js $S/shots http://localhost:8770 $S/OtherData`), `e2e11.js` (tab Thông báo) :8796 — cần `python $S/hook_srv.py $S/hook.log &` (webhook :8094) và chạy `node $S/e2e11.js $S/shots $S/hook.log` (tham số 2 = file log webhook).
Ảnh mới: viết `e2eN.js` theo mẫu `e2e9.js` (login bằng `ctx.request.post`, `D(...)` để mở popup/tab, `p.screenshot`).
Gửi ảnh bằng SendUserFile; dừng uvicorn sau khi xong (`pkill -f "uvicorn app.main:app --port 879"`).

## 4. Lưu ý môi trường sandbox (đã gặp)
- Gotify trả 401 ở bộ 15 sau khi dockerd khởi động lại (container không có ổ lưu → mất token): chạy lại 3 dòng `APPTOK=` / `CLITOK=` / `echo … > $S/gotify.tok` ở mục 1.
- Keycloak (bộ 35) đặt cookie `Secure`; httpx không gửi cookie Secure qua http như trình duyệt (trình duyệt coi localhost là an toàn) → test tự bỏ cờ Secure trước khi gửi form.
- `pkill -f "mẫu"` trong `sh("...; lệnh khác")` tự khớp chính shell đó và giết nó (lệnh sau không chạy): dùng mẫu `[x]` (vd `"oidc_mock[.]py"`) hoặc gọi `sh()` riêng.
- `dockerd` chết khi khởi động không có `setsid` → mọi test lỗi "Cannot connect to the Docker daemon": chạy lại lệnh ở mục 1.
- Bộ 9/10 tắt/bật dockerd: container không có `--restart` sẽ dừng (đã gặp: ntfy/Gotify dừng làm bộ 15 lỗi).
- Cổng proxy (`HTTPS_PROXY`) có thể đổi giữa các lần: `start_amp.sh` đọc lúc chạy; AppManager cũ trong container dùng proxy cũ → chạy lại `start_amp.sh`.
- `grep` trong pipeline giữ bộ đệm → file kết quả chỉ có dữ liệu khi từng bộ xong; đừng tưởng bị treo.
- `ntfy.sh` / Telegram / Discord công khai bị proxy chặn → dùng ntfy/Gotify tự dựng; Telegram/Discord giả lập trong test.
- Docker Hub `429 Too Many Requests` → đổi image sang `mirror.gcr.io/library/...`.
- Hết dung lượng: `docker system prune -af --volumes` (sẽ mất image đã pull, registry vẫn còn nếu đang chạy) và xoá `$S/ampdata*`.
