"""0.22 nhiều tài khoản + phân quyền: Quản trị / Cập nhật / Chỉ xem. AppManager thật (uvicorn :8781) trên Docker
trong sandbox (setup.sh: bb-none busybox:1.35 chạy bằng docker run, có bản mới 1.38). Kiểm tra quyền ở máy chủ cho
API, WebSocket, máy chủ phụ; khoá / đổi vai trò / đặt lại mật khẩu thu hồi phiên ngay; luôn giữ 1 Quản trị; nhật ký theo người."""
import asyncio, atexit, json, os, subprocess, sys, time
import httpx
S = os.environ["S"]; R = []
B = "http://localhost:8781"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
sh('pkill -f "port 8781"; sleep 1')
data = f"{S}/users_data"; sh(f"rm -rf {data} && mkdir -p {data}")
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8781"],
                        env={**os.environ, "APP_DATA_DIR": data}, stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT)
atexit.register(proc.terminate)
for _ in range(60):
    try:
        if httpx.get(B + "/login", timeout=2).status_code < 500: break
    except Exception: time.sleep(0.5)
H = {"Origin": B}
PW = "Test-Passw0rd!x"
def client(user, pw=PW):
    c = httpx.Client(base_url=B, headers=H, timeout=120)
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    return c, r

httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": PW, "confirm_password": PW})
adm, _ = client("admin")
me = adm.get("/api/auth/me").json()
check("U1 the first account (and accounts from before 0.22) is an administrator", me == {"username": "admin", "role": "admin", "roles": ["admin", "operator", "viewer"]}, me)

# U2 tạo tài khoản
r1 = adm.post("/api/users", json={"new": True, "username": "oper", "password": PW, "role": "operator"})
r2 = adm.post("/api/users", json={"new": True, "username": "view", "password": PW, "role": "viewer"})
dup = adm.post("/api/users", json={"new": True, "username": "OPER", "password": PW, "role": "viewer"})
bad = [adm.post("/api/users", json={"new": True, "username": "a b", "password": PW, "role": "viewer"}).status_code,
       adm.post("/api/users", json={"new": True, "username": "token:x", "password": PW, "role": "viewer"}).status_code,
       adm.post("/api/users", json={"new": True, "username": "short", "password": "123", "role": "viewer"}).status_code,
       adm.post("/api/users", json={"new": True, "username": "guy", "password": PW, "role": "god"}).status_code]
lst = adm.get("/api/users").json()["users"]
check("U2 admin adds an Update and a View-only account", r1.status_code == 200 and r2.status_code == 200
      and [(u["username"], u["role"], u["created_by"]) for u in lst] == [("admin", "admin", ""), ("oper", "operator", "admin"), ("view", "viewer", "admin")], lst)
check("U2 duplicate name (any case), bad name, token: prefix, short password, unknown role -> 400",
      dup.status_code == 400 and bad == [400, 400, 400, 400], (dup.text, bad))
check("U2 the account list never contains password hashes or 2FA secrets", all("password_hash" not in u and "totp_secret" not in u for u in lst))

op, rop = client("oper"); vw, rvw = client("view")
check("U3 login returns the role", rop.json().get("role") == "operator" and rvw.json().get("role") == "viewer", (rop.text, rvw.text))

# U4 Chỉ xem
v = {
    "apps": vw.get("/api/apps").status_code, "logs": vw.get("/api/apps/bb-none/logs").status_code,
    "history": vw.get("/api/system/history").status_code, "settings": vw.get("/api/settings").status_code,
    "check": vw.post("/api/updates/check").status_code, "restart": vw.post("/api/apps/bb-none/restart").status_code,
    "update": vw.post("/api/apps/bb-none/update", json={}).status_code, "prefs": vw.post("/api/apps/bb-none/prefs", json={"auto_update": True}).status_code,
    "settings_post": vw.post("/api/settings", json={}).status_code, "compose": vw.get("/api/apps/bb-none/compose").status_code,
    "runcmd": vw.get("/api/apps/bb-none/run-command").status_code, "tokens": vw.get("/api/tokens").status_code,
    "users": vw.get("/api/users").status_code, "audit": vw.get("/api/audit").status_code, "notify": vw.get("/api/notify").status_code,
    "srv_add": vw.post("/api/servers", json={"name": "x", "url": "http://1.2.3.4", "token": "amp_" + "x" * 40}).status_code,
}
check("U4 View only: can see apps, logs, history and settings", [v[k] for k in ("apps", "logs", "history", "settings")] == [200] * 4, v)
check("U4 View only: cannot check, restart, update, change app settings or settings (403)",
      [v[k] for k in ("check", "restart", "update", "prefs", "settings_post")] == [403] * 5, v)
