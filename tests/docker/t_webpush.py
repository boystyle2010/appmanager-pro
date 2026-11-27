"""0.25 Web Push: toán P-256 thuần Python (ECDH, ECDSA RFC 6979) và mã hoá RFC 8291 đối chiếu véc-tơ chuẩn + thư viện
cryptography; AppManager thật (uvicorn :8774) gửi tới "dịch vụ push" giả HTTPS (:8775, chứng chỉ tự ký được tin qua
SSL_CERT_FILE) — test giải mã lại nội dung bằng cryptography (như trình duyệt) và kiểm chữ ký VAPID (như Apple / Google);
kênh Web Push tự tạo, thiết bị bị huỷ (410) tự xoá, đăng ký sai bị từ chối, quyền."""
import atexit, base64, json, os, ssl, struct, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
S = os.environ["S"]; R = []
B = "http://localhost:8774"; PUSH = "https://127.0.0.1:8775"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def b64u_dec(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

os.environ["APP_DATA_DIR"] = f"{S}/wp_testproc"
sys.path.insert(0, ".")
from app.core import ec256, webpush  # noqa: E402

# ---------------- W1 véc-tơ chuẩn + đối chiếu cryptography
v = webpush.encrypt(b"When I grow up, I want to be a watermelon",
                    b64u_dec("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"), b64u_dec("BTBZMqHH6r4Tts7J_aSIgg"),
                    as_private=int.from_bytes(b64u_dec("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), salt=b64u_dec("DGv6ra1nlYgDCS1FRnbzlw"))
check("W1 RFC 8291 Appendix A test vector reproduced byte for byte", b64u(v) == "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
sig = ec256.sign(0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721, b"sample")
check("W1 RFC 6979 deterministic ECDSA P-256 vector (r)", int.from_bytes(sig[:32], "big") == 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716)
okx = True
for _ in range(10):
    d, pub = ec256.keypair()
    k = ec.derive_private_key(d, ec.SECP256R1())
    okx &= k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint) == pub
    o = ec.generate_private_key(ec.SECP256R1())
    opub = o.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    okx &= ec256.ecdh(d, opub) == o.exchange(ec.ECDH(), k.public_key())
    m = os.urandom(64); s_ = ec256.sign(d, m)
    k.public_key().verify(encode_dss_signature(int.from_bytes(s_[:32], "big"), int.from_bytes(s_[32:], "big")), m, ec.ECDSA(hashes.SHA256()))
    r2, s2 = decode_dss_signature(k.sign(m, ec.ECDSA(hashes.SHA256())))
    okx &= ec256.verify(pub, m, r2.to_bytes(32, "big") + s2.to_bytes(32, "big")) and not ec256.verify(pub, m + b"x", s_)
check("W1 pure-Python P-256 matches the cryptography library (keys, ECDH, ECDSA both ways, 10 random keys)", okx)
bad_pt = b"\x04" + (1).to_bytes(32, "big") + (2).to_bytes(32, "big")
try:
    ec256.ecdh(5, bad_pt); inv = False
except ValueError:
    inv = True
check("W1 a point not on the curve is refused (invalid-curve attack)", inv)

# ---------------- dịch vụ push giả (HTTPS)
sh(f"openssl req -x509 -newkey rsa:2048 -nodes -keyout {S}/push.key -out {S}/push.crt -days 2 -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1 2>/dev/null")
GOT = []
class Push(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        GOT.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        code = 410 if self.path.startswith("/gone") else 201
        self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()
srv = ThreadingHTTPServer(("127.0.0.1", 8775), Push)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(f"{S}/push.crt", f"{S}/push.key")
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

sh('pkill -f "app.main:app --port 877[4]"'); time.sleep(1)
data = f"{S}/wp_data"; sh(f"rm -rf {data} && mkdir -p {data}")
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8774"],
                        env={**os.environ, "APP_DATA_DIR": data, "SSL_CERT_FILE": f"{S}/push.crt", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"},
                        stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT)
atexit.register(proc.terminate)
for _ in range(60):
    try:
        if httpx.get(B + "/login", timeout=2).status_code < 500: break
    except Exception: time.sleep(0.5)
H = {"Origin": B}; PW = "Test-Passw0rd!x"
httpx.post(B + "/api/auth/setup", headers=H, json={"username": "admin", "password": PW, "confirm_password": PW})
a = httpx.Client(base_url=B, headers=H, timeout=60); a.post("/api/auth/login", json={"username": "admin", "password": PW})

sw = httpx.get(B + "/sw.js")
man = httpx.get(B + "/manifest.json").json()
check("W2 service worker served from the site root (no sign-in needed, not cached, scope /)", sw.status_code == 200 and "showNotification" in sw.text
      and sw.headers.get("service-worker-allowed") == "/" and "javascript" in sw.headers.get("content-type", ""), sw.headers)
check("W2 web app manifest ready for the iPhone home screen (standalone, id, scope)", man.get("display") == "standalone" and man.get("id") == "/" and man.get("scope") == "/", man)
g1 = a.get("/api/notify/webpush").json(); g2 = a.get("/api/notify/webpush").json()
vap = b64u_dec(g1["public_key"])
check("W2 VAPID public key: valid P-256 point, created once and kept", len(vap) == 65 and ec256.on_curve(ec256.decode_point(vap)) and g1["public_key"] == g2["public_key"] and g1["devices"] == [], g1)

# thiết bị giả: khoá P-256 + auth secret như trình duyệt tạo
ua = ec.generate_private_key(ec.SECP256R1()); ua_pub = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
auth = os.urandom(16)
sub = {"endpoint": PUSH + "/push/dev1", "keys": {"p256dh": b64u(ua_pub), "auth": b64u(auth)}}
bad = [a.post("/api/notify/webpush/subscribe", json={"subscription": {**sub, "endpoint": "http://127.0.0.1:8775/push/x"}}).status_code,
       a.post("/api/notify/webpush/subscribe", json={"subscription": {**sub, "keys": {"p256dh": b64u(b"\x04" + b"\x01" * 64), "auth": b64u(auth)}}}).status_code,
       a.post("/api/notify/webpush/subscribe", json={"subscription": {**sub, "keys": {"p256dh": b64u(ua_pub), "auth": "abc"}}}).status_code]
check("W3 invalid subscriptions refused (http endpoint, key not on the curve, bad auth secret)", bad == [400, 400, 400], bad)
r = a.post("/api/notify/webpush/subscribe", json={"subscription": sub, "name": "iPhone · Safari"}).json()
n = a.get("/api/notify").json()
check("W3 subscribe: device saved; a Web Push channel with every event is created automatically",
      r["ok"] and r["device"]["name"] == "iPhone · Safari" and any(c["type"] == "webpush" and set(c["events"]) == set(n["events"]) for c in n["channels"]), (r, n["channels"]))
r2 = a.post("/api/notify/webpush/subscribe", json={"subscription": sub, "name": "iPhone (renamed)"}).json()
check("W3 the same device subscribing again replaces its entry (no duplicates)", len(a.get("/api/notify/webpush").json()["devices"]) == 1)

def decrypt(body):
    salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_pub = body[21:21 + idlen]; ct = body[21 + idlen:]
    secret = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ua_pub + as_pub).derive(secret)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ct, None)
    return rs, json.loads(plain.rstrip(b"\x00")[:-1])  # bỏ dấu kết thúc 0x02

GOT.clear()
t = a.post("/api/notify/webpush/test", json={}).json()
req = GOT[-1] if GOT else {}
hd = req.get("headers", {})
check("W4 test push accepted by the push service (201)", t["ok"] and req.get("path") == "/push/dev1", (t, GOT))
check("W4 push headers: aes128gcm, TTL, Urgency, octet-stream", hd.get("content-encoding") == "aes128gcm" and hd.get("ttl") == "86400"
      and hd.get("urgency") in ("normal", "high") and hd.get("content-type") == "application/octet-stream", hd)
rs, msg = decrypt(req.get("body", b""))
check("W4 the device decrypts the message with the standard library (RFC 8291): title, body, url", rs == 4096 and msg.get("title") and msg.get("url") == "/" and "body" in msg, msg)
auth_h = hd.get("authorization", "")
jwt = auth_h.split("t=")[1].split(",")[0].strip() if "t=" in auth_h else ""
k = auth_h.split("k=")[1].strip() if "k=" in auth_h else ""
hdr64, cl64, sg64 = (jwt.split(".") + ["", "", ""])[:3]
claims = json.loads(b64u_dec(cl64)) if cl64 else {}
try:
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64u_dec(k))
    sgb = b64u_dec(sg64)
    pub.verify(encode_dss_signature(int.from_bytes(sgb[:32], "big"), int.from_bytes(sgb[32:], "big")), f"{hdr64}.{cl64}".encode(), ec.ECDSA(hashes.SHA256()))
    vok = True
except Exception as e:
    vok = repr(e)
check("W4 VAPID JWT (RFC 8292) verifies like Apple / Google would: ES256, aud = push origin, exp <= 24 h, sub set, k = our key",
      vok is True and json.loads(b64u_dec(hdr64)).get("alg") == "ES256" and claims.get("aud") == PUSH and 0 < claims.get("exp", 0) - time.time() <= 86400
      and claims.get("sub", "").startswith(("mailto:", "https:")) and k == g1["public_key"], (vok, claims, k))
# qua hệ thống thông báo (kênh Web Push): Gửi thử kênh
GOT.clear()
ch = next(c for c in a.get("/api/notify").json()["channels"] if c["type"] == "webpush")
tc = a.post("/api/notify/test", json={"id": ch["id"]})
check("W5 notification channel 'Web Push' delivers through the normal notification system", tc.status_code == 200 and len(GOT) == 1 and decrypt(GOT[0]["body"])[1].get("title"), (tc.text, len(GOT)))
dev = a.get("/api/notify/webpush").json()["devices"][0]
check("W5 device shows the push service and the last delivery time", dev["service"] == "127.0.0.1" and dev["last_ok"] > 0 and not dev["last_error"], dev)
# thiết bị đã huỷ đăng ký (410) -> tự xoá
ua2 = ec.generate_private_key(ec.SECP256R1())
sub2 = {"endpoint": PUSH + "/gone/dev2", "keys": {"p256dh": b64u(ua2.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)), "auth": b64u(os.urandom(16))}}
a.post("/api/notify/webpush/subscribe", json={"subscription": sub2, "name": "Old phone"})
t2 = a.post("/api/notify/webpush/test", json={}).json()
names = [d["name"] for d in a.get("/api/notify/webpush").json()["devices"]]
check("W6 a device the push service reports as gone (410) is removed automatically; the others still get it",
      t2["ok"] and "removed" in t2["message"] and names == ["iPhone (renamed)"], (t2, names))
did = a.get("/api/notify/webpush").json()["devices"][0]["id"]
de = a.post("/api/notify/webpush/delete", json={"id": did})
check("W6 remove a device", de.status_code == 200 and a.get("/api/notify/webpush").json()["devices"] == [])
nt = a.post("/api/notify/webpush/test", json={}).json()
check("W6 test with no device explains what to do", not nt["ok"] and "No device" in nt["message"], nt)
# W8 kiểu thông báo của app điện thoại (0.25.1): không emoji / dấu "•", tiêu đề gọn, gộp nhiều app, số trên biểu tượng
from app.core import notify  # noqa: E402
from app.core.database import init_db  # noqa: E402
init_db()  # dữ liệu riêng của tiến trình test (APP_DATA_DIR = wp_testproc, đặt ở đầu file)
apps1 = [{"name": "bark", "title": "Bark Server", "from": "v2.4.0", "to": "v2.4.1"}]
t1 = notify.native("update_available", "🆕 Updates available (1)", "• Bark Server: v2.4.0 → v2.4.1", {"apps": apps1, "pending": 1})
apps6 = [{"name": f"a{i}", "title": f"App {i}", "from": "1.0", "to": "1.1"} for i in range(6)]
t6 = notify.native("update_available", "🆕 Updates available (6)", "", {"apps": apps6})
check("W8 one update: title = app name, one short line 'Update available: 2.4.0 → 2.4.1' (no emoji / bullet / 'v')",
      t1 == ("Bark Server", "Update available: 2.4.0 → 2.4.1"), t1)
check("W8 six updates: '6 updates available' + one line 'App 0, App 1, App 2 and 3 more'", t6 == ("6 updates available", "App 0, App 1, App 2 and 3 more"), t6)
ok1 = notify.native("update_success", "✅ Updated: Nextcloud", "29.0 → 30.0", {"app": "nextcloud", "title": "Nextcloud", "from": "29.0", "to": "v30.0", "status": "success"})
rb = notify.native("update_failed", "↩️ Update failed — rolled back: Nextcloud", "29.0 → 30.0\nhealth check failed", {"app": "nextcloud", "title": "Nextcloud", "from": "29.0", "status": "rolled_back"})
other = notify.native("disk_low", "💾 Disk almost full", "• /DATA 95% used", {})
check("W8 updated / rolled back / other events read like phone apps",
      ok1 == ("Nextcloud", "Updated to 30.0") and rb == ("Nextcloud", "Update failed, back on 29.0")
      and other == ("Disk almost full", "/DATA 95% used") and all("\n" not in x for x in ok1 + rb + other + t1 + t6), (ok1, rb, other))
GOT.clear()
a.post("/api/notify/webpush/subscribe", json={"subscription": sub, "name": "iPhone"})
import asyncio  # noqa: E402
os.environ.update({"SSL_CERT_FILE": f"{S}/push.crt", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
webpush.add(sub, "iPhone", "admin")  # thiết bị trong dữ liệu của tiến trình test -> gửi qua đúng đường của kênh Web Push
n0 = len(GOT)
r8 = asyncio.run(notify._send({"type": "webpush", "config": {}}, "🆕 Updates available (1)", "• Bark Server: v2.4.0 → v2.4.1",
                              "update_available", {"apps": apps1, "pending": 3}))
m7 = decrypt(GOT[-1]["body"])[1] if len(GOT) > n0 else {}
check("W8 'update available' push: phone-style text, opens the Updates list, app icon badge = 3 pending updates",
      r8[0] and m7.get("title") == "Bark Server" and m7.get("body") == "Update available: 2.4.0 → 2.4.1"
      and m7.get("url") == "/?filter=updates" and m7.get("badge") == 3, (r8, m7))
ch = next(c for c in a.get("/api/notify").json()["channels"] if c["type"] == "webpush")
tc = a.post("/api/notify/test", json={"id": ch["id"]})
m8 = decrypt(GOT[-1]["body"])[1] if GOT else {}
check("W8 'Send test' arrives as 'Notifications are on' (no emoji)", tc.status_code == 200 and m8.get("title") == "Notifications are on" and "badge" not in m8, m8)
# quyền
a.post("/api/users", json={"new": True, "username": "viewer1", "password": "Viewer-Passw0rd!1", "role": "viewer"})
vw = httpx.Client(base_url=B, headers=H); vw.post("/api/auth/login", json={"username": "viewer1", "password": "Viewer-Passw0rd!1"})
check("W7 View only cannot read the push setup or subscribe devices (403)",
      vw.get("/api/notify/webpush").status_code == 403 and vw.post("/api/notify/webpush/subscribe", json={"subscription": sub}).status_code == 403)
proc.terminate(); srv.shutdown()
print(f"SUMMARY {sum(R)} / {len(R)}")
