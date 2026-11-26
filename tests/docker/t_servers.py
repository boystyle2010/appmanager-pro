"""0.18 nhiều máy chủ: máy chính (uvicorn :8793) quản lý máy phụ (uvicorn :8792, HTTP) và máy phụ HTTPS tự ký (:8791)
qua REST API + API Token. Cùng Docker trong sandbox (setup.sh: bb-none, bb-fail...). Thêm máy giả (phiên bản cũ /
chuyển hướng) ở :8790 và địa chỉ không có gì ở :8799."""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
S = os.environ["S"]; R = []
MAIN, REM, REMS = "http://localhost:8793", "http://127.0.0.1:8792", "https://127.0.0.1:8791"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
procs = []
def start(port, data, ssl=False):
    sh(f"rm -rf {data} && mkdir -p {data}")
    args = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)]
    if ssl:
        args += ["--ssl-keyfile", f"{S}/srv.key", "--ssl-certfile", f"{S}/srv.crt"]
    procs.append(subprocess.Popen(args, env={**os.environ, "APP_DATA_DIR": data}, stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT))
def wait(url):
    for _ in range(60):
        try:
            if httpx.get(url + "/login", timeout=2, verify=False).status_code < 500: return True
        except Exception: time.sleep(0.5)
    return False
def admin(base):
    h = {"Origin": base}
    httpx.post(base + "/api/auth/setup", headers=h, verify=False, json={"username": "admin", "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"})
    c = httpx.Client(base_url=base, headers=h, timeout=120, verify=False)
    assert c.post("/api/auth/login", json={"username": "admin", "password": "Test-Passw0rd!x"}).status_code == 200
    return c

