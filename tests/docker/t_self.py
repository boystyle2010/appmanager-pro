import asyncio, json, os, subprocess, time
import httpx, websockets
B = "http://localhost:8770"; S = os.environ["S"]; R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:800]}"), flush=True)
H = {"Origin": B}
def wait_up(t=120):
    end = time.time() + t
    while time.time() < end:
        try:
            if httpx.get(B + "/login", timeout=3).status_code < 500: return True
        except Exception: pass
        time.sleep(2)
    return False
def wait_result(t=240):
    """Chờ container phụ làm xong (không còn container phụ, không còn -amp-old)."""
    end = time.time() + t
    time.sleep(6)
    while time.time() < end:
        if not sh("docker ps -aq -f name=^appmanager-pro-self-updater$") and not sh("docker ps -aq -f name=^appmanager-pro-amp-old$"):
            return True
        time.sleep(3)
    return False
def client():
    c = httpx.Client(base_url=B, headers=H, timeout=30)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "Test-Passw0rd!x"})
    assert r.status_code == 200, r.text
    return c
async def ws_update(c, tag=""):
    cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    url = "ws://localhost:8770/ws/update/appmanager-pro" + (f"?tag={tag}" if tag else "")
    out = []
    async with websockets.connect(url, additional_headers={"Cookie": cookie, "Origin": B}) as ws:
        try:
            async for m in ws: out.append(m)
        except Exception: pass
    return "".join(out)
def build_tag(): return sh("docker exec appmanager-pro cat /app/BUILD_TAG")
def history(c):
    r = c.get("/api/settings"); return (r.json().get("history") or [])
def push_latest(t): sh(f"docker tag localhost:5000/amp:{t} localhost:5000/amp:latest && docker push -q localhost:5000/amp:latest")

async def main():
    # --- AppManager chạy bằng docker run
    sh("docker rm -f appmanager-pro appmanager-pro-amp-old appmanager-pro-self-updater"); sh(f"rm -rf {S}/selfdata && mkdir -p {S}/selfdata")
    push_latest("1")
    sh("docker pull -q localhost:5000/amp:latest")
    run = (f"docker run -d --name appmanager-pro --restart unless-stopped -p 8770:8000 -e TZ=Asia/Ho_Chi_Minh "
           f"-v /var/run/docker.sock:/var/run/docker.sock -v {S}/selfdata:/app/data -v {S}/AppData:{S}/AppData -e APPDATA_DIR={S}/AppData localhost:5000/amp:latest")
    sh(run)
    check("S0 AppManager (docker run) starts", wait_up())
    httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"})
    c = client()
    me = next(a for a in c.get("/api/apps").json()["apps"] if a["is_self"])
    check("S0 AppManager detected as itself, manage=run, can_update + can_edit", me["manage"] == "run" and me["can_update"] and me["can_edit"], me)
    st = c.get("/api/apps/appmanager-pro/compose").json()
    check("S0 editor shows AppManager's own settings", st.get("run_mode") and "/var/run/docker.sock" in st.get("raw_yaml", ""), st.get("raw_yaml"))
    # S1 update latest(1) -> latest(2)
    push_latest("2")
    log = await ws_update(c)
    check("S1 self-update hands over to helper", "Helper launched" in log, log[-600:])
    done = wait_result(); up = wait_up()
    check("S1 new AppManager running build 2", done and up and build_tag() == "2", (done, up, build_tag()))
    c = client()
    h = history(c)
    check("S1 login + data kept, history success", h and h[0]["status"] == "success" and h[0]["container_name"] == "appmanager-pro", h[:2])
    a = json.loads(sh("docker inspect appmanager-pro"))[0]
    check("S1 settings kept (env TZ, port 8770, mounts)", "TZ=Asia/Ho_Chi_Minh" in a["Config"]["Env"] and a["HostConfig"]["PortBindings"]["8000/tcp"][0]["HostPort"] == "8770" and len(a["Mounts"]) == 3)
    check("S1 no helper / -amp-old left", not sh("docker ps -aq -f name=self-updater") and not sh("docker ps -aq -f name=amp-old"))
    # S2 broken new version -> rollback
    before = sh("docker inspect -f '{{.Id}}' appmanager-pro")
    push_latest("bad")
    log = await ws_update(c)
    done = wait_result(); up = wait_up()
    after = sh("docker inspect -f '{{.Id}}' appmanager-pro")
    check("S2 broken build rolled back to the SAME previous container (build 2)", done and up and after == before and build_tag() == "2", (done, up, before[:12], after[:12], build_tag()))
    c = client(); h = history(c)
    check("S2 history = rolled_back with reason", h and h[0]["status"] == "rolled_back", h[:1])
    # S3 edit AppManager config (add env)
    push_latest("2")
    st = c.get("/api/apps/appmanager-pro/compose").json()
    y = st["raw_yaml"].replace("      - TZ=Asia/Ho_Chi_Minh", "      - TZ=Asia/Ho_Chi_Minh\n      - FOO=bar")
    r = c.post("/api/apps/appmanager-pro/compose/apply", json={"raw_yaml": y})
    check("S3 apply on itself -> self_update", r.status_code == 200 and r.json().get("self_update"), r.text)
    done = wait_result(); up = wait_up()
    a = json.loads(sh("docker inspect appmanager-pro"))[0]
    check("S3 AppManager recreated with FOO=bar", done and up and "FOO=bar" in a["Config"]["Env"], a["Config"]["Env"])
    # S4 edit that drops the data folder -> refused
    c = client()
    st = c.get("/api/apps/appmanager-pro/compose").json()
    y = "\n".join(l for l in st["raw_yaml"].splitlines() if ":/app/data" not in l)
    before = sh("docker inspect -f '{{.Id}}' appmanager-pro")
    r = c.post("/api/apps/appmanager-pro/compose/apply", json={"raw_yaml": y})
    time.sleep(3)
    check("S4 removing AppManager's data folder refused, nothing changed", r.status_code == 400 and "data folder" in r.text and sh("docker inspect -f '{{.Id}}' appmanager-pro") == before, r.text)
    # S5 regression: AppManager deployed with compose self-updates as before
    sh("docker rm -f appmanager-pro"); push_latest("1")
    os.makedirs(f"{S}/AppData/appmanager-pro", exist_ok=True)
    open(f"{S}/AppData/appmanager-pro/docker-compose.yml", "w").write(f"""name: appmanager-pro
services:
  appmanager-pro:
    image: localhost:5000/amp:latest
    container_name: appmanager-pro
    restart: unless-stopped
    ports: ["8770:8000"]
    environment: ["APPDATA_DIR={S}/AppData"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - {S}/selfdata:/app/data
      - {S}/AppData:{S}/AppData
""")
    sh(f"docker pull -q localhost:5000/amp:latest; cd {S}/AppData/appmanager-pro && docker compose up -d")
    up = wait_up(); c = client()
    me = next(a for a in c.get("/api/apps").json()["apps"] if a["is_self"])
    check("S5 AppManager via compose: manage=compose", up and me["manage"] == "compose", me.get("manage"))
    push_latest("2")
    log = await ws_update(c)
    done = wait_result(); up = wait_up()
    check("S5 compose self-update still works (build 2)", "Helper launched" in log and done and up and build_tag() == "2", (log[-300:], build_tag()))
    c = client(); h = history(c)
    check("S5 history success", h and h[0]["status"] == "success", h[:1])
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
