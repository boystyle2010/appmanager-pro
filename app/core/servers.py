"""
Quản lý nhiều máy chủ (0.18) — mô hình "máy chính + máy phụ".

Giao thức: máy chính gọi REST API (HTTP hoặc HTTPS) của AppManager trên máy phụ, xác thực bằng API Token
(`Authorization: Bearer amp_…`, tạo trong Cài đặt → API Token của máy phụ). Không mở Docker socket ra mạng,
không cài agent riêng: việc thật (pull, tạo lại container, kiểm tra sức khoẻ, tự quay lại) vẫn do AppManager
của từng máy làm. Máy chính chỉ chuyển yêu cầu và hiển thị kết quả.

Yêu cầu: máy phụ chạy AppManager >= 0.17.0, máy chính kết nối được tới địa chỉ:cổng của máy phụ (LAN / VPN /
reverse proxy HTTPS), Token quyền "Cập nhật" (hoặc "Chỉ đọc" nếu chỉ xem). Token lưu trong database của máy chính
(cần để gọi máy phụ) và không bao giờ trả về trình duyệt.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.core import net
from app.core.database import get_setting, set_setting

SETTING = "remote_servers"
MAX_SERVERS = 20
MIN_VERSION = (0, 17, 0)
_LOCK = threading.Lock()
_STATUS: dict[str, dict[str, Any]] = {}   # id -> trạng thái lần kiểm tra gần nhất (bộ nhớ)

# Trường của app trả về trình duyệt (bớt dữ liệu nội bộ của máy phụ)
APP_FIELDS = ("name", "title", "icon", "status", "version", "remote_version", "has_update", "can_update", "is_self",
              "manage", "source", "image", "image_tag", "uptime", "auto_update", "is_skipped")


class RemoteError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(get_setting(SETTING, "[]") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    set_setting(SETTING, json.dumps(items))


def normalize_url(raw: str) -> str:
    u = (raw or "").strip().rstrip("/")
    if u and "://" not in u:
        u = "http://" + u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Enter the address of the other AppManager, e.g. http://192.168.1.20:8098")
    if p.query or p.fragment or p.username or p.password:
        raise ValueError("The address must not contain a user name, password, ? or #")
    return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")


def public(s: dict[str, Any]) -> dict[str, Any]:
    tok = s.get("token") or ""
    return {
        "id": s["id"], "name": s["name"], "url": s["url"], "verify_tls": bool(s.get("verify_tls", True)),
        "has_token": bool(tok), "token_hint": (tok[:8] + "…" + tok[-4:]) if len(tok) > 12 else "",
        "created": s.get("created", 0), "https": s["url"].startswith("https://"),
        "status": _STATUS.get(s["id"], {}),
    }


def list_servers() -> list[dict[str, Any]]:
    return [public(s) for s in _load()]


def get(server_id: str) -> dict[str, Any]:
    s = next((x for x in _load() if x["id"] == server_id), None)
    if not s:
        raise RemoteError("Server not found", 404)
    return s


def build(data: dict[str, Any], existing: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Kiểm tra dữ liệu nhập; Token để trống khi sửa = giữ Token cũ."""
    name = re.sub(r"\s+", " ", str(data.get("name") or "").strip())
    if not 1 <= len(name) <= 40:
        raise ValueError("Name must be 1-40 characters")
    url = normalize_url(str(data.get("url") or ""))
    token = str(data.get("token") or "").strip() or (existing or {}).get("token", "")
    if not token.startswith("amp_") or len(token) > 100:
        raise ValueError("Paste an API Token created on the other AppManager (Settings → API Token), it starts with amp_")
    return {"id": (existing or {}).get("id") or secrets.token_hex(4), "name": name, "url": url, "token": token,
            "verify_tls": bool(data.get("verify_tls", True)), "created": (existing or {}).get("created") or time.time()}