# máy giả: /api/health báo bản cũ ; /redir/* chuyển hướng
class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/redir"):
            self.send_response(302); self.send_header("Location", "http://example.invalid/"); self.end_headers(); return
        body = json.dumps({"status": "ok", "version": "0.16.0"} if "health" in self.path else {"jobs": []}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
threading.Thread(target=HTTPServer(("127.0.0.1", 8790), Fake).serve_forever, daemon=True).start()

sh(f"openssl req -x509 -newkey rsa:2048 -nodes -keyout {S}/srv.key -out {S}/srv.crt -days 2 -subj /CN=127.0.0.1 2>/dev/null")
try:
    start(8793, f"{S}/srv_main"); start(8792, f"{S}/srv_rem"); start(8791, f"{S}/srv_rems", ssl=True)
    check("3 AppManager instances up (main, remote HTTP, remote HTTPS self-signed)", wait(MAIN) and wait(REM) and wait(REMS))
    main, rem, rems = admin(MAIN), admin(REM), admin(REMS)
    TOK = rem.post("/api/tokens", json={"name": "Main", "scope": "update", "ips": "127.0.0.1"}).json()["token"]
    RO = rem.post("/api/tokens", json={"name": "Viewer", "scope": "read"}).json()["token"]
    TOKS = rems.post("/api/tokens", json={"name": "Main", "scope": "update"}).json()["token"]

    # V1 kiểm tra trước khi lưu
    r = main.post("/api/servers/test", json={"name": "Remote", "url": REM, "token": "amp_" + "x" * 40}).json()
    check("V1 test with a wrong Token -> clear error, nothing saved", not r["ok"] and "refused" in r["error"] and main.get("/api/servers").json()["servers"] == [], r)
    r = main.post("/api/servers/test", json={"name": "Remote", "url": REM, "token": TOK}).json()
    check("V1 test with the right Token -> version, app count, Token permission", r["ok"] and r["version"] and r["apps"]["total"] > 0 and r["scope"] == "update", r)
    r = main.post("/api/servers/test", json={"name": "X", "url": "ftp://1.2.3.4", "token": TOK})
    r2 = main.post("/api/servers/test", json={"name": "X", "url": "http://user:pw@1.2.3.4", "token": TOK})
    check("V1 invalid address (ftp://, user:password@) refused", r.status_code == 400 and r2.status_code == 400, (r.text, r2.text))

    # V2 lưu + danh sách không lộ Token
    r = main.post("/api/servers", json={"name": "Remote", "url": REM + "/", "token": TOK}).json()
    SID = r["server"]["id"]
    check("V2 save -> status ok, trailing / removed", r["status"]["ok"] and r["server"]["url"] == REM, r)
    lst = main.get("/api/servers").json()["servers"]
    check("V2 list never returns the Token (only a hint)", TOK not in json.dumps(lst) and lst[0]["has_token"] and lst[0]["token_hint"].startswith("amp_"), lst)
    check("V2 duplicate address refused", main.post("/api/servers", json={"name": "Other", "url": REM, "token": TOK}).status_code == 400)
    r = main.post("/api/servers", json={"id": SID, "name": "Remote NAS", "url": REM, "token": ""}).json()
    check("V2 edit with empty Token keeps the saved Token", r["status"]["ok"] and r["server"]["name"] == "Remote NAS", r)

    # V3 xem app của máy phụ
    d = main.get(f"/api/servers/{SID}/apps").json()
    names = {a["name"] for a in d["apps"]}
    check("V3 remote app list through the main server", {"bb-none", "bb-fail", "web"} <= names and "compose_path" not in d["apps"][0], sorted(names)[:8])

    # V4 cập nhật thật trên máy phụ qua máy chính
    j = main.post(f"/api/servers/{SID}/apps/bb-none/update", json={}).json()
    for _ in range(120):
        st = main.get(f"/api/servers/{SID}/jobs/{j['id']}").json()
        if st["status"] != "running": break
        time.sleep(2)
    check("V4 remote update job runs on the other server and finishes", st["status"] == "success" and "bb-none" in st.get("target", "bb-none"), (st["status"], st.get("log", "")[-300:]))
    au_rem = rem.get("/api/audit?limit=50").json()["items"]
    au_main = main.get("/api/audit?limit=50").json()["items"]
    check("V4 both activity logs record it (remote: token:Main, main: remote_update)",
          any(a.get("action") == "update" and str(a.get("user") or a.get("username")) == "token:Main" for a in au_rem)
          and any(a.get("action") == "remote_update" and "Remote NAS/bb-none" in (a.get("target") or "") for a in au_main), (au_rem[:3], au_main[:3]))
    # V5 dừng / bật / khởi động lại
    r1 = main.post(f"/api/servers/{SID}/apps/bb-none/stop", json={})
    s1 = sh("docker inspect -f '{{.State.Running}}' bb-none")
    r2 = main.post(f"/api/servers/{SID}/apps/bb-none/start", json={})
    r3 = main.post(f"/api/servers/{SID}/apps/bb-none/restart", json={})
    check("V5 stop / start / restart on the other server", r1.status_code == r2.status_code == r3.status_code == 200 and s1 == "false" and sh("docker inspect -f '{{.State.Running}}' bb-none") == "true", (r1.text, r2.text, r3.text, s1))
    check("V5 kill is not offered remotely", main.post(f"/api/servers/{SID}/apps/bb-none/kill", json={}).status_code == 400)

    # V6 Token chỉ đọc
    r = main.post("/api/servers", json={"name": "Viewer", "url": "http://localhost:8792", "token": RO}).json(); VID = r["server"]["id"]
    check("V6 read-only Token: list works", main.get(f"/api/servers/{VID}/apps").status_code == 200 and r["status"]["scope"] == "read")
    rr = main.post(f"/api/servers/{VID}/apps/bb-none/update", json={})
    check("V6 read-only Token: update refused with an explanation", rr.status_code == 403 and "Not allowed" in rr.text, rr.text)

    # V7 HTTPS tự ký
    r = main.post("/api/servers/test", json={"name": "S", "url": REMS, "token": TOKS, "verify_tls": True}).json()
    check("V7 HTTPS self-signed + certificate check on -> explains the certificate problem", not r["ok"] and "certificate" in r["error"].lower(), r)
    r = main.post("/api/servers/test", json={"name": "S", "url": REMS, "token": TOKS, "verify_tls": False}).json()
    check("V7 HTTPS with certificate check off -> works", r["ok"], r)

    # V8 máy không tồn tại / bản cũ / chuyển hướng
    t0 = time.time(); r = main.post("/api/servers/test", json={"name": "Off", "url": "http://127.0.0.1:8799", "token": TOK}).json()
    check("V8 unreachable server -> quick, clear error", not r["ok"] and "Cannot connect" in r["error"] and time.time() - t0 < 15, r)
    r = main.post("/api/servers/test", json={"name": "Old", "url": "http://127.0.0.1:8790", "token": TOK}).json()
    check("V8 AppManager older than 0.17.0 -> asks to update it", not r["ok"] and "too old" in r["error"], r)
    r = main.post("/api/servers/test", json={"name": "Redir", "url": "http://127.0.0.1:8790/redir", "token": TOK}).json()
    check("V8 redirect is not followed (Token never sent elsewhere)", not r["ok"] and "redirects" in r["error"], r)

    # V9 trạng thái tất cả + mã lỗi không làm trình duyệt đăng xuất
    main.post("/api/servers", json={"name": "Offline box", "url": "http://127.0.0.1:8799", "token": TOK})
    st = {s["name"]: s["status"] for s in main.get("/api/servers/status").json()["servers"]}
    check("V9 status of all servers at once (ok / offline)", st["Remote NAS"]["ok"] and not st["Offline box"]["ok"] and st["Viewer"]["ok"], st)
    rem.post("/api/tokens/delete", json={"id": next(t["id"] for t in rem.get("/api/tokens").json()["tokens"] if t["name"] == "Viewer")})
    rr = main.get(f"/api/servers/{VID}/apps")
    check("V9 Token deleted on the other server -> 424 (not 401, so this browser stays signed in)", rr.status_code == 424 and "refused" in rr.text, (rr.status_code, rr.text))

    # V10 bảo mật trên máy chính
    MT = main.post("/api/tokens", json={"name": "HA", "scope": "full"}).json()["token"]
    check("V10 API Tokens of the main server cannot use /api/servers", httpx.get(MAIN + "/api/servers", headers={"Authorization": "Bearer " + MT}).status_code == 403)
    r = httpx.post(MAIN + "/api/servers", json={"name": "Evil", "url": "http://1.2.3.4", "token": TOK}, headers={"Origin": "http://evil.example"}, cookies=main.cookies)
    check("V10 foreign Origin cannot add a server", r.status_code == 403, r.text)
    check("V10 not signed in -> 401", httpx.get(MAIN + "/api/servers").status_code == 401)

    # V11 gỡ máy chủ
    main.post("/api/servers/delete", json={"id": SID})
    check("V11 remove server", all(s["id"] != SID for s in main.get("/api/servers").json()["servers"]) and main.get(f"/api/servers/{SID}/apps").status_code == 404)
finally:
    for p in procs: p.terminate()
print(f"\nSUMMARY {sum(R)} / {len(R)}")
