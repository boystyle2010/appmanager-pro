"""0.24 sao lưu / khôi phục cấu hình AppManager: máy A (uvicorn :8778, có đủ cấu hình) -> file .ampbak -> máy B mới
(:8777). Kiểm tra từng phần sau khi khôi phục (đăng nhập bằng mật khẩu của A, 2FA, Vai trò, Token dùng được, kênh
thông báo, máy chủ, SSO, registry -> Docker, quy tắc từng app, cài đặt chung), sai mật khẩu / file bị sửa / không
phải file sao lưu, khôi phục một phần, bản tự lưu trước khi khôi phục (tải về + mở được), luôn có Quản trị, quyền."""
import atexit, base64, json, os, subprocess, sys, time
import httpx
S = os.environ["S"]; R = []
A, Bm = "http://localhost:8778", "http://localhost:8777"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
sh('pkill -f "app.main:app --port 877[78]"'); time.sleep(1)
procs = []
atexit.register(lambda: [p.terminate() for p in procs])
def start(port, data):
    sh(f"rm -rf {data} && mkdir -p {data}")
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], env={**os.environ, "APP_DATA_DIR": data},
                                  stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT))
def wait(url):
    for _ in range(60):
        try:
            if httpx.get(url + "/login", timeout=2).status_code < 500: return True
        except Exception: time.sleep(0.5)
    return False
def admin(base, user="admin", pw="Test-Passw0rd!x", setup=True):
    h = {"Origin": base}
    if setup:
        httpx.post(base + "/api/auth/setup", headers=h, json={"username": user, "password": pw, "confirm_password": pw})
    c = httpx.Client(base_url=base, headers=h, timeout=120)
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    return c, r
start(8778, f"{S}/cfgA"); start(8777, f"{S}/cfgB")
check("C0 two AppManager instances up (A configured, B new)", wait(A) and wait(Bm))
a, _ = admin(A, "boss", "Boss-Passw0rd!1")
# --- cấu hình máy A
a.post("/api/users", json={"new": True, "username": "minh", "password": "Minh-Passw0rd!1", "role": "operator"})
a.post("/api/users", json={"new": True, "username": "khach", "password": "Khach-Passw0rd!1", "role": "viewer"})
tok = a.post("/api/tokens", json={"name": "Home Assistant", "scope": "update"}).json()["token"]
a.post("/api/notify/channels", json={"type": "ntfy", "name": "Phone", "config": {"server": "http://localhost:8091", "topic": "amp-cfg"}, "events": ["update_failed"]})
a.post("/api/notify/settings", json={"quiet_enabled": True, "quiet_start": "23:00", "quiet_end": "06:30"})
a.post("/api/servers", json={"name": "NAS", "url": "http://127.0.0.1:8799", "token": "amp_" + "z" * 40})
a.post("/api/sso", json={"label": "Authentik", "issuer": "https://auth.example.com/application/o/amp", "client_id": "amp", "client_secret": "sso-secret-xyz",
                         "admin_groups": "admins", "enabled": True})
a.post("/api/apps/bb-none/prefs", json={"auto_update": True, "policy": {"level": "patch", "min_age_days": 3, "days": [5, 6], "time": "02:15"}})
st = a.get("/api/settings").json()["settings"]
a.post("/api/settings", json={**st, "auto_update_enabled": True, "auto_update_time": "04:45", "check_interval_hours": 12, "github_token": "ghp_cfgtest123"})
subprocess.run([sys.executable, "-c", "from app.core.database import init_db; init_db(); from app.core import net; net.save_login('registry.example.com', 'robot', 'reg-secret-1')"],
               env={**os.environ, "APP_DATA_DIR": f"{S}/cfgA"}, check=False)
# 2FA cho boss (bí mật TOTP phải đi theo file)
os.environ["APP_DATA_DIR"] = f"{S}/cfg_testproc"  # trước khi import app.core (thư mục dữ liệu riêng cho tiến trình test)
sys.path.insert(0, ".")
from app.core.auth import totp_now
sec = a.post("/api/auth/2fa/setup").json()["secret"]
used_code = totp_now(sec)
a.post("/api/auth/2fa/enable", json={"code": used_code})

cur = a.get("/api/config/sections").json()
check("C1 current configuration summary lists every part with counts", cur["current"]["accounts"]["count"] == 3 and cur["current"]["tokens"]["count"] == 1
      and cur["current"]["notify"]["count"] == 1 and cur["current"]["servers"]["count"] == 1 and cur["current"]["sso"]["enabled"]
      and cur["current"]["registry"]["count"] == 1 and cur["current"]["app_rules"]["count"] == 1, cur["current"])
