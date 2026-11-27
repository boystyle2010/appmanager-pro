"""0.26 Quét lỗ hổng (Trivy thật): cài Trivy qua API (binary từ image aquasec/trivy, cơ sở dữ liệu thật), quét container thật
(nginx 1.26-alpine có lỗi đã biết, busybox gần như sạch), kết quả theo mức / đã có bản vá / chi tiết, bỏ qua khi image chưa đổi,
quét lại khi bấm, thông báo `vuln_found` gửi tới webhook thật (chỉ lỗi MỚI), quyền (Chỉ xem / Cập nhật / Token), lịch, gỡ.
Cần: setup.sh (container web = nginx:1.26-alpine, bb-* = busybox), mirror.gcr.io/aquasec/trivy, mạng tới mirror.gcr.io (DB)."""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
S = os.environ["S"]; R = []
PORT = 8763; B = f"http://127.0.0.1:{PORT}"; H = {"Origin": B}
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:500]}"), flush=True)

# webhook nhận thông báo
GOT = []
class Hook(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        GOT.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"))
        self.send_response(200); self.end_headers()
srv = HTTPServer(("127.0.0.1", 8762), Hook); threading.Thread(target=srv.serve_forever, daemon=True).start()

data = f"{S}/vuln_t"; subprocess.run(["rm", "-rf", data]); os.makedirs(data)
env = {**os.environ, "APP_DATA_DIR": data, "TRIVY_IMAGE": "mirror.gcr.io/aquasec/trivy:latest", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        if httpx.get(B + "/api/health", timeout=1).status_code == 200: break
    except Exception: pass
    time.sleep(0.5)
pw = "Test-Passw0rd!x"
httpx.post(B + "/api/auth/setup", json={"username": "admin", "password": pw, "confirm_password": pw}, headers=H)
a = httpx.Client(base_url=B, headers=H, timeout=60); a.post("/api/auth/login", json={"username": "admin", "password": pw})

s0 = a.get("/api/vulns").json()
check("Off by default, Trivy not installed", s0["settings"]["enabled"] is False and s0["trivy"]["installed"] is False, s0)
r = a.post("/api/vulns/scan", json={})
check("Scanning without Trivy explains what to do (409)", r.status_code == 409 and "Trivy" in r.text, r.text)

# cài Trivy
a.post("/api/vulns/install"); t0 = time.time()
while time.time() - t0 < 900:
    st = a.get("/api/vulns").json()
    if not st["state"]["installing"]: break
    time.sleep(3)
info = st["trivy"]
check("Install: Trivy binary from the official image + vulnerability database downloaded", info["installed"] and info.get("version") and info.get("db_updated"),
      (info, st["state"]))
check("Install source is the Docker image (no GitHub download on amd64 / arm64)", "aquasec/trivy" in info.get("source", ""), info)

# cài đặt + thông báo webhook
a.post("/api/notify/channels", json={"type": "webhook", "name": "Hook", "events": ["vuln_found"], "config": {"url": "http://127.0.0.1:8762/h"}, "enabled": True})
cfg = a.post("/api/vulns/settings", json={"enabled": True, "schedule": "daily", "time": "04:40", "severities": ["CRITICAL", "HIGH"]}).json()
check("Settings saved (on, daily 04:40, critical + high)", cfg["settings"]["enabled"] and cfg["settings"]["time"] == "04:40", cfg)
bad = a.post("/api/vulns/settings", json={"severities": []})
check("At least one severity required", bad.status_code == 400, bad.text)

def wait_scan(limit=900):
    t = time.time()
    time.sleep(1)
    while time.time() - t < limit:
        st = a.get("/api/vulns").json()
        if not st["state"]["running"]: return st
        time.sleep(2)
    return st
a.post("/api/vulns/scan", json={}); st = wait_scan()
apps = st["apps"]
web = apps.get("web", {}); bb = apps.get("bb-none", {})
check("Scan all: every container has a result", "web" in apps and "bb-none" in apps and st["state"]["total"] >= 5, list(apps))
check("nginx 1.26-alpine: real vulnerabilities found, counted by severity", sum(web.get("counts", {}).values()) > 0 and not web.get("error"), web)
check("Fixable counts are a subset of the totals", all(web["fixable"].get(k, 0) <= v for k, v in web["counts"].items()), web)
det = a.get("/api/vulns/web").json()
f0 = det["findings"][0] if det.get("findings") else {}
check("Details: CVE id, package, installed / fixed version, severity, link; most severe first",
      f0.get("id", "").startswith(("CVE-", "GHSA-")) and f0.get("pkg") and f0.get("installed") and f0.get("severity") in ("CRITICAL", "HIGH") and f0.get("url"), f0)
time.sleep(3)
check("Notification 'vuln_found' sent once for the new findings (webhook)", len(GOT) == 1 and GOT[0].get("event") == "vuln_found", GOT[-1:] if GOT else GOT)

# không đổi image -> bỏ qua; bấm lại (force) -> quét
t_before = apps["web"]["scanned_at"]
a.post("/api/vulns/scan", json={"name": "web", "force": False}); st2 = wait_scan()
check("Same image scanned < 24 h ago -> skipped unless forced", st2["apps"]["web"]["scanned_at"] == t_before, st2["apps"]["web"])
time.sleep(1.1)
a.post("/api/vulns/scan", json={"name": "web", "force": True}); st3 = wait_scan()
check("Re-scan one app on request", st3["apps"]["web"]["scanned_at"] > t_before, st3["apps"]["web"])
time.sleep(2)
check("No second notification when nothing new was found", len(GOT) == 1, len(GOT))

# quyền
for role, u in (("viewer", "viewer1"), ("operator", "oper1")):
    a.post("/api/users", json={"new": True, "username": u, "password": "Role-Passw0rd!1", "role": role})
v = httpx.Client(base_url=B, headers=H); v.post("/api/auth/login", json={"username": "viewer1", "password": "Role-Passw0rd!1"})
o = httpx.Client(base_url=B, headers=H); o.post("/api/auth/login", json={"username": "oper1", "password": "Role-Passw0rd!1"})
check("View only: sees results, cannot scan / change settings / install",
      v.get("/api/vulns").status_code == 200 and v.get("/api/vulns/web").status_code == 200 and v.post("/api/vulns/scan", json={}).status_code == 403
      and v.post("/api/vulns/settings", json={"enabled": False}).status_code == 403 and v.post("/api/vulns/install").status_code == 403)
check("Update role: can start a scan, not settings / install",
      o.post("/api/vulns/scan", json={"name": "bb-none"}).status_code == 200 and o.post("/api/vulns/settings", json={"enabled": False}).status_code == 403
      and o.post("/api/vulns/install").status_code == 403)
wait_scan()
tok = a.post("/api/tokens", json={"name": "ha", "scope": "update", "days": 0}).json().get("token", "")
th = {"Authorization": f"Bearer {tok}"}
check("API Token (Update): read results + start scan; not settings",
      httpx.get(B + "/api/vulns", headers=th).status_code == 200 and httpx.post(B + "/api/vulns/scan", json={"name": "bb-none"}, headers={**th, **H}).status_code == 200
      and httpx.post(B + "/api/vulns/settings", json={"enabled": False}, headers={**th, **H}).status_code == 403)
wait_scan()

# lịch + sao lưu cấu hình + gỡ
sched = subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,'.');from app.core import vulnscan;print(vulnscan.settings()['schedule'])"],
                       env=env, capture_output=True, text=True).stdout.strip()
check("Schedule stored (daily)", sched == "daily", sched)
sys.path.insert(0, "."); from app.core import config_backup  # noqa: E402
check("Configuration backup includes the scan settings", "vuln_settings" in config_backup.SETTING_SECTIONS["settings"])
un = a.post("/api/vulns/uninstall")
st4 = a.get("/api/vulns").json()
check("Uninstall removes Trivy (results kept)", un.status_code == 200 and not st4["trivy"]["installed"] and "web" in st4["apps"], st4["trivy"])
proc.terminate(); srv.shutdown()
print(f"SUMMARY {sum(R)} / {len(R)}")
