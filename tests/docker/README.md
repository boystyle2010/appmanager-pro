# Bộ test trên Docker thật (cho phiên Claude Code)

Tài liệu này đủ để một phiên mới **dựng lại môi trường và chạy lại toàn bộ test trong ~10 phút chuẩn bị**,
không cần đọc lại lịch sử. Không chạy trong CI. Kết quả lần gần nhất (0.16.0, 2026-11-25): mọi bộ đạt,
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
`e2e11.js` (tab Thông báo) :8796 — cần `python $S/hook_srv.py $S/hook.log &` (webhook :8094).
Ảnh mới: viết `e2eN.js` theo mẫu `e2e9.js` (login bằng `ctx.request.post`, `D(...)` để mở popup/tab, `p.screenshot`).
Gửi ảnh bằng SendUserFile; dừng uvicorn sau khi xong (`pkill -f "uvicorn app.main:app --port 879"`).

## 4. Lưu ý môi trường sandbox (đã gặp)
- `dockerd` chết khi khởi động không có `setsid` → mọi test lỗi "Cannot connect to the Docker daemon": chạy lại lệnh ở mục 1.
- Bộ 9/10 tắt/bật dockerd: container không có `--restart` sẽ dừng (đã gặp: ntfy/Gotify dừng làm bộ 15 lỗi).
- Cổng proxy (`HTTPS_PROXY`) có thể đổi giữa các lần: `start_amp.sh` đọc lúc chạy; AppManager cũ trong container dùng proxy cũ → chạy lại `start_amp.sh`.
- `grep` trong pipeline giữ bộ đệm → file kết quả chỉ có dữ liệu khi từng bộ xong; đừng tưởng bị treo.
- `ntfy.sh` / Telegram / Discord công khai bị proxy chặn → dùng ntfy/Gotify tự dựng; Telegram/Discord giả lập trong test.
- Docker Hub `429 Too Many Requests` → đổi image sang `mirror.gcr.io/library/...`.
- Hết dung lượng: `docker system prune -af --volumes` (sẽ mất image đã pull, registry vẫn còn nếu đang chạy) và xoá `$S/ampdata*`.
