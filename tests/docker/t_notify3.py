"""Mã hoá nội dung tin (Bark AES-CBC, Webhook AES-256-GCM) + Chế độ riêng tư (mọi kênh).
Giải mã lại bằng thư viện cryptography chuẩn (như app Bark / máy chủ webhook làm). Webhook nhận thật qua HTTP."""
import asyncio, base64, hashlib, hmac, json, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db(); set_setting("notify_channels", "[]"); set_setting("notify_lang", "vi")
import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core import notify, net
R = []
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:600]}"), flush=True)
HOOK = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        HOOK.append((raw, self.headers.get("X-AppManager-Signature"))); self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
threading.Thread(target=HTTPServer(("127.0.0.1", 8097), H).serve_forever, daemon=True).start()
TITLE, BODY = "❌ Cập nhật thất bại", "nextcloud: 29.0 → 30.0 (đã quay lại) · IP 192.168.68.101"
NTITLE = "Cập nhật thất bại"  # Bark / Web Push: kiểu thông báo của app điện thoại (không emoji)

# B1 Bark mã hoá (giả lập máy chủ Bark, giải mã như app iPhone)
seen = []
def handler(req): seen.append(json.loads(req.content)); return httpx.Response(200, json={"code": 200})
orig = net.client; net.client = lambda **kw: net.GuardedClient(transport=httpx.MockTransport(handler), **kw)
for bits, key in ((256, "K" * 32), (128, "abcdefghijklmnop"), (192, "x" * 24)):
    seen.clear()
    ch = {"type": "bark", "config": {"device_key": "DK", "encrypt": "1", "enc_key": key, "enc_iv": "0123456789abcdef"}}
    ok = asyncio.run(notify._send(ch, TITLE, BODY, "update_failed", {}))
    pl = seen[0]
    d = Cipher(algorithms.AES(key.encode()), modes.CBC(b"0123456789abcdef")).decryptor()
    u = padding.PKCS7(128).unpadder(); plain = json.loads(u.update(d.update(base64.b64decode(pl["ciphertext"])) + d.finalize()) + u.finalize())
    check(f"B1 Bark AES{bits}-CBC: only ciphertext leaves AppManager, the iPhone key decrypts title + body",
          ok[0] and "title" not in pl and "body" not in pl and "nextcloud" not in json.dumps(pl) and plain["title"] == NTITLE and plain["body"] == BODY and plain.get("icon", "").endswith("/icon.png") and pl["iv"] == "0123456789abcdef", (pl, plain))
seen.clear()
asyncio.run(notify._send({"type": "bark", "config": {"device_key": "DK"}}, TITLE, BODY, "update_failed", {}))
check("B2 Bark without encryption: same text, phone style (no emoji) + AppManager icon", seen[0]["title"] == NTITLE and seen[0]["body"] == BODY and seen[0]["icon"].endswith("/icon.png"), seen)

# P1 chế độ riêng tư (Telegram giả lập)
tg = []
net.client = lambda **kw: net.GuardedClient(transport=httpx.MockTransport(lambda r: (tg.append(json.loads(r.content)), httpx.Response(200, json={"ok": True}))[1]), **kw)
asyncio.run(notify._send({"type": "telegram", "private": True, "config": {"bot_token": "1:A", "chat_id": "1"}}, TITLE, BODY, "update_failed", {"app": "nextcloud"}))
check("P1 Private mode (Telegram): only the title + 'open AppManager', no app name / IP", tg[0]["text"].startswith(TITLE) and "nextcloud" not in tg[0]["text"] and "192.168" not in tg[0]["text"] and "Mở AppManager" in tg[0]["text"], tg)
net.client = orig

# W1 webhook mã hoá, nhận thật qua HTTP, giải mã AES-256-GCM, chữ ký HMAC vẫn đúng
wh = notify.upsert_channel({"type": "webhook", "name": "Hook", "config": {"url": "http://127.0.0.1:8097/h", "secret": "sig", "encrypt": "1", "enc_key": "my-very-secret-key-123"}})
r = notify._deliver(wh, TITLE, BODY, "update_failed", {"app": "nextcloud"})
raw, sig = HOOK[-1]; body = json.loads(raw)
blob = base64.b64decode(body["encrypted"])
plain = json.loads(AESGCM(hashlib.sha256(b"my-very-secret-key-123").digest()).decrypt(blob[:12], blob[12:], None))
check("W1 Webhook AES-256-GCM: body unreadable without the key, decrypts to the normal payload",
      r[0] and "nextcloud" not in raw.decode() and body["alg"] == "AES-256-GCM" and plain["event"] == "update_failed" and plain["data"]["app"] == "nextcloud", (raw[:120], plain))
check("W1 HMAC signature still covers the (encrypted) body", sig == "sha256=" + hmac.new(b"sig", raw, hashlib.sha256).hexdigest())
notify._deliver(wh, TITLE, BODY, "update_failed", {})
check("W2 a new random nonce for every message", json.loads(HOOK[-1][0])["encrypted"][:16] != body["encrypted"][:16])
whp = notify.upsert_channel({"type": "webhook", "name": "Private hook", "private": True, "config": {"url": "http://127.0.0.1:8097/p"}})
notify._deliver(whp, TITLE, BODY, "update_failed", {"app": "nextcloud"})
pp = json.loads(HOOK[-1][0])
check("P2 Private mode (Webhook): no details and empty data", pp["data"] == {} and "nextcloud" not in json.dumps(pp) and whp["private"], pp)

# V1 kiểm tra dữ liệu nhập + bí mật bị ẩn
errs = []
for d in ({"type": "telegram", "config": {"bot_token": "1:A", "chat_id": "1", "encrypt": "1", "enc_key": "x" * 32}},
          {"type": "bark", "config": {"device_key": "K", "encrypt": "1", "enc_key": "short", "enc_iv": "0123456789abcdef"}},
          {"type": "bark", "config": {"device_key": "K", "encrypt": "1", "enc_key": "x" * 32, "enc_iv": "123"}},
          {"type": "webhook", "config": {"url": "http://x", "encrypt": "1", "enc_key": "short"}}):
    try: notify.upsert_channel(d); errs.append("saved")
    except ValueError as e: errs.append(str(e)[:60])
check("V1 refused: encryption on Telegram, wrong Bark key / IV length, short webhook key", "saved" not in errs, errs)
bk = notify.upsert_channel({"type": "bark", "name": "iPhone", "config": {"device_key": "DK", "encrypt": "1", "enc_key": "K" * 32, "enc_iv": "0123456789abcdef"}})
mc = next(c for c in notify.masked_channels() if c["id"] == bk["id"])["config"]
notify.upsert_channel({"id": bk["id"], "type": "bark", "name": "iPhone 2", "config": {"device_key": "", "encrypt": "1", "enc_key": "", "enc_iv": ""}})
kept = next(c for c in notify.channels() if c["id"] == bk["id"])["config"]
check("V2 key + IV never returned to the browser; empty on edit keeps them", mc["enc_key"] == "" and mc["has_enc_iv"] and kept["enc_key"] == "K" * 32 and kept["enc_iv"] == "0123456789abcdef", (mc, kept))
notify.upsert_channel({"id": bk["id"], "type": "bark", "name": "iPhone 3", "config": {"device_key": "", "encrypt": ""}})
check("V3 turning encryption off removes the flag", "encrypt" not in next(c for c in notify.channels() if c["id"] == bk["id"])["config"])
print(f"\nSUMMARY {sum(R)} / {len(R)}")