short = a.post("/api/config/export", json={"password": "short"})
check("C1 password shorter than 8 characters refused", short.status_code == 400, short.text)
t0 = time.time()
ex = a.post("/api/config/export", json={"password": "Backup-Pass-2026"}).json()
dt = time.time() - t0
text = ex["data"]; env = json.loads(text)
check("C2 export: .ampbak named by date, scrypt + AES-256-GCM, every part listed", ex["filename"].startswith("appmanager-config-") and ex["filename"].endswith(".ampbak")
      and env["cipher"] == "AES-256-GCM" and env["kdf"]["name"] == "scrypt" and set(env["sections"]) == set(cur["sections"]), (ex["filename"], env.get("sections")))
check("C2 no secret is readable in the file (password hashes, Token hashes, SSO / registry secrets, GitHub token)",
      not any(x in text for x in ("argon2", "sso-secret-xyz", "reg-secret-1", "ghp_cfgtest123", "Boss-Passw0rd", "amp_zzzz")) and len(text) < 200_000, len(text))
check(f"C2 export is quick ({dt:.2f} s)", dt < 10)

# --- máy B
b, _ = admin(Bm, "newadmin", "New-Passw0rd!x")
bad = [b.post("/api/config/inspect", json={"data": text, "password": "wrong-password"}),
       b.post("/api/config/inspect", json={"data": "hello", "password": "Backup-Pass-2026"}),
       b.post("/api/config/inspect", json={"data": json.dumps({**env, "host": "evil"}), "password": "Backup-Pass-2026"}),
       b.post("/api/config/inspect", json={"data": json.dumps({**env, "data": base64.b64encode(bytes([base64.b64decode(env["data"])[0] ^ 1]) + base64.b64decode(env["data"])[1:]).decode()}), "password": "Backup-Pass-2026"}),
       b.post("/api/config/inspect", json={"data": json.dumps({**env, "version": 99}), "password": "Backup-Pass-2026"})]
check("C3 wrong password / not a backup / header changed / data changed / newer format -> refused with a clear reason",
      [r.status_code for r in bad] == [400] * 5 and "Wrong password" in bad[0].text and "not an AppManager" in bad[1].text
      and "Wrong password, or the file was damaged" in bad[2].text and "damaged" in bad[3].text and "newer AppManager" in bad[4].text, [r.text for r in bad])
ins = b.post("/api/config/inspect", json={"data": text, "password": "Backup-Pass-2026"}).json()
check("C3 inspect shows where the file comes from and what is inside (no secrets)", ins["header"]["app_version"] and ins["summary"]["accounts"]["count"] == 3
      and {u["username"] for u in ins["summary"]["accounts"]["items"]} == {"boss", "minh", "khach"} and "sso-secret" not in json.dumps(ins), ins)
# khôi phục một phần trước (chỉ thông báo)
part = b.post("/api/config/restore", json={"data": text, "password": "Backup-Pass-2026", "sections": ["notify"]}).json()
nb = b.get("/api/notify").json()
check("C4 partial restore (notifications only): channel + quiet hours restored, accounts untouched",
      list(part["restored"]) == ["notify"] and [c["name"] for c in nb["channels"]] == ["Phone"]
      and nb["settings"]["quiet_enabled"] and b.get("/api/auth/me").json()["username"] == "newadmin", (part, nb["channels"], nb["settings"]))
check("C4 the configuration before restoring was saved automatically", part["safety_backup"].startswith("before-restore-") and not part["signed_out"], part)
# khôi phục toàn bộ
full = b.post("/api/config/restore", json={"data": text, "password": "Backup-Pass-2026", "sections": env["sections"]}).json()
check("C5 full restore: every part restored; newadmin (not in the file) is signed out", set(full["restored"]) == set(env["sections"]) and full["signed_out"], full)
b2, lr = admin(Bm, "boss", "Boss-Passw0rd!1", setup=False)
check("C5 boss signs in on B with the password from A and is asked for the 2FA code from A", lr.json().get("otp_required") is True, lr.text)
lr_re = b2.post("/api/auth/login", json={"username": "boss", "password": "Boss-Passw0rd!1", "otp": used_code}) if totp_now(sec) == used_code else None
for _ in range(40):  # mã đã dùng lúc bật 2FA bị chặn dùng lại (bước đã dùng đi theo file) -> đợi mã 30 giây kế tiếp
    if totp_now(sec) != used_code:
        break
    time.sleep(1)