def upsert(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        items = _load()
        existing = next((x for x in items if x["id"] == data.get("id")), None) if data.get("id") else None
        if data.get("id") and not existing:
            raise ValueError("Server not found")
        rec = build(data, existing)
        others = [x for x in items if x["id"] != rec["id"]]
        if any(x["name"].lower() == rec["name"].lower() for x in others):
            raise ValueError("A server with this name already exists")
        if any(x["url"] == rec["url"] for x in others):
            raise ValueError("This address is already added")
        if not existing and len(items) >= MAX_SERVERS:
            raise ValueError(f"At most {MAX_SERVERS} servers")
        _save(others + [rec] if not existing else [rec if x["id"] == rec["id"] else x for x in items])
    _STATUS.pop(rec["id"], None)
    return rec


def delete(server_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        items = _load()
        rec = next((x for x in items if x["id"] == server_id), None)
        if rec:
            _save([x for x in items if x["id"] != server_id])
    _STATUS.pop(server_id, None)
    return rec


# ---------------------------------------------------------------- gọi máy phụ
def _version_tuple(v: str) -> tuple[int, ...]:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _detail(resp: httpx.Response) -> str:
    try:
        d = resp.json()
        return str(d.get("detail") or d.get("error") or "")[:300] if isinstance(d, dict) else ""
    except Exception:
        return (resp.text or "")[:200]


async def call(s: dict[str, Any], method: str, path: str, body: Any = None, timeout: float = 20) -> Any:
    """Gọi API của máy phụ; lỗi -> RemoteError với lời giải thích dễ hiểu."""
    url = s["url"] + path
    headers = {"Authorization": f"Bearer {s['token']}", "Accept": "application/json",
               "User-Agent": "AppManager-Pro (multi-server)"}
    try:
        async with net.client(verify=bool(s.get("verify_tls", True)), follow_redirects=False,
                              timeout=httpx.Timeout(timeout, connect=6.0)) as c:
            resp = await c.request(method, url, headers=headers, json=body if method != "GET" else None)
    except net.RateLimited as exc:
        raise RemoteError(f"{s['name']} refused for now (too many failed attempts from this server); "
                          f"try again after {time.strftime('%H:%M', time.localtime(exc.until))}", 429)
    except httpx.ConnectError as exc:
        txt = str(exc)
        if "CERTIFICATE" in txt.upper() or "SSL" in txt.upper():
            raise RemoteError(f"HTTPS certificate of {s['url']} is not trusted (self-signed?). Use a trusted "
                              "certificate or turn off certificate checking for this server.", 502)
        raise RemoteError(f"Cannot connect to {s['url']}: check the address, port, firewall / VPN and that AppManager is running there.", 504)
    except httpx.TimeoutException:
        raise RemoteError(f"{s['url']} did not answer in time", 504)
    except httpx.HTTPError as exc:
        raise RemoteError(f"Connection to {s['url']} failed: {str(exc)[:200]}", 502)
    if 300 <= resp.status_code < 400:
        raise RemoteError(f"{s['url']} redirects to {resp.headers.get('location', '?')}; enter that address instead", 502)
    if resp.status_code == 401:
        raise RemoteError("The API Token was refused (wrong, deleted or expired). Create a new one on that server.", 424)  # không dùng 401: trình duyệt sẽ tưởng phiên đăng nhập của máy này hết hạn
    if resp.status_code == 403:
        raise RemoteError(f"Not allowed by the API Token on {s['name']}: {_detail(resp) or 'permission'}", 403)
    if resp.status_code == 404:
        raise RemoteError(f"{s['name']} does not know this request (AppManager too old?): {_detail(resp)}", 404)
    if resp.status_code >= 400:
        code = resp.status_code if resp.status_code in (400, 409, 429) else 502
        raise RemoteError(f"{s['name']}: {_detail(resp) or 'HTTP ' + str(resp.status_code)}", code)
    try:
        return resp.json()
    except Exception:
        raise RemoteError(f"{s['url']} did not answer like AppManager (is it the right address and port?)", 502)


async def probe(s: dict[str, Any]) -> dict[str, Any]:
    """Kết nối + Token + phiên bản + số app. Luôn trả dict (ok/error), lưu vào bộ nhớ trạng thái."""
    t0 = time.time()
    st: dict[str, Any] = {"ok": False, "checked": int(t0)}
    try:
        await call(s, "GET", "/api/jobs", timeout=10)            # cần Token hợp lệ (health thì không)
        h = await call(s, "GET", "/api/health", timeout=15)
        ver = str(h.get("version") or "")
        st.update(version=ver, apps=h.get("apps") or {}, updates=h.get("updates") or [],
                  last_checked=h.get("last_checked", ""), scope=h.get("token_scope", ""),
                  latency_ms=int((time.time() - t0) * 1000))
        if _version_tuple(ver) < MIN_VERSION:
            st["error"] = f"AppManager {ver or '?'} on that server is too old; update it to 0.17.0 or newer"
        else:
            st["ok"] = True
    except RemoteError as exc:
        st["error"] = exc.message
    if "id" in s:
        _STATUS[s["id"]] = st
    return st


async def probe_all() -> list[dict[str, Any]]:
    items = _load()
    await asyncio.gather(*(probe(s) for s in items))
    return [public(s) for s in items]


def trim_app(a: dict[str, Any], base: str) -> dict[str, Any]:
    out = {k: a.get(k) for k in APP_FIELDS}
    icon = out.get("icon") or ""
    if icon.startswith("/"):
        out["icon"] = base + icon   # biểu tượng nằm trên máy phụ
    return out
