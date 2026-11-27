"""Tạo Quản trị đầu tiên chỉ được khi máy CHƯA có tài khoản (mới cài, hoặc sau RESET_AUTH): 12 yêu cầu cùng lúc -> đúng 1
thành công; sau đó luôn bị từ chối (kể cả khi đã đăng nhập); trang đăng nhập chỉ có form tạo Quản trị lúc chưa có tài khoản."""
import asyncio, os, subprocess, sys, time
import httpx
S = os.environ["S"]; R = []
PORT = 8767; B = f"http://127.0.0.1:{PORT}"; H = {"Origin": B}
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:400]}"), flush=True)
data = f"{S}/setup_t"; subprocess.run(["rm", "-rf", data]); os.makedirs(data)
def start(extra=None):
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env={**os.environ, "APP_DATA_DIR": data, **(extra or {})},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            if httpx.get(B + "/api/health", timeout=1).status_code == 200:
                return p
        except Exception:
            pass
        time.sleep(0.5)
    return p
proc = start()
body = lambda u: {"username": u, "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"}
check("Fresh install: the login page offers the administrator form (setup mode)", "authApp(true)" in httpx.get(B + "/login").text)
async def race():
    async with httpx.AsyncClient(base_url=B, headers=H, timeout=20) as c:
        return await asyncio.gather(*[c.post("/api/auth/setup", json=body(f"admin{i}")) for i in range(12)])
res = asyncio.run(race())
codes = sorted(r.status_code for r in res)
check("12 simultaneous 'create administrator' requests -> exactly one succeeds", codes.count(200) == 1 and codes.count(400) == 11, codes)
winner = [f"admin{i}" for i, r in enumerate(res) if r.status_code == 200]
a = httpx.Client(base_url=B, headers=H); a.post("/api/auth/login", json={"username": winner[0], "password": "Test-Passw0rd!x"})
users = a.get("/api/users").json()
n_users = len(users.get("users", users) if isinstance(users, dict) else users)
check("Only one account exists afterwards", n_users == 1, users)
r = httpx.post(B + "/api/auth/setup", json=body("intruder"), headers=H)
check("After installation, creating an administrator is refused", r.status_code == 400 and "already" in r.text, r.text)
r2 = a.post("/api/auth/setup", json=body("intruder2"))
check("...also when signed in", r2.status_code == 400, r2.text)
check("Login page no longer offers the administrator form", "authApp(false)" in httpx.get(B + "/login").text)
proc.terminate(); proc.wait(10)
proc = start({"RESET_AUTH": "true"})
check("RESET_AUTH=true (forgotten password): setup mode again", "authApp(true)" in httpx.get(B + "/login").text)
r3 = httpx.post(B + "/api/auth/setup", json=body("newadmin"), headers=H)
check("...and a new administrator can be created once", r3.status_code == 200, r3.text)
proc.terminate(); proc.wait(10)
print(f"SUMMARY {sum(R)} / {len(R)}")