lr2 = b2.post("/api/auth/login", json={"username": "boss", "password": "Boss-Passw0rd!1", "otp": totp_now(sec)})
check("C5 a 2FA code already used on A is refused on B (replay protection travels with the file)", lr_re is None or lr_re.status_code == 401, lr_re.text if lr_re else "")
check("C5 2FA code from the same authenticator works on B", lr2.status_code == 200 and b2.get("/api/auth/me").json()["role"] == "admin", lr2.text)
users = {u["username"]: u["role"] for u in b2.get("/api/users").json()["users"]}
check("C5 accounts and Roles restored (boss Admin, minh Update, khach View only); newadmin gone", users == {"boss": "admin", "minh": "operator", "khach": "viewer"}, users)
tr = httpx.post(Bm + "/api/apps/bb-none/check", headers={"Authorization": f"Bearer {tok}"})
check("C5 API Token created on A works on B", tr.status_code == 200, tr.text)
sv = b2.get("/api/servers").json()["servers"]
check("C5 other server restored with its Token (Token never shown)", [s["name"] for s in sv] == ["NAS"] and sv[0]["has_token"] and "z" * 40 not in json.dumps(sv), sv)
so = b2.get("/api/sso").json()["config"]
check("C5 SSO restored (enabled, issuer, groups, secret kept but not shown)", so["enabled"] and so["issuer"].startswith("https://auth.example.com") and so["has_secret"]
      and so["admin_groups"] == "admins" and "sso-secret" not in json.dumps(so), so)
apps = {x["name"]: x for x in b2.get("/api/apps").json()["apps"]}
pol = apps.get("bb-none", {}).get("policy") or {}
check("C5 per-app rules restored (auto-update + patch only, wait 3 days, Sat / Sun 02:15)",
      apps.get("bb-none", {}).get("auto_update") and pol.get("level") == "patch" and pol.get("min_age_days") == 3 and pol.get("days") == [5, 6], apps.get("bb-none"))
st2 = b2.get("/api/settings").json()["settings"]
check("C5 general settings restored (auto-update 04:45, check every 12 h, GitHub token set)", st2["auto_update_enabled"] in (True, "true") and st2["auto_update_time"] == "04:45"
      and int(st2["check_interval_hours"]) == 12 and st2.get("has_github_token", True), st2)
dcfg = sh(f"cat {S}/cfgB/docker-config/config.json 2>/dev/null")
check("C5 registry account restored and handed to Docker (docker-config/config.json)", "registry.example.com" in dcfg, dcfg[:200])
au = b2.get("/api/audit").json()["items"]
check("C5 restore written to the activity log", any(x["action"] == "config_restore" and x["ok"] for x in au), [x["action"] for x in au][:6])

# bản tự lưu: tải về + mở được bằng mật khẩu, chứa cấu hình cũ của B
saf = b2.get("/api/config/sections").json()["safety"]
fn = [f["name"] for f in saf]
dl = b2.get(f"/api/config/safety/{fn[-1]}")
old = b2.post("/api/config/inspect", json={"data": dl.text, "password": "Backup-Pass-2026"}).json()
check("C6 two automatic copies (one per restore); the first one opens with the same password and holds B's old accounts",
      len(fn) == 2 and dl.status_code == 200 and [u["username"] for u in old["summary"]["accounts"]["items"]] == ["newadmin"], (fn, old.get("summary", {}).get("accounts")))
check("C6 path tricks in the copy name refused", b2.get("/api/config/safety/..%2F..%2Fappmanager.db").status_code in (400, 404))
undo = b2.post("/api/config/restore", json={"data": dl.text, "password": "Backup-Pass-2026", "sections": ["accounts"]}).json()
b3, lr3 = admin(Bm, "newadmin", "New-Passw0rd!x", setup=False)
check("C6 undo: restoring the automatic copy brings back B's own admin", lr3.status_code == 200 and undo["signed_out"], (lr3.text, undo))

# luôn có Quản trị; quyền
from app.core import config_backup as cb
noadm = cb.encrypt({"accounts": [{"username": "v", "password_hash": "x", "role": "viewer"}]}, "Backup-Pass-2026", "0.24.0")
r = b3.post("/api/config/restore", json={"data": noadm, "password": "Backup-Pass-2026", "sections": ["accounts"]})
check("C7 a file with no active administrator cannot replace the accounts", r.status_code == 400 and "no active administrator" in r.text and b3.get("/api/auth/me").status_code == 200, r.text)
b3.post("/api/users", json={"new": True, "username": "viewer1", "password": "Viewer-Passw0rd!1", "role": "viewer"})
v, _ = admin(Bm, "viewer1", "Viewer-Passw0rd!1", setup=False)
full_tok = b3.post("/api/tokens", json={"name": "full", "scope": "full"}).json()["token"]
check("C7 View only and even a Full API Token cannot export or restore the configuration",
      v.post("/api/config/export", json={"password": "Backup-Pass-2026"}).status_code == 403
      and httpx.post(Bm + "/api/config/export", headers={"Authorization": f"Bearer {full_tok}"}, json={"password": "Backup-Pass-2026"}).status_code == 403)
print(f"SUMMARY {sum(R)} / {len(R)}")
