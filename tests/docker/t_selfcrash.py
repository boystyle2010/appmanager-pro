import asyncio, os, subprocess, time
import httpx, websockets
S = os.environ["S"]; B = "http://localhost:8770"; H = {"Origin": B}; R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:600]}"), flush=True)
def wait_up(t=180):
    end = time.time() + t
    while time.time() < end:
        try:
            if httpx.get(B + "/login", timeout=3).status_code < 500: return True
        except Exception: pass
        time.sleep(2)
    return False
def client():
    c = httpx.Client(base_url=B, headers=H, timeout=30)
    assert c.post("/api/auth/login", json={"username": "admin", "password": "Test-Passw0rd!x"}).status_code == 200
    return c
def push_latest(t): sh(f"docker tag localhost:5000/amp:{t} localhost:5000/amp:latest && docker push -q localhost:5000/amp:latest")
def restart_docker():
    sh("pkill dockerd")
    for _ in range(30):
        time.sleep(1)
        if not sh("pgrep -x dockerd"): break
    subprocess.run(f"setsid nohup dockerd > {S}/dockerd.log 2>&1 < /dev/null &", shell=True)
    for _ in range(60):
        time.sleep(1)
        if subprocess.run("docker info", shell=True, capture_output=True).returncode == 0: break
async def start_self_update(c):
    cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    async with websockets.connect("ws://localhost:8770/ws/update/appmanager-pro", additional_headers={"Cookie": cookie, "Origin": B}) as ws:
        try:
            async for _ in ws: pass
        except Exception: pass
def wait_helper_line(marker, t=120):
    end = time.time() + t
    while time.time() < end:
        if marker in sh("docker logs appmanager-pro-self-updater 2>&1"): return True
        time.sleep(0.5)
    return False
def settle(t=300):
    end = time.time() + t; time.sleep(5)
    while time.time() < end:
        if sh("docker inspect -f '{{.State.Status}}' appmanager-pro-self-updater 2>/dev/null") in ("", "exited") and not sh("docker ps -aq -f name=^appmanager-pro-amp-old$"):
            return True
        time.sleep(3)
    return False
def fresh_run_mode():
    sh("docker rm -f appmanager-pro appmanager-pro-amp-old appmanager-pro-self-updater"); sh(f"rm -rf {S}/selfdata3 && mkdir -p {S}/selfdata3")
    push_latest("1"); sh("docker pull -q localhost:5000/amp:latest")
    sh(f"docker run -d --name appmanager-pro --restart unless-stopped -p 8770:8000 -v /var/run/docker.sock:/var/run/docker.sock -v {S}/selfdata3:/app/data localhost:5000/amp:latest")
    assert wait_up()
    httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"})

async def main():
    # S6: docker run — mất điện ngay sau khi container phụ dừng & đổi tên AppManager
    fresh_run_mode(); c = client(); push_latest("2")
    asyncio.get_event_loop().run_in_executor(None, lambda: None)
    task = asyncio.create_task(start_self_update(c))
    hit = await asyncio.to_thread(wait_helper_line, "keeping it as appmanager-pro-amp-old")
    restart_docker()
    task.cancel()
    check("S6 interrupt reproduced (helper was mid-way)", hit)
    done = settle(); up = wait_up()
    check("S6 after Docker restart AppManager is running again, no leftovers", done and up and not sh("docker ps -aq -f name=amp-old"), (done, up, sh("docker ps -a --format '{{.Names}}:{{.Status}}'")))
    c = client(); h = c.get("/api/settings").json()["history"]
    check("S6 History records the outcome", h and h[0]["container_name"] == "appmanager-pro" and h[0]["status"] in ("success", "rolled_back"), h[:1])
    check("S6 helper container cleaned up", not sh("docker ps -aq -f name=self-updater"))
    # S7: docker run — mất điện khi AppManager mới đang được kiểm tra
    push_latest("1"); sh("docker pull -q localhost:5000/amp:latest")
    task = asyncio.create_task(start_self_update(c))
    hit = await asyncio.to_thread(wait_helper_line, "Checking the new container")
    time.sleep(3); restart_docker(); task.cancel()
    done = settle(); up = wait_up()
    check("S7 interrupt during health check: AppManager running, no leftovers", hit and done and up and not sh("docker ps -aq -f name=amp-old"), (hit, done, up))
    # S8: compose — mất điện giữa lúc tự cập nhật
    sh("docker rm -f appmanager-pro"); os.makedirs(f"{S}/AppData/appmanager-pro", exist_ok=True)
    open(f"{S}/AppData/appmanager-pro/docker-compose.yml", "w").write(f"""name: appmanager-pro
services:
  appmanager-pro:
    image: localhost:5000/amp:latest
    container_name: appmanager-pro
    restart: unless-stopped
    ports: ["8770:8000"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - {S}/selfdata3:/app/data
      - {S}/AppData:{S}/AppData
""")
    push_latest("1"); sh(f"docker pull -q localhost:5000/amp:latest; cd {S}/AppData/appmanager-pro && docker compose up -d")
    wait_up(); c = client(); push_latest("2")
    task = asyncio.create_task(start_self_update(c))
    hit = await asyncio.to_thread(wait_helper_line, "Checking the new container")
    restart_docker(); task.cancel()
    done = settle(); up = wait_up()
    tag = sh("docker exec appmanager-pro cat /app/BUILD_TAG")
    check("S8 compose: interrupted self-update ends with AppManager running", hit and done and up and tag in ("1", "2"), (hit, done, up, tag))
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
