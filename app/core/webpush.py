"""
Web Push (0.25): thông báo đẩy thẳng tới trình duyệt / app thêm vào màn hình chính (iPhone iOS 16.4+, Android, máy tính)
— không cần app thông báo riêng.

- Khoá VAPID (RFC 8292): cặp khoá P-256 tạo một lần, lưu trong setting `webpush_vapid`. Mỗi lần gửi ký JWT ES256
  (aud = gốc của địa chỉ push, exp 12 giờ, sub = mailto / https) -> header `Authorization: vapid t=…, k=…`.
- Mã hoá nội dung (RFC 8291, aes128gcm): khoá tạm P-256 cho mỗi tin, ECDH với khoá p256dh của thiết bị, HKDF với
  auth secret -> AES-128-GCM. Dịch vụ push (Apple / Google / Mozilla…) không đọc được nội dung.
- Thiết bị đăng ký lưu trong setting `webpush_subs`; dịch vụ push trả 404 / 410 (thiết bị huỷ đăng ký) -> tự xoá.
- Toán học P-256 trong ec256.py, AES trong aes.py — thuần Python (không cần thư viện cryptography, chạy được armv7).
- Trình duyệt chỉ cho đăng ký push trên HTTPS (hoặc localhost). iPhone: phải "Thêm vào MH chính" rồi mở từ biểu tượng đó.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.core import aes, ec256
from app.core.database import get_setting, set_setting

VAPID_SETTING = "webpush_vapid"
SUBS_SETTING = "webpush_subs"
MAX_SUBS = 50
RECORD_SIZE = 4096
MAX_PAYLOAD = 3000  # đủ cho tiêu đề + nội dung; dịch vụ push nhận tối đa ~4 KB sau mã hoá
DEFAULT_SUBJECT = "mailto:appmanager-pro@users.noreply.github.com"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------------------------------------------------------- VAPID
def vapid() -> dict[str, Any]:
    """Khoá VAPID (tạo một lần). Đổi khoá = mọi thiết bị phải đăng ký lại."""
    try:
        v = json.loads(get_setting(VAPID_SETTING, "") or "{}")
        if v.get("d") and v.get("public"):
            return v
    except Exception:
        pass
    d, pub = ec256.keypair()
    v = {"d": format(d, "x"), "public": b64u(pub), "created": int(time.time())}
    set_setting(VAPID_SETTING, json.dumps(v))
    return v


def public_key() -> str:
    return vapid()["public"]


def vapid_headers(endpoint: str, subject: str = DEFAULT_SUBJECT, now: Optional[int] = None) -> dict[str, str]:
    v = vapid()
    p = urlparse(endpoint)
    claims = {"aud": f"{p.scheme}://{p.netloc}", "exp": int(now or time.time()) + 12 * 3600, "sub": subject}
    signing = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "." + \
        b64u(json.dumps(claims, separators=(",", ":")).encode())
    sig = ec256.sign(int(v["d"], 16), signing.encode())
    return {"Authorization": f"vapid t={signing}.{b64u(sig)}, k={v['public']}"}


# ---------------------------------------------------------------- RFC 8291 (aes128gcm)
def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload: bytes, ua_public: bytes, auth_secret: bytes, *, as_private: Optional[int] = None,
            salt: Optional[bytes] = None) -> bytes:
    """Nội dung đã mã hoá theo RFC 8291 (một bản ghi). as_private / salt chỉ truyền khi test bằng véc-tơ chuẩn."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("Push message too large")
    if len(auth_secret) != 16:
        raise ValueError("Invalid auth secret")
    ec256.decode_point(ua_public)  # điểm phải hợp lệ
    if as_private is None:
        as_private, as_public = ec256.keypair()
    else:
        as_public = ec256.public_from_private(as_private)
    salt = salt or secrets.token_bytes(16)
    ecdh_secret = ec256.ecdh(as_private, ua_public)
    ikm = _hkdf(auth_secret, ecdh_secret, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = payload + b"\x02"  # dấu kết thúc bản ghi cuối
    header = salt + struct.pack("!I", RECORD_SIZE) + bytes([len(as_public)]) + as_public
    return header + aes.gcm_encrypt(cek, nonce, record)


# ---------------------------------------------------------------- thiết bị
def subscriptions() -> list[dict[str, Any]]:
    try:
        data = json.loads(get_setting(SUBS_SETTING, "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    set_setting(SUBS_SETTING, json.dumps(items))


def public_sub(s: dict[str, Any]) -> dict[str, Any]:
    host = urlparse(s.get("endpoint", "")).hostname or ""
    service = ("Apple" if host.endswith("push.apple.com") else "Google" if "googleapis.com" in host
               else "Mozilla" if "mozilla" in host else "Microsoft" if "notify.windows.com" in host else host)
    return {"id": s["id"], "name": s.get("name", ""), "user": s.get("user", ""), "service": service,
            "ep": hashlib.sha256(s.get("endpoint", "").encode()).hexdigest()[:16],  # để trình duyệt nhận ra "thiết bị này"
            "created": s.get("created", 0), "last_ok": s.get("last_ok", 0), "last_error": s.get("last_error", "")}


def add(sub: dict[str, Any], name: str, user: str) -> dict[str, Any]:
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    p = urlparse(endpoint)
    if p.scheme != "https" or not p.hostname or len(endpoint) > 2048:
        raise ValueError("Invalid push subscription (endpoint must be HTTPS)")
    try:
        ec256.decode_point(b64u_dec(str(keys.get("p256dh") or "")))
        if len(b64u_dec(str(keys.get("auth") or ""))) != 16:
            raise ValueError
    except Exception:
        raise ValueError("Invalid push subscription keys")
    name = re.sub(r"\s+", " ", (name or "").strip())[:60] or "Device"
    items = [s for s in subscriptions() if s["endpoint"] != endpoint]  # cùng thiết bị đăng ký lại -> thay
    if len(items) >= MAX_SUBS:
        raise ValueError(f"At most {MAX_SUBS} devices")
    rec = {"id": secrets.token_hex(5), "endpoint": endpoint, "p256dh": keys["p256dh"], "auth": keys["auth"],
           "name": name, "user": user, "created": int(time.time()), "last_ok": 0, "last_error": ""}
    _save(items + [rec])
    return rec


def remove(sub_id: str) -> Optional[dict[str, Any]]:
    items = subscriptions()
    rec = next((s for s in items if s["id"] == sub_id), None)
    if rec:
        _save([s for s in items if s["id"] != sub_id])
    return rec


def _mark(sub_id: str, ok: bool, err: str = "", drop: bool = False) -> None:
    items = subscriptions()
    if drop:
        _save([s for s in items if s["id"] != sub_id])
        return
    for s in items:
        if s["id"] == sub_id:
            if ok:
                s["last_ok"], s["last_error"] = int(time.time()), ""
            else:
                s["last_error"] = err[:200]
    _save(items)


# ---------------------------------------------------------------- gửi
async def send_one(client: httpx.AsyncClient, s: dict[str, Any], message: dict[str, Any], urgent: bool = False,
                   ttl: int = 86400) -> tuple[bool, str]:
    body = encrypt(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                   b64u_dec(s["p256dh"]), b64u_dec(s["auth"]))
    headers = {**vapid_headers(s["endpoint"]), "TTL": str(ttl), "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "Urgency": "high" if urgent else "normal"}
    try:
        r = await client.post(s["endpoint"], content=body, headers=headers)
    except httpx.HTTPError as exc:
        _mark(s["id"], False, f"connection: {str(exc)[:150]}")
        return False, f"{s.get('name')}: cannot reach the push service"
    if r.status_code in (200, 201, 202, 204):
        _mark(s["id"], True)
        return True, f"{s.get('name')}: OK"
    if r.status_code in (404, 410):  # thiết bị đã huỷ đăng ký / hết hạn
        _mark(s["id"], False, drop=True)
        return False, f"{s.get('name')}: subscription expired — removed (turn notifications on again on that device)"
    detail = (r.text or "")[:150].strip()
    _mark(s["id"], False, f"HTTP {r.status_code} {detail}")
    return False, f"{s.get('name')}: push service answered HTTP {r.status_code} {detail}".strip()


async def send_all(title: str, body: str, *, url: str = "/", tag: str = "", urgent: bool = False,
                   only: Optional[str] = None) -> tuple[bool, str]:
    """Gửi tới mọi thiết bị (hoặc một thiết bị). Thành công nếu ít nhất một thiết bị nhận."""
    from app.core import net
    targets = [s for s in subscriptions() if not only or s["id"] == only]
    if not targets:
        return False, "No device has turned on push notifications yet"
    msg = {"title": title[:200], "body": (body or "")[:1500], "url": url, "tag": tag or "appmanager", "ts": int(time.time())}
    results = []
    async with net.client(timeout=15, follow_redirects=False) as c:
        for s in targets:
            results.append(await send_one(c, s, msg, urgent))
    ok = any(r[0] for r in results)
    return ok, "; ".join(r[1] for r in results)[:500]