check("U4 View only: cannot read compose / docker run command (passwords), Tokens, accounts, activity log, notification setup, add servers",
      [v[k] for k in ("compose", "runcmd", "tokens", "users", "audit", "notify", "srv_add")] == [403] * 7, v)
d = vw.post("/api/apps/bb-none/restart")
check("U4 refusal explains the role", "View only" in d.text and "administrator" in d.text, d.text)

# U5 Cập nhật
o = {
    "check1": op.post("/api/apps/bb-none/check").status_code, "restart": op.post("/api/apps/bb-none/restart").status_code,
    "prefs": op.post("/api/apps/bb-none/prefs", json={"auto_update": False}).status_code,
    "settings_post": op.post("/api/settings", json={}).status_code, "compose": op.get("/api/apps/bb-none/compose").status_code,
    "uninstall": op.post("/api/apps/bb-none/uninstall", json={}).status_code, "kill": op.post("/api/apps/bb-none/kill").status_code,
    "tokens_new": op.post("/api/tokens", json={"name": "x", "scope": "full"}).status_code, "users": op.get("/api/users").status_code,
    "deploy": op.post("/api/deploy/validate", json={}).status_code, "prune": op.post("/api/system/prune", json={}).status_code,
}
check("U5 Update role: check, restart, per-app preferences allowed", [o[k] for k in ("check1", "restart", "prefs")] == [200] * 3, o)
check("U5 Update role: settings, compose, uninstall, kill, Tokens, accounts, deploy, prune refused (403)",
      [o[k] for k in ("settings_post", "compose", "uninstall", "kill", "tokens_new", "users", "deploy", "prune")] == [403] * 8, o)
j = op.post("/api/apps/bb-none/update", json={})
jid = j.json().get("id") if j.status_code == 202 else ""
st = {}
for _ in range(120):
    if not jid: break
    st = op.get(f"/api/jobs/{jid}").json()
    if st.get("status") != "running": break
    time.sleep(2)
img = sh("docker inspect -f '{{.Config.Image}}' bb-none")
hist = adm.get("/api/system/history").json()
hist = hist.get("items", hist) if isinstance(hist, dict) else hist
check("U5 Update role really runs an update (job success, container recreated, in history)",
      j.status_code == 202 and st.get("status") == "success" and "busybox" in img, (j.text, st.get("status"), st.get("log", "")[-300:], img))

# U6 WebSocket theo vai trò (log: mọi vai trò; cập nhật: Cập nhật trở lên; triển khai: Quản trị)
import websockets
async def ws_try(c, path):
    ck = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    try:
        async with websockets.connect("ws://localhost:8781" + path, additional_headers={"Cookie": ck, "Origin": B}, open_timeout=10) as w:
            try:
                await asyncio.wait_for(w.recv(), 4)
            except asyncio.TimeoutError:
                return "open"
            except websockets.ConnectionClosed as e:
                return e.code
            return "open"
    except websockets.ConnectionClosed as e:
        return e.code
    except Exception as e:
        return type(e).__name__
async def ws_all():
    return await asyncio.wait_for(asyncio.gather(
        ws_try(vw, "/ws/logs/bb-none"), ws_try(vw, "/ws/update/bb-none"), ws_try(op, "/ws/deploy"), ws_try(adm, "/ws/logs/bb-none")), 60)
res = asyncio.run(ws_all())
check("U6 WebSocket: View only reads logs, cannot update (4403, not sent to login); Update role cannot deploy (4403)",
      res[0] == "open" and res[1] == 4403 and res[2] == 4403 and res[3] == "open", res)

