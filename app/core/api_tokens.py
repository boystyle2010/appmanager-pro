"""
API token cho tự động hoá (Home Assistant, script/CI, Uptime Kuma…).

- Token dạng `amp_<40 ký tự ngẫu nhiên>`; chỉ hiện MỘT lần lúc tạo, server chỉ lưu mã băm SHA-256
  (token đủ ngẫu nhiên nên không cần hàm băm chậm như mật khẩu).
- Gửi kèm header `Authorization: Bearer amp_…` (không nhận token trong URL để không lộ qua log / lịch sử trình duyệt).
- Quyền: read (chỉ đọc) < update (kiểm tra / cập nhật / khởi động lại app) < full (mọi thứ trừ tài khoản & token).
- Hạn dùng tuỳ chọn, giới hạn IP / dải mạng tuỳ chọn; sai token nhiều lần bị khoá IP như đăng nhập sai.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
import time
from typing import Any, Optional

from app.core.database import get_setting, set_setting

SETTING = "api_tokens"
PREFIX = "amp_"
MAX_TOKENS = 25
SCOPES = ("read", "update", "full")
_LOCK = threading.Lock()
_LAST_WRITE: dict[str, float] = {}

# Không token nào được dùng các API này (tài khoản, 2FA, token, mật khẩu registry) — chỉ người đăng nhập trên web.
_NEVER = (
    re.compile(r"^/api/auth(/|$)"),
    re.compile(r"^/api/tokens(/|$)"),
    re.compile(r"^/api/system/registry-logins(/|$)"),
    re.compile(r"^/api/servers(/|$)"),   # máy chủ khác: chứa Token của máy khác -> chỉ người đăng nhập
)
# Quyền "update": ngoài đọc, được kiểm tra bản mới, cập nhật app (qua job), cập nhật tất cả, start/stop/restart,
# khôi phục bản sao lưu cấu hình app.
_UPDATE_POST = (
    re.compile(r"^/api/updates/check$"),
    re.compile(r"^/api/apps/[^/]+/check$"),
    re.compile(r"^/api/apps/[^/]+/update$"),
    re.compile(r"^/api/update-all$"),
    re.compile(r"^/api/apps/[^/]+/(start|stop|restart)$"),
    re.compile(r"^/api/backups/restore$"),   # 0.21: khôi phục cấu hình app (máy chính khôi phục máy phụ từ xa)
)


class TokenError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(get_setting(SETTING, "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    set_setting(SETTING, json.dumps(items))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_ips(raw: Any) -> list[str]:
    """'192.168.1.0/24, 10.0.0.5' hoặc list -> danh sách mạng hợp lệ (chuẩn hoá). Sai định dạng -> ValueError."""
    items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw or ""))
    out: list[str] = []
    for it in items:
        it = str(it).strip()
        if not it:
            continue
        try:
            net = str(ipaddress.ip_network(it, strict=False))
        except ValueError:
            raise ValueError(f"Invalid IP address or network: {it}")
        if net not in out:
            out.append(net)
    if len(out) > 20:
        raise ValueError("At most 20 IP addresses / networks")
    return out


def public(t: dict[str, Any]) -> dict[str, Any]:
    """Thông tin hiển thị (KHÔNG có mã băm)."""
    now = time.time()
    exp = float(t.get("expires") or 0)
    return {
        "id": t["id"], "name": t["name"], "scope": t["scope"], "hint": t.get("hint", ""),
        "created": t.get("created", 0), "expires": exp, "expired": bool(exp and exp <= now),
        "ips": t.get("ips") or [], "last_used": t.get("last_used", 0), "last_ip": t.get("last_ip", ""),
        "created_by": t.get("created_by", ""),
    }


def list_tokens() -> list[dict[str, Any]]:
    return [public(t) for t in _load()]


def create(name: str, scope: str, days: int, ips: Any, created_by: str = "") -> tuple[dict[str, Any], str]:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not 1 <= len(name) <= 40:
        raise ValueError("Name must be 1-40 characters")
    if scope not in SCOPES:
        raise ValueError("Invalid permission")
    days = int(days or 0)
    if days < 0 or days > 3650:
        raise ValueError("Invalid expiry")
    nets = parse_ips(ips)
    with _LOCK:
        items = _load()
        if len(items) >= MAX_TOKENS:
            raise ValueError(f"At most {MAX_TOKENS} tokens; delete one you no longer use")
        if any(t["name"].lower() == name.lower() for t in items):
            raise ValueError("A token with this name already exists")
        plain = PREFIX + secrets.token_urlsafe(30)[:40]
        now = time.time()
        rec = {
            "id": secrets.token_hex(4), "name": name, "scope": scope, "hash": _hash(plain),
            "hint": plain[: len(PREFIX) + 4] + "…" + plain[-4:], "created": now,
            "expires": now + days * 86400 if days else 0, "ips": nets, "last_used": 0, "last_ip": "",
            "created_by": created_by,
        }
        items.append(rec)
        _save(items)
    return public(rec), plain


def delete(token_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        items = _load()
        rec = next((t for t in items if t["id"] == token_id), None)
        if rec:
            _save([t for t in items if t["id"] != token_id])
    return public(rec) if rec else None


def bearer(headers) -> str:
    """Token trong header Authorization (chỉ nhận dạng Bearer amp_…); '' nếu không có."""
    auth = (headers.get("authorization") or "").strip()
    if auth[:7].lower() != "bearer ":
        return ""
    return auth[7:].strip()


def scope_allows(scope: str, method: str, path: str) -> bool:
    if any(r.match(path) for r in _NEVER):
        return False
    method = method.upper()
    if method in ("GET", "HEAD"):
        return True
    if scope == "full":
        return True
    if scope == "update" and method == "POST":
        return any(r.match(path) for r in _UPDATE_POST)
    return False


def min_scope(method: str, path: str) -> str:
    """Quyền thấp nhất đủ để gọi API (cho tài liệu); '' = token không dùng được."""
    return next((s for s in SCOPES if scope_allows(s, method, path)), "")


def verify(token: str, ip: str, method: str, path: str) -> dict[str, Any]:
    """Trả bản ghi token nếu hợp lệ; TokenError(401) sai / hết hạn, (403) sai IP hoặc thiếu quyền."""
    if not token.startswith(PREFIX) or len(token) > 100:
        raise TokenError(401, "Invalid API token")
    h = _hash(token)
    items = _load()
    rec = next((t for t in items if hmac.compare_digest(t.get("hash", ""), h)), None)
    if not rec:
        raise TokenError(401, "Invalid API token")
    exp = float(rec.get("expires") or 0)
    if exp and exp <= time.time():
        raise TokenError(401, "This API token has expired")
    nets = rec.get("ips") or []
    if nets:
        try:
            addr = ipaddress.ip_address(ip)
            ok = any(addr in ipaddress.ip_network(n, strict=False) for n in nets)
        except ValueError:
            ok = False
        if not ok:
            raise TokenError(403, f"This API token is not allowed from {ip}")
    if not scope_allows(rec["scope"], method, path):
        raise TokenError(403, f"This API token ({rec['scope']}) is not allowed to {method} {path}")
    _touch(rec["id"], ip)
    return rec


def _touch(token_id: str, ip: str) -> None:
    """Ghi lần dùng gần nhất (tối đa 1 lần / 30 giây mỗi token để không ghi database liên tục)."""
    now = time.time()
    if now - _LAST_WRITE.get(token_id, 0) < 30:
        return
    _LAST_WRITE[token_id] = now
    with _LOCK:
        items = _load()
        for t in items:
            if t["id"] == token_id:
                t["last_used"], t["last_ip"] = now, ip
        _save(items)
