"""0.23 SSO với nhà cung cấp THẬT: Keycloak 26 (container, realm home nhập từ kc-realm.json: nhóm amp-admins / amp-ops /
family, client appmanager có PKCE S256 + secret, mapper nhóm). AppManager thật (uvicorn :8780). Đăng nhập qua đúng form
của Keycloak (httpx đóng vai trình duyệt). id_token Keycloak ký RS256 -> AppManager kiểm chữ ký bằng RSA thuần Python."""
import atexit, os, re, subprocess, sys, time
from html import unescape
from urllib.parse import parse_qs, urlparse
import httpx
S = os.environ["S"]; R = []
B = "http://localhost:8780"; KC = "http://127.0.0.1:8088"; ISS = KC + "/realms/home"
HERE = os.path.dirname(os.path.abspath(__file__))
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
sh('docker rm -f kc'); sh('pkill -f "app.main:app --port 878[0]"')
sh(f"docker run -d --name kc -p 8088:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin "
   f"-v {HERE}/kc-realm.json:/opt/keycloak/data/import/realm.json:ro mirror.gcr.io/keycloak/keycloak:26.4 start-dev --import-realm")
data = f"{S}/sso_kc"; sh(f"rm -rf {data} && mkdir -p {data}")
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8780"], env={**os.environ, "APP_DATA_DIR": data},
                        stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT)
atexit.register(lambda: (proc.terminate(), sh("docker rm -f kc")))
up = False
for _ in range(180):
    try:
        if httpx.get(ISS + "/.well-known/openid-configuration", timeout=3).status_code == 200:
            up = True; break
    except Exception: pass
    time.sleep(1)
check("K0 Keycloak 26 up with realm 'home' imported", up, sh("docker logs --tail 30 kc"))
H = {"Origin": B}; PW = "Test-Passw0rd!x"
httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": PW, "confirm_password": PW})
adm = httpx.Client(base_url=B, headers=H, timeout=60); adm.post("/api/auth/login", json={"username": "admin", "password": PW})

t = adm.post("/api/sso/test", json={"issuer": ISS}).json()
check("K1 test connection to Keycloak: discovery, signing keys, PKCE S256; scope groups (unknown to Keycloak) will be skipped", t.get("ok") and t["keys"] >= 1 and t["pkce"] and "RS256" in t["algs"] and t["scopes_dropped"] == ["groups"], t)
sv = adm.post("/api/sso", json={"enabled": True, "label": "Keycloak", "issuer": ISS, "client_id": "appmanager", "client_secret": "kc-client-secret-123",
                                "admin_groups": "amp-admins", "operator_groups": "amp-ops", "default_role": "none"})
check("K1 SSO saved and enabled", sv.status_code == 200, sv.text)

def kc_login(user, pw):
    c = httpx.Client(timeout=60, follow_redirects=True)
    r = c.get(B + "/api/auth/oidc/login")
    if urlparse(str(r.url)).netloc != urlparse(KC).netloc:
        return c, str(r.url), "did not reach Keycloak"
    m = re.search(r'<form[^>]+action="([^"]+)"', r.text)
    if not m:
        return c, str(r.url), "no login form"
    for ck in c.cookies.jar:  # Keycloak đặt cookie Secure; trình duyệt thật vẫn gửi tới localhost / 127.0.0.1 qua http, httpx thì không
        ck.secure = False
    r = c.post(unescape(m.group(1)), data={"username": user, "password": pw, "credentialId": ""})
    err = parse_qs(urlparse(str(r.url)).query).get("sso_error", [""])[0]
    return c, str(r.url), err

def me(c):
    r = c.get(B + "/api/auth/me")
    return r.json() if r.status_code == 200 else {"status": r.status_code}

c, url, err = kc_login("alice", "Alice-Passw0rd!")
m = me(c)
check("K2 alice signs in through the real Keycloak login form -> AppManager Admin (group amp-admins, RS256 signature verified)",
      url == B + "/" and m.get("username") == "alice" and m.get("role") == "admin" and m.get("auth_source") == "oidc", (url, err, m))
c2, _, _ = kc_login("bob", "Bob-Passw0rd!")
check("K3 bob (group amp-ops) -> Update role", me(c2).get("role") == "operator", me(c2))
c3, url3, err3 = kc_login("carl", "Carl-Passw0rd!")
check("K4 carl (only group 'family') -> refused with the reason (groups listed)", "not in a group" in err3 and "family" in err3 and me(c3).get("status") == 401, (url3, err3))
c4, url4, err4 = kc_login("alice", "wrong")
check("K5 wrong password stays on Keycloak (no AppManager session)", me(c4).get("status") == 401 and urlparse(url4).netloc == urlparse(KC).netloc, url4)
users = {u["username"]: u for u in adm.get("/api/users").json()["users"]}
check("K6 accounts created for alice and bob with e-mails from Keycloak", users.get("alice", {}).get("email") == "alice@example.com"
      and users.get("bob", {}).get("role") == "operator", list(users))
au = [a for a in adm.get("/api/audit").json()["items"] if a["action"] == "login" and "SSO" in (a.get("detail") or "")]
check("K6 SSO sign-ins in the activity log (SSO (Keycloak))", {a["username"] for a in au} >= {"alice", "bob"}, au[:3])
proc.terminate()
print(f"SUMMARY {sum(R)} / {len(R)}")
