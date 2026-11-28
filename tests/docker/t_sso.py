"""0.23 SSO / OIDC: AppManager thật (uvicorn :8780) + nhà cung cấp OIDC giả (oidc_mock.py, HTTP :8790 và HTTPS tự ký
:8789, ký RS256 / ES256 thật). Luồng đầy đủ qua trình duyệt giả (httpx theo chuyển hướng): đăng nhập, tạo tài khoản,
vai trò theo nhóm + đồng bộ, mọi kiểu lỗi (state, aud, hạn, nonce, chữ ký, alg none, issuer, từ chối, ES256 qua HTTP),
client_secret_basic / post, gắn tài khoản có sẵn, tự tạo tắt, userinfo, bảo mật cấu hình."""
import atexit, os, subprocess, sys, time
from urllib.parse import parse_qs, urlparse
import httpx
S = os.environ["S"]; R = []
B = "http://localhost:8780"; MOCK = "http://127.0.0.1:8790"; MOCKS = "https://127.0.0.1:8789"
HERE = os.path.dirname(os.path.abspath(__file__))
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
sh('pkill -f "oidc_mock[.]py"'); sh('pkill -f "app.main:app --port 878[0]"'); time.sleep(1)  # [x]: không tự khớp lệnh pkill
sh(f"openssl req -x509 -newkey rsa:2048 -nodes -keyout {S}/oidc.key -out {S}/oidc.crt -days 2 -subj /CN=127.0.0.1 2>/dev/null")
data = f"{S}/sso_data"; sh(f"rm -rf {data} && mkdir -p {data}")
procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8780"], env={**os.environ, "APP_DATA_DIR": data},
                          stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT),
         subprocess.Popen([sys.executable, f"{HERE}/oidc_mock.py", "8790"]),
         subprocess.Popen([sys.executable, f"{HERE}/oidc_mock.py", "8789", f"{S}/oidc.crt", f"{S}/oidc.key"])]
atexit.register(lambda: [p.terminate() for p in procs])
for _ in range(60):
    try:
        if httpx.get(B + "/login", timeout=2).status_code < 500 and httpx.get(MOCK + "/jwks", timeout=2).status_code == 200: break
    except Exception: time.sleep(0.5)
H = {"Origin": B}; PW = "Test-Passw0rd!x"
httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": PW, "confirm_password": PW})
adm = httpx.Client(base_url=B, headers=H, timeout=60); adm.post("/api/auth/login", json={"username": "admin", "password": PW})
def mock(**kw): return httpx.post(MOCK + "/admin", json=kw).json()
def mocks(**kw): return httpx.post(MOCKS + "/admin", json=kw, verify=False).json()

def sso_login(user=None, fault="", alg="RS256", base=MOCK):
    """Trình duyệt giả: bấm nút SSO -> nhà cung cấp -> quay lại AppManager. Trả (client, url cuối, lỗi trên trang đăng nhập)."""
    adm_mock = mocks if base == MOCKS else mock
    adm_mock(user=user or {"sub": "u-1", "preferred_username": "alice", "email": "alice@example.com", "groups": ["amp-admins"]}, fault=fault, alg=alg)
    c = httpx.Client(timeout=60, follow_redirects=True, verify=False)
    r = c.get(B + "/api/auth/oidc/login")
    err = parse_qs(urlparse(str(r.url)).query).get("sso_error", [""])[0]
    return c, str(r.url), err

def me(c):
    r = c.get(B + "/api/auth/me")
    return r.json() if r.status_code == 200 else {"status": r.status_code}

# S1 cấu hình
st = httpx.get(B + "/api/auth/oidc/status").json()
check("S1 SSO is off by default; the login page gets only public fields (enabled, label, provider icon, sign-up)",
      st.get("enabled") is False and st.get("label") == "SSO" and set(st) <= {"enabled", "label", "provider", "signup"}, st)
g = adm.get("/api/sso").json()
check("S1 settings show the Redirect URI to register at the provider", g["redirect_uri"] == B + "/api/auth/oidc/callback" and not g["config"]["has_secret"], g)
t = adm.post("/api/sso/test", json={"issuer": MOCK + "/.well-known/openid-configuration"}).json()
check("S1 test connection: discovery + keys + PKCE (issuer pasted with /.well-known also works)", t.get("ok") and t["keys"] == 3 and t["pkce"], t)
t2 = adm.post("/api/sso/test", json={"issuer": "http://127.0.0.1:8777"}).json()
check("S1 test connection to a dead address explains the problem", not t2["ok"] and "Cannot connect" in t2["error"], t2)
bad = adm.post("/api/sso", json={"enabled": True, "issuer": MOCK})
check("S1 cannot turn SSO on without Client ID / Secret", bad.status_code == 400 and "Client ID" in bad.text, bad.text)
cfg = {"enabled": True, "label": "Authentik", "issuer": MOCK, "client_id": "appmanager", "client_secret": "s3cret-value",
       "admin_groups": "amp-admins", "operator_groups": "amp-ops, /Operators", "viewer_groups": "amp-view", "default_role": "none"}
