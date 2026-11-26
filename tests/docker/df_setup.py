"""Phần đầu t_datafolders.py: dựng AppManager (compose) ở :8770 với AppData + casa/apps, cho e2e12.js."""
"""Thư mục dữ liệu: liệt kê (ẩn docker.sock), kiểm tra, đổi đường dẫn, gỡ — AppManager chạy bằng compose trong container."""
import os, subprocess, time
import httpx
B = "http://localhost:8770"; S = os.environ["S"]; R = []; H = {"Origin": B}
M = "mirror.gcr.io/library"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:800]}"), flush=True)
def wait_up(t=120):
    end = time.time() + t
    while time.time() < end:
        try:
            if httpx.get(B + "/login", timeout=3).status_code < 500: return True
        except Exception: pass
        time.sleep(2)
    return False
def wait_helper(t=240):
    end = time.time() + t; time.sleep(6)
    while time.time() < end:
        if not sh("docker ps -aq -f name=^appmanager-pro-self-updater$") and not sh("docker ps -aq -f name=^appmanager-pro-amp-old$"):
            return True
        time.sleep(3)
    return False
def client():
    c = httpx.Client(base_url=B, headers=H, timeout=60)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "Test-Passw0rd!x"}); assert r.status_code == 200, r.text
    return c
def mounts(): return sh("docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' appmanager-pro").split()
def status(c): return c.get("/api/setup/data-status").json()

A, C, O = f"{S}/AppData", f"{S}/casa/apps", f"{S}/OtherData"
sh("docker rm -f appmanager-pro appmanager-pro-amp-old appmanager-pro-self-updater otherapp")
sh(f"rm -rf {S}/selfdata3 {O} && mkdir -p {S}/selfdata3 {O}/otherapp {A}/appmanager-pro")
open(f"{O}/otherapp/docker-compose.yml", "w").write(f"services:\n  otherapp:\n    image: {M}/busybox:1.35\n    container_name: otherapp\n    command: sleep 3600\n")
sh(f"cd {O}/otherapp && docker compose up -d")
COMPOSE = f"{A}/appmanager-pro/docker-compose.yml"
open(COMPOSE, "w").write(f"""name: appmanager-pro
services:
  appmanager-pro:
    image: localhost:5000/amp:latest
    container_name: appmanager-pro
    restart: unless-stopped
    ports: ["8770:8000"]
    environment: ["APPDATA_DIR={A}"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - {S}/selfdata3:/app/data
      - {A}:{A}
      - {C}:{C}:ro
""")
sh("docker tag localhost:5000/amp:1 localhost:5000/amp:latest && docker push -q localhost:5000/amp:latest")
sh(f"cd {A}/appmanager-pro && docker compose up -d"); check("AppManager (compose) up", wait_up())
httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"})
c = client()
st = status(c); f = {x["path"]: x for x in st.get("folders", [])}
check("D1 folders = AppData + CasaOS apps; docker.sock / app data hidden", set(f) == {A, C} and not any("docker.sock" in m for m in st["mounted"]), st.get("folders"))
check("D1 app counts listed", f[A]["app_count"] >= 3, f)
check("D1 backup badge on APPDATA_DIR folder", f[A]["backup_root"] and not f[C]["backup_root"], f)
check("D1 otherapp not readable yet (missing)", "otherapp" in st.get("missing_apps", []), st.get("missing_apps"))
r = c.post("/api/setup/data-check", json={"path": O}); d = r.json()
check("D2 check new folder: compose found + covers otherapp", r.status_code == 200 and d["count"] >= 1 and "otherapp" in d.get("covers_apps", []), d)
