"""API token (0.17): quyền, hạn dùng, giới hạn IP, khoá IP khi sai nhiều lần, cập nhật app thật qua HTTP job,
/api/health, /docs + /openapi.json, audit log. AppManager chạy bằng uvicorn từ repo ở :8795 (cần setup.sh: bb-none, bb-fail)."""
import json, os, subprocess, sys, time
import httpx
sys.path.insert(0, ".")
B = "http://localhost:8795"; S = os.environ["S"]; R = []; H = {"Origin": B}
D = os.environ["APP_DATA_DIR"]
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
def T(tok): return {"Authorization": f"Bearer {tok}"}
api = httpx.Client(base_url=B, timeout=60)   # như script / Home Assistant: KHÔNG có cookie, KHÔNG có Origin

srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8795"], stdout=open(f"{S}/uvtok.log", "w"), stderr=subprocess.STDOUT)
try:
    for _ in range(40):
        try:
            if httpx.get(B + "/login", timeout=2).status_code < 500: break
        except Exception: time.sleep(0.5)
    httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"})
    web = httpx.Client(base_url=B, headers=H, timeout=60)
    assert web.post("/api/auth/login", json={"username": "admin", "password": "Test-Passw0rd!x"}).status_code == 200
    # webhook nhận tin bảo mật
    sh(f"rm -f {S}/hook_tok.log"); hook = subprocess.Popen([sys.executable, f"{S}/hook_srv.py", f"{S}/hook_tok.log"])
    web.post("/api/notify/channels", json={"type": "webhook", "name": "Hook", "config": {"url": "http://127.0.0.1:8094/t"}})

    # T1 tạo token: hiện 1 lần, danh sách không lộ mã băm / token
    r = web.post("/api/tokens", json={"name": "Home Assistant", "scope": "read", "days": 0}); RD = r.json().get("token", "")
    check("T1 create read token -> plaintext amp_… returned once", r.status_code == 200 and RD.startswith("amp_") and len(RD) == 44, r.text)
    lst = web.get("/api/tokens").json()["tokens"]
    check("T1 list shows hint only (no hash, no token)", lst and "hash" not in lst[0] and RD not in json.dumps(lst) and lst[0]["hint"].startswith("amp_"), lst)
    raw = sh(f"sqlite3 {D}/*.db \"select value from settings where key='api_tokens'\" 2>/dev/null") or open(next(os.path.join(D, f) for f in os.listdir(D) if f.endswith('.db')), 'rb').read().decode('latin1')
    check("T1 database stores only the SHA-256 hash", RD not in raw)
    r = web.post("/api/tokens", json={"name": "home assistant", "scope": "read"})
    check("T1 duplicate name refused", r.status_code == 400, r.text)
    r = web.post("/api/tokens", json={"name": "Bad", "scope": "read", "ips": "10.0.0.300"})
    check("T1 invalid IP refused", r.status_code == 400, r.text)

    # T2 quyền chỉ đọc
    check("T2 read: GET /api/apps 200", api.get("/api/apps", headers=T(RD)).status_code == 200)
    check("T2 read: POST /api/updates/check 403", api.post("/api/updates/check", headers=T(RD)).status_code == 403)
    check("T2 read: POST update app 403", api.post("/api/apps/bb-none/update", headers=T(RD)).status_code == 403)
    check("T2 read: GET /api/tokens 403 (tokens never manage tokens)", api.get("/api/tokens", headers=T(RD)).status_code == 403)
    check("T2 token in URL is not accepted", api.get("/api/apps?token=" + RD).status_code == 401)
    check("T2 no token -> 401", api.get("/api/apps").status_code == 401)

    # T3 quyền cập nhật: cập nhật app THẬT qua job
    UP = web.post("/api/tokens", json={"name": "CI", "scope": "update", "days": 30}).json()["token"]
    r = api.post("/api/updates/check", headers=T(UP))
    check("T3 update: check for updates 200", r.status_code == 200, r.text[:200])
    r = api.post("/api/apps/bb-none/update", headers=T(UP), json={"tag": "no-such-tag-zz"})
    check("T3 update: unknown tag refused (only versions found in the registry)", r.status_code == 400, r.text)
    r = api.post("/api/apps/bb-none/update", headers=T(UP)); job = r.json()
    check("T3 update job started (202 + job id)", r.status_code == 202 and job.get("status") == "running", r.text)
    r2 = api.post("/api/apps/bb-none/update", headers=T(UP))
    check("T3 second update of the same app while running -> 409", r2.status_code == 409, r2.text)
    for _ in range(120):
        j = api.get(f"/api/jobs/{job['id']}", headers=T(UP)).json()
        if j["status"] != "running": break
        time.sleep(2)
    img = sh("docker inspect -f '{{.Config.Image}}' bb-none")
    check("T3 job finished with success, container updated", j["status"] == "success" and "busybox" in img, (j["status"], j.get("result"), j.get("log", "")[-300:], img))
    check("T3 restart via token", api.post("/api/apps/bb-none/restart", headers=T(UP)).status_code == 200)
    check("T3 update: POST /api/settings 403", api.post("/api/settings", headers=T(UP), json={}).status_code == 403)
    check("T3 update: compose apply 403", api.post("/api/apps/bb-none/compose/apply", headers=T(UP), json={"yaml": "x"}).status_code == 403)
    check("T3 update: kill not allowed", api.post("/api/apps/bb-none/kill", headers=T(UP)).status_code == 403)

    # T4 toàn quyền
    FU = web.post("/api/tokens", json={"name": "Admin script", "scope": "full", "days": 365}).json()["token"]
    r = api.post("/api/settings", headers=T(FU), json={"check_interval_hours": 6})
    check("T4 full: POST /api/settings allowed", r.status_code == 200, r.text[:200])
    check("T4 full: change password 403", api.post("/api/auth/password", headers=T(FU), json={"current_password": "x", "new_password": "y" * 9}).status_code == 403)
    check("T4 full: create token 403", api.post("/api/tokens", headers=T(FU), json={"name": "x", "scope": "full"}).status_code == 403)
    check("T4 full: registry passwords 403", api.post("/api/system/registry-logins", headers=T(FU), json={}).status_code == 403)
    check("T4 full: 2FA disable 403", api.post("/api/auth/2fa/disable", headers=T(FU), json={}).status_code == 403)
    r = api.post("/api/apps/bb-none/stop", headers={**T(FU), "Origin": "http://evil.example"})
    check("T4 browser-style foreign Origin still blocked with a token", r.status_code == 403, r.text)

    # T5 giới hạn IP + hết hạn
    IPT = web.post("/api/tokens", json={"name": "LAN only", "scope": "read", "ips": "10.0.0.0/8"}).json()["token"]
    r = api.get("/api/apps", headers=T(IPT))
    check("T5 IP allow-list: 127.0.0.1 not in 10.0.0.0/8 -> 403", r.status_code == 403 and "not allowed from" in r.text, r.text)
    EX = web.post("/api/tokens", json={"name": "Short", "scope": "read", "days": 1}).json()["token"]
    from app.core.database import get_setting, set_setting
    items = json.loads(get_setting("api_tokens", "[]"))
    for t in items:
        if t["name"] == "Short": t["expires"] = time.time() - 5
    set_setting("api_tokens", json.dumps(items))
    r = api.get("/api/apps", headers=T(EX))
    check("T5 expired token -> 401", r.status_code == 401 and "expired" in r.text, r.text)
    lst = {t["name"]: t for t in web.get("/api/tokens").json()["tokens"]}
    check("T5 list marks expired + last used time / IP recorded", lst["Short"]["expired"] and lst["Home Assistant"]["last_used"] > 0 and lst["Home Assistant"]["last_ip"] == "127.0.0.1", lst)

    # T6 health / docs / openapi
    h = api.get("/api/health").json()
    check("T6 /api/health without token: only status", h == {"status": "ok"}, h)
    h = api.get("/api/health", headers=T(RD)).json()
    check("T6 /api/health with token: version + app counts + updates", h.get("version") and "total" in h.get("apps", {}) and isinstance(h.get("updates"), list), h)
    check("T6 /openapi.json and /docs closed without sign-in", api.get("/openapi.json").status_code == 401 and api.get("/docs", follow_redirects=False).status_code == 302)
    o = web.get("/openapi.json").json()
    ops = o["paths"]["/api/apps/{container_name}/update"]["post"]
    check("T6 openapi: bearer scheme + permission noted per endpoint", "bearerAuth" in o["components"]["securitySchemes"] and "update" in ops["description"] and "/api/tokens" in o["paths"], list(o["paths"])[:5])
    d = web.get("/docs?lang=vi")
    check("T6 /docs page for signed-in user (no CDN, curl examples, permissions)", d.status_code == 200 and "API cho tự động hoá" in d.text and "/api/apps/{container_name}/update" in d.text and "Authorization: Bearer" in d.text and "cdn." not in d.text, d.status_code)

    # T7 xoá token -> mất hiệu lực ngay; audit + thông báo
    tid = next(t["id"] for t in web.get("/api/tokens").json()["tokens"] if t["name"] == "CI")
    web.post("/api/tokens/delete", json={"id": tid})
    check("T7 deleted token stops working immediately", api.get("/api/apps", headers=T(UP)).status_code == 401)
    au = web.get("/api/audit?limit=200").json()["items"]
    acts = {(a.get("action"), a.get("user") if "user" in a else a.get("username")) for a in au}
    check("T7 audit: token create/delete + actions done by token:CI", any(a[0] == "token_create" for a in acts) and any(a[0] == "token_delete" for a in acts) and any((a[1] or "") == "token:CI" for a in acts), list(acts)[:12])
    time.sleep(2)
    hl = open(f"{S}/hook_tok.log").read() if os.path.exists(f"{S}/hook_tok.log") else ""
    check("T7 security notification sent when a token is created", "Home Assistant" in hl and "security" in hl, hl[:300])
    check("T7 web session still works normally", web.get("/api/apps").status_code == 200)

    # T8 sai token nhiều lần -> khoá IP (chạy cuối vì khoá cả 127.0.0.1)
    # các lần 401 trước đó (token hết hạn, token đã xoá) cũng được tính: khoá ở lần sai thứ 5 tính chung
    codes = [api.get("/api/apps", headers=T("amp_" + "x" * 40)).status_code for _ in range(6)]
    r = api.get("/api/apps", headers=T(RD))
    first = codes.index(429) if 429 in codes else -1
    check("T8 wrong tokens -> IP locked (429) after 5 failures in total, even a valid token waits",
          0 < first <= 5 and all(c == 401 for c in codes[:first]) and all(c == 429 for c in codes[first:]) and r.status_code == 429 and r.headers.get("retry-after"), (codes, r.status_code))
    hook.terminate()
finally:
    srv.terminate()
print(f"\nSUMMARY {sum(R)} / {len(R)}")