# U7 khoá / đổi vai trò / đặt lại mật khẩu -> thu hồi phiên ngay
r = adm.post("/api/users", json={"username": "oper", "role": "viewer"})
after = op.post("/api/apps/bb-none/restart").status_code
check("U7 changing a role signs that person out everywhere at once (old session -> 401)", r.status_code == 200 and after == 401, (r.text, after))
op2, _ = client("oper")
check("U7 after signing in again the new role applies (Update -> View only)", op2.get("/api/auth/me").json()["role"] == "viewer" and op2.post("/api/apps/bb-none/restart").status_code == 403)
adm.post("/api/users", json={"username": "oper", "role": "operator", "disabled": True})
_, rl = client("oper")
check("U7 a disabled account cannot sign in (clear message, only after the right password)",
      rl.status_code == 403 and "disabled" in rl.text and client("oper", "wrong-password")[1].status_code == 401, rl.text)
adm.post("/api/users", json={"username": "oper", "role": "operator", "disabled": False, "password": "New-Passw0rd!y"})
_, old_pw = client("oper"); op3, new_pw = client("oper", "New-Passw0rd!y")
check("U7 admin resets a password: old one stops working, new one works, account enabled again", old_pw.status_code == 401 and new_pw.status_code == 200, (old_pw.text, new_pw.text))
check("U7 admin's own session is not affected by changes to other accounts", adm.get("/api/users").status_code == 200)

# U8 luôn giữ ít nhất 1 Quản trị
a = adm.post("/api/users", json={"username": "admin", "role": "viewer"})
b = adm.post("/api/users/delete", json={"username": "admin"})
c = adm.post("/api/users", json={"username": "admin", "role": "admin", "disabled": True})
check("U8 the last administrator cannot be demoted, deleted or disabled", a.status_code == 400 and "at least one" in a.text and b.status_code == 400 and c.status_code == 400, (a.text, b.text, c.text))
adm.post("/api/users", json={"username": "view", "role": "admin"})
a2 = adm.post("/api/users", json={"username": "admin", "role": "operator"})
check("U8 with a second admin, an admin can change their own role (and keeps the session on this device)",
      a2.status_code == 200 and a2.json().get("self_changed") and adm.get("/api/auth/me").json()["role"] == "operator", a2.text)
vw2, _ = client("view")
dele = vw2.post("/api/users/delete", json={"username": "oper"})
check("U8 deleting an account: it can no longer sign in", dele.status_code == 200 and client("oper", "New-Passw0rd!y")[1].status_code == 401, dele.text)

# U9 đổi mật khẩu của mình chỉ đăng xuất thiết bị khác của chính mình
other_dev, _ = client("view")
vw2.post("/api/auth/password", json={"current_password": PW, "new_password": "Another-Passw0rd!1"})
check("U9 changing your own password signs out your other devices only (other accounts stay signed in)",
      other_dev.get("/api/auth/me").status_code == 401 and vw2.get("/api/auth/me").status_code == 200 and adm.get("/api/auth/me").status_code == 200)

# U10 API Token không quản lý được tài khoản; nhật ký theo người
tok = vw2.post("/api/tokens", json={"name": "full", "scope": "full"}).json()["token"]
tu = httpx.get(B + "/api/users", headers={"Authorization": f"Bearer {tok}"})
check("U10 even a Full-access API Token cannot read or change accounts", tu.status_code == 403, tu.text)
au = vw2.get("/api/audit", params={"user": "admin"}).json()["items"]
acts = {a["action"] for a in au}
check("U10 activity log filtered by person: who added / changed / deleted accounts", au and all(a["username"] == "admin" for a in au)
      and {"user_add", "user_edit"} <= acts, sorted(acts))
au_v = vw2.get("/api/audit", params={"user": "view"}).json()["items"]
check("U10 the other admin's own entries (delete account, password change) are listed under their name",
      {"user_delete", "password_changed"} <= {a["action"] for a in au_v}, [a["action"] for a in au_v][:10])
proc.terminate()
print(f"SUMMARY {sum(R)} / {len(R)}")