sv = adm.post("/api/sso", json=cfg)
check("S1 save: Client Secret never returned to the browser", sv.status_code == 200 and "s3cret" not in sv.text and sv.json()["config"]["has_secret"], sv.text)
st2 = httpx.get(B + "/api/auth/oidc/status").json()
check("S1 login page now offers the SSO button", st2.get("enabled") is True and st2.get("label") == "Authentik" and set(st2) <= {"enabled", "label", "provider", "signup"}, st2)

# S2 đăng nhập đầy đủ
mock(reset_counters=True)
c, url, err = sso_login()
m = me(c)
check("S2 SSO sign-in (Authorization Code + PKCE, RS256 id_token checked with the provider's key) -> signed in at /",
      url == B + "/" and not err and m.get("username") == "alice" and m.get("role") == "admin" and m.get("auth_source") == "oidc", (url, err, m))
form = mock()["last_token_form"]
check("S2 token request sent PKCE code_verifier + redirect_uri, secret via HTTP Basic (not in the form)",
      form.get("code_verifier") and form.get("redirect_uri") == B + "/api/auth/oidc/callback" and "client_secret" not in form, form)
users = {u["username"]: u for u in adm.get("/api/users").json()["users"]}
check("S2 account created automatically (created by sso, e-mail kept)", users["alice"]["auth_source"] == "oidc" and users["alice"]["created_by"] == "sso"
      and users["alice"]["email"] == "alice@example.com", users.get("alice"))
check("S2 SSO session can use the app like a password session", c.get(B + "/api/users").status_code == 200)

# S3 vai trò theo nhóm + đồng bộ mỗi lần đăng nhập
bob = {"sub": "u-2", "preferred_username": "bob", "email": "bob@example.com", "groups": ["/Operators"]}
c2, _, _ = sso_login(bob)
check("S3 group /Operators (Keycloak path) -> Update role", me(c2).get("role") == "operator", me(c2))
c3, _, _ = sso_login({**bob, "groups": ["AMP-VIEW"]})
check("S3 group changed at the provider -> role follows on next sign-in (case-insensitive match)", me(c3).get("role") == "viewer", me(c3))
c4, url4, err4 = sso_login({"sub": "u-3", "preferred_username": "eve", "groups": ["random"]})
check("S3 no matching group and default role 'none' -> refused with a clear message", "not in a group" in err4 and me(c4).get("status") == 401, (url4, err4))
adm.post("/api/sso", json={"default_role": "viewer"})
c5, _, _ = sso_login({"sub": "u-3", "preferred_username": "eve", "groups": ["random"]})
check("S3 default role View only -> no group still signs in as View only", me(c5).get("role") == "viewer", me(c5))
adm.post("/api/sso", json={"default_role": "none"})

# S4 lỗi bảo mật: mọi kiểu đều bị từ chối, không có phiên
faults = {"bad_state": "expired or was started elsewhere", "bad_aud": "not issued for this Client ID", "expired": "expired",
          "bad_nonce": "nonce does not match", "bad_sig": "signature does not match", "alg_none": "Unsigned", "deny": "User cancelled"}
res = {}
for f, want in faults.items():
    cx, ux, ex = sso_login(fault=f)
    res[f] = (want in ex, me(cx).get("status"))
check("S4 tampered state / wrong audience / expired / wrong nonce / bad signature / alg none / user cancelled -> refused",
      all(ok and stt == 401 for ok, stt in res.values()), res)
ce, ue, ee = sso_login(alg="ES256")
check("S4 ES256 id_token over plain HTTP refused (cannot be verified without TLS)", "only accept over HTTPS" in ee and me(ce).get("status") == 401, ee)
mock(fault="issuer_mismatch")
ti = adm.post("/api/sso/test", json={}).json()
check("S4 provider claiming another issuer -> test shows the mismatch", not ti["ok"] and "Issuer mismatch" in ti["error"], ti)
mock(fault="")
au = adm.get("/api/audit", params={"user": "alice"}).json()["items"]
check("S4 failed SSO sign-ins are in the activity log", sum(1 for a in adm.get("/api/audit").json()["items"] if a["action"] == "login_failed" and "SSO" in a["detail"]) >= 8)

# S5 HTTPS + ES256 (chứng chỉ tự ký: tắt kiểm tra chứng chỉ)
adm.post("/api/sso", json={"issuer": MOCKS, "verify_tls": True})
cs, us, es = sso_login(alg="ES256", base=MOCKS)
check("S5 self-signed HTTPS provider with certificate checking on -> clear certificate message", "not trusted" in es, es)
adm.post("/api/sso", json={"verify_tls": False})
cs, us, es = sso_login(alg="ES256", base=MOCKS)
check("S5 ES256 id_token received directly from the HTTPS token endpoint is accepted (OIDC Core 3.1.3.7); another issuer = separate account",
      me(cs).get("username") == "alice-2" and not es, (es, me(cs)))
adm.post("/api/sso", json={"issuer": MOCK, "verify_tls": True})

# S6 client_secret_post + sai secret
mock(auth_method="post")
adm.post("/api/sso", json={})  # lưu lại = xoá bộ đệm discovery (nhà cung cấp vừa đổi cách nhận secret)
cp, _, _ = sso_login()
form = mock()["last_token_form"]
check("S6 provider wanting client_secret_post: secret sent in the form, sign-in works", me(cp).get("username") == "alice" and form.get("client_secret") == "***", form)
mock(auth_method="basic")
adm.post("/api/sso", json={"client_secret": "wrong"})  # (lưu cũng xoá bộ đệm discovery)
cw, _, ew = sso_login()
check("S6 wrong Client Secret -> provider's refusal shown (check Client ID / Secret / Redirect URI)", "Wrong client credentials" in ew and me(cw).get("status") == 401, ew)
adm.post("/api/sso", json={"client_secret": "s3cret-value"})

# S7 tài khoản mật khẩu cùng tên: không tự gắn (chống chiếm quyền) trừ khi bật
adm.post("/api/users", json={"new": True, "username": "carol", "password": PW, "role": "viewer"})
carol = {"sub": "u-9", "preferred_username": "carol", "groups": ["amp-admins"]}
cc, _, ec_ = sso_login(carol)
check("S7 SSO user with the same name as a password account is refused by default", "already exists" in ec_ and me(cc).get("status") == 401, ec_)
adm.post("/api/sso", json={"link_existing": True})
cc, _, _ = sso_login(carol)
mc = me(cc)
check("S7 with linking on: the existing account is linked and keeps the role the admin gave it (not raised by groups)",
      mc.get("username") == "carol" and mc.get("role") == "viewer" and mc.get("auth_source") == "local", mc)
pw = httpx.post(B + "/api/auth/login", headers=H, json={"username": "carol", "password": PW})
check("S7 linked account can still sign in with its password", pw.status_code == 200)
adm.post("/api/sso", json={"link_existing": False})

# S8 tự tạo tắt; trùng tên giữa 2 tài khoản SSO
adm.post("/api/sso", json={"auto_create": False})
cn, _, en = sso_login({"sub": "u-10", "preferred_username": "newbie", "groups": ["amp-view"]})
check("S8 automatic account creation off -> unknown person refused", "automatic account creation is off" in en and me(cn).get("status") == 401, en)
adm.post("/api/sso", json={"auto_create": True})
cd, _, _ = sso_login({"sub": "u-11", "preferred_username": "alice", "groups": ["amp-view"]})
check("S8 a different person (other sub) with the same name gets a separate account (alice-3), never alice's",
      me(cd).get("username") == "alice-3" and me(cd).get("role") == "viewer", me(cd))
cw2, _, _ = sso_login({"sub": "u-12", "preferred_username": "Đặng Văn A", "groups": ["amp-view"]})
check("S8 names with spaces / accents become a valid user name", me(cw2).get("username", "").startswith("u") or "-" in me(cw2).get("username", ""), me(cw2))

# S9 userinfo
mock(fault="groups_only_userinfo")
cu, _, _ = sso_login({"sub": "u-2", "preferred_username": "bob", "groups": ["amp-ops"]})
check("S9 groups only in userinfo (not in id_token) are still used", me(cu).get("role") == "operator", me(cu))
mock(fault="userinfo_other_sub")
cu2, _, _ = sso_login({"sub": "u-2", "preferred_username": "bob", "groups": ["amp-view"]})
check("S9 userinfo for a different subject is ignored (no admin from a wrong userinfo)", me(cu2).get("role") == "viewer", me(cu2))
mock(fault="")

# S10 khoá tài khoản SSO; quyền xem cấu hình
adm.post("/api/users", json={"username": "bob", "role": "operator", "disabled": True})
cb, _, eb = sso_login({"sub": "u-2", "preferred_username": "bob", "groups": ["amp-ops"]})
check("S10 a disabled SSO account cannot sign in through SSO either", "disabled" in eb and me(cb).get("status") == 401, eb)
v = httpx.Client(base_url=B, headers=H); v.post("/api/auth/login", json={"username": "carol", "password": PW})
tok = adm.post("/api/tokens", json={"name": "full", "scope": "full"}).json()["token"]
check("S10 SSO settings: View only gets 403; even a Full API Token gets 403",
      v.get("/api/sso").status_code == 403 and httpx.get(B + "/api/sso", headers={"Authorization": f"Bearer {tok}"}).status_code == 403)
adm.post("/api/sso", json={"enabled": False})
co, _, eo = sso_login()
check("S10 SSO turned off -> button gone and the SSO endpoint refuses", "turned off" in eo and httpx.get(B + "/api/auth/oidc/status").json()["enabled"] is False, eo)
print(f"SUMMARY {sum(R)} / {len(R)}")
