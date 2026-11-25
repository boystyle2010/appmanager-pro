"""
Lớp kết nối chung cho mọi lời gọi ra ngoài (Docker Hub, GitHub, GHCR, registry khác).

- Bộ nhớ tạm (SQLite): nội dung bất biến (blob theo digest, release theo tag) lưu lâu; danh sách tag / release lưu
  vừa phải; API GitHub dùng ETag (trả 304 không tính vào giới hạn).
- Tôn trọng giới hạn: gặp 429 / hết lượt (GitHub 403 + X-RateLimit-Remaining: 0) -> TẠM DỪNG gọi tới đúng nguồn đó
  tới giờ được phép (Retry-After / X-RateLimit-Reset), nhớ qua cả khi khởi động lại; trong lúc đó trả lỗi RateLimited
  ngay, không gọi mạng.
- Đếm lượt gọi / lượt dùng bộ nhớ tạm theo nguồn; giới hạn số kết nối song song mỗi nguồn.
- Tài khoản registry (Docker Hub, GHCR, registry riêng): tự gắn vào yêu cầu lấy token registry và API Docker Hub.
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import email.utils
import hashlib
import json
import logging
import re
import threading
import time
from collections import deque
from typing import Any, Optional

import httpx

from app.core.database import get_connection, get_setting, set_setting

logger = logging.getLogger(__name__)

SOURCE_LABELS = {"dockerhub": "Docker Hub", "github": "GitHub", "ghcr": "GitHub Container Registry", "quay": "Quay.io"}
_CONCURRENCY = {"dockerhub": 4, "github": 4}
_DEFAULT_BLOCK = 15 * 60
_MAX_BODY = 1024 * 1024


class RateLimited(httpx.HTTPError):
    def __init__(self, source: str, until: float):
        self.source, self.until = source, until
        when = time.strftime("%H:%M", time.localtime(until))
        super().__init__(f"{SOURCE_LABELS.get(source, source)} rate limit reached — paused until {when}")


def source_of(host: str) -> str:
    host = (host or "").lower()
    if host in ("hub.docker.com", "registry-1.docker.io", "auth.docker.io", "index.docker.io", "registry.hub.docker.com"):
        return "dockerhub"
    if host in ("api.github.com", "github.com", "raw.githubusercontent.com", "codeload.github.com"):
        return "github"
    if host == "ghcr.io":
        return "ghcr"
    if host == "quay.io":
        return "quay"
    return host


# ---------------------------------------------------------------- trạng thái từng nguồn
_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}
_sems: dict[tuple[int, str], asyncio.Semaphore] = {}
_track: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("amp_net_track", default=None)


def _st(source: str) -> dict[str, Any]:
    with _lock:
        if source not in _state:
            _state[source] = {"requests": deque(maxlen=5000), "cache_hits": deque(maxlen=5000), "remaining": None,
                              "limit": None, "reset": None, "blocked_until": 0.0, "last_error": "", "last_429": 0.0}
            try:
                blocks = json.loads(get_setting("net_blocks", "{}") or "{}")
                _state[source]["blocked_until"] = float(blocks.get(source) or 0)
            except Exception:
                pass
        return _state[source]


def _persist_blocks() -> None:
    try:
        now = time.time()
        set_setting("net_blocks", json.dumps({k: v["blocked_until"] for k, v in _state.items() if v["blocked_until"] > now}))
    except Exception:
        pass


def blocked_until(source: str) -> float:
    b = _st(source)["blocked_until"]
    return b if b > time.time() else 0.0


def block(source: str, until: float, reason: str = "") -> None:
    s = _st(source)
    s["blocked_until"] = max(s["blocked_until"], until)
    s["last_429"] = time.time()
    s["last_error"] = reason[:200]
    _persist_blocks()
    logger.warning("Rate limit on %s, paused until %s (%s)", source, time.ctime(until), reason)


def clear_block(source: str) -> None:
    _st(source)["blocked_until"] = 0.0
    _persist_blocks()


def begin_track() -> contextvars.Token:
    """Theo dõi các lần bị giới hạn trong một tác vụ (vd kiểm tra một app)."""
    return _track.set([])


def end_track(token: contextvars.Token) -> list:
    hits = _track.get() or []
    _track.reset(token)
    return hits


def _note_limited(source: str, until: float) -> None:
    hits = _track.get()
    if hits is not None:
        hits.append((source, until))


def _parse_reset(resp: httpx.Response) -> Optional[float]:
    h = resp.headers
    ra = h.get("retry-after")
    if ra:
        if ra.strip().isdigit():
            return time.time() + int(ra.strip())
        try:
            return email.utils.parsedate_to_datetime(ra).timestamp()
        except Exception:
            pass
    for key in ("x-ratelimit-reset", "ratelimit-reset"):
        v = (h.get(key) or "").split(";")[0].strip()
        if v.isdigit():
            n = int(v)
            return float(n) if n > 10 ** 9 else time.time() + n  # epoch hoặc số giây
    return None


def _num(v: Optional[str]) -> Optional[int]:
    m = re.match(r"\s*(\d+)", v or "")
    return int(m.group(1)) if m else None


def _observe(source: str, resp: httpx.Response) -> None:
    s = _st(source)
    h = resp.headers
    rem = _num(h.get("x-ratelimit-remaining") or h.get("ratelimit-remaining"))
    lim = _num(h.get("x-ratelimit-limit") or h.get("ratelimit-limit"))
    if rem is not None:
        s["remaining"], s["limit"] = rem, lim
        s["reset"] = _parse_reset(resp)
    try:
        body_hint = resp.text[:500].lower() if resp.status_code == 403 else ""
    except Exception:
        body_hint = ""
    limited = resp.status_code == 429 or (resp.status_code == 403 and (rem == 0 or "rate limit" in body_hint))
    if limited:
        until = _parse_reset(resp) or (time.time() + _DEFAULT_BLOCK)
        until = min(until, time.time() + 24 * 3600)
        block(source, until, f"HTTP {resp.status_code}")
        _note_limited(source, until)


# ---------------------------------------------------------------- bộ nhớ tạm HTTP
def _ensure_table() -> None:
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS http_cache (
            key TEXT PRIMARY KEY, url TEXT, status INTEGER, headers TEXT, body BLOB, etag TEXT,
            expires REAL, stored REAL)""")
        conn.commit()
    finally:
        conn.close()


_table_ready = False


def _cache_policy(request: httpx.Request) -> tuple[int, bool]:
    """(số giây lưu, dùng ETag). 0 = không lưu."""
    if request.method != "GET":
        return 0, False
    url = str(request.url)
    host = request.url.host
    path = request.url.path
    if "/blobs/sha256:" in path:
        return 30 * 86400, False  # nội dung theo digest: không bao giờ đổi
    if "/manifests/" in path:
        return 0, False  # phát hiện bản mới: luôn hỏi registry (HEAD/GET manifest)
    if host == "api.github.com":
        if "/releases/tags/" in path:
            return 7 * 86400, True
        if "/compare/" in path or "/commits" in path:
            return 30 * 60, True
        return 30 * 60, True
    if host == "raw.githubusercontent.com":
        return 3600, False
    if host == "hub.docker.com" and "/tags" in path:
        return 3600, False
    if path.endswith("/tags/list"):
        return 3600, False
    if "/token" in path and ("scope=" in url or "service=" in url):
        return 240, False  # token registry ngắn hạn
    return 0, False


def _cache_key(request: httpx.Request) -> str:
    auth = request.headers.get("authorization") or ""
    raw = "|".join([request.method, str(request.url), request.headers.get("accept") or "",
                    hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else ""])
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    global _table_ready
    try:
        if not _table_ready:
            _ensure_table(); _table_ready = True
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM http_cache WHERE key = ?", (key,)).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _cache_put(key: str, url: str, resp: httpx.Response, ttl: int, body: bytes) -> None:
    global _table_ready
    if len(body) > _MAX_BODY:
        return
    try:
        if not _table_ready:
            _ensure_table(); _table_ready = True
        keep = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "etag", "docker-content-digest", "link")}
        conn = get_connection()
        try:
            now = time.time()
            conn.execute("INSERT OR REPLACE INTO http_cache (key, url, status, headers, body, etag, expires, stored) VALUES (?,?,?,?,?,?,?,?)",
                         (key, url[:500], resp.status_code, json.dumps(keep), body, resp.headers.get("etag") or "", now + ttl, now))
            if int(now) % 50 == 0:  # thỉnh thoảng dọn bản đã hết hạn lâu
                conn.execute("DELETE FROM http_cache WHERE expires < ?", (now - 7 * 86400,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug("cache put failed", exc_info=True)


def _cache_touch(key: str, ttl: int) -> None:
    try:
        conn = get_connection()
        try:
            conn.execute("UPDATE http_cache SET expires = ? WHERE key = ?", (time.time() + ttl, key))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _from_cache(row: dict[str, Any], request: httpx.Request) -> httpx.Response:
    headers = json.loads(row.get("headers") or "{}")
    headers["x-amp-cache"] = "hit"
    return httpx.Response(row["status"], headers=headers, content=row["body"] or b"", request=request)


def clear_cache() -> int:
    try:
        _ensure_table()
        conn = get_connection()
        try:
            n = conn.execute("DELETE FROM http_cache").rowcount
            conn.commit()
            return n
        finally:
            conn.close()
    except Exception:
        return 0


# ---------------------------------------------------------------- tài khoản registry
def registry_logins() -> list[dict[str, str]]:
    try:
        data = json.loads(get_setting("registry_logins", "[]") or "[]")
        return [d for d in data if isinstance(d, dict) and d.get("registry") and d.get("username") and d.get("token")]
    except Exception:
        return []


def _login_for_registry(registry: str) -> Optional[dict[str, str]]:
    registry = registry.lower()
    if registry in ("auth.docker.io", "registry-1.docker.io", "index.docker.io", "hub.docker.com", "docker.io"):
        registry = "docker.io"
    return next((d for d in registry_logins() if d["registry"].lower() == registry), None)


_hub_jwt: dict[str, Any] = {"token": "", "exp": 0.0, "user": ""}


async def _hub_jwt_token(client: "GuardedClient") -> str:
    login = _login_for_registry("docker.io")
    if not login:
        return ""
    if _hub_jwt["token"] and _hub_jwt["exp"] > time.time() and _hub_jwt["user"] == login["username"]:
        return _hub_jwt["token"]
    try:
        r = await httpx.AsyncClient.send(client, client.build_request(
            "POST", "https://hub.docker.com/v2/users/login",
            json={"username": login["username"], "password": login["token"]}))
        if r.status_code == 200 and r.json().get("token"):
            _hub_jwt.update(token=r.json()["token"], exp=time.time() + 50 * 60, user=login["username"])
            return _hub_jwt["token"]
        _st("dockerhub")["last_error"] = f"Docker Hub login failed (HTTP {r.status_code})"
    except Exception as exc:
        _st("dockerhub")["last_error"] = f"Docker Hub login failed ({exc})"
    return ""


# ---------------------------------------------------------------- client
class GuardedClient(httpx.AsyncClient):
    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        source = source_of(request.url.host)
        s = _st(source)
        until = blocked_until(source)
        if until:
            _note_limited(source, until)
            raise RateLimited(source, until)

        # Thông tin đăng nhập: token registry (Basic) và API Docker Hub (JWT)
        if "authorization" not in request.headers:
            if "/token" in request.url.path and ("scope" in str(request.url) or "service" in str(request.url)):
                login = _login_for_registry(request.url.host)
                if login:
                    raw = base64.b64encode(f"{login['username']}:{login['token']}".encode()).decode()
                    request.headers["Authorization"] = f"Basic {raw}"
            elif request.url.host == "hub.docker.com" and not request.url.path.startswith("/v2/users/login"):
                jwt = await _hub_jwt_token(self)
                if jwt:
                    request.headers["Authorization"] = f"Bearer {jwt}"

        ttl, use_etag = _cache_policy(request)
        key = _cache_key(request) if ttl else ""
        row = await asyncio.to_thread(_cache_get, key) if ttl else None
        if row and row["expires"] > time.time():
            s["cache_hits"].append(time.time())
            return _from_cache(row, request)
        if row and use_etag and row.get("etag"):
            request.headers["If-None-Match"] = row["etag"]

        sem_key = (id(asyncio.get_running_loop()), source)
        sem = _sems.setdefault(sem_key, asyncio.Semaphore(_CONCURRENCY.get(source, 6)))
        async with sem:
            s["requests"].append(time.time())
            resp = await super().send(request, **kwargs)
        _observe(source, resp)
        if resp.status_code in (429,) or (resp.status_code == 403 and blocked_until(source)):
            await resp.aread()
            raise RateLimited(source, blocked_until(source) or time.time() + _DEFAULT_BLOCK)
        if resp.status_code == 304 and row:
            await resp.aread()
            await asyncio.to_thread(_cache_touch, key, ttl)
            s["cache_hits"].append(time.time())
            return _from_cache(row, request)
        if ttl and resp.status_code == 200:
            body = await resp.aread()
            await asyncio.to_thread(_cache_put, key, str(request.url), resp, ttl, body)
        return resp


def client(**kwargs: Any) -> GuardedClient:
    kwargs.setdefault("timeout", httpx.Timeout(12.0, connect=6.0))
    return GuardedClient(**kwargs)


# ---------------------------------------------------------------- tình trạng (cho Cài đặt)
def status() -> list[dict[str, Any]]:
    now = time.time()
    out = []
    names = set(_state) | {"dockerhub", "github"}
    for src in sorted(names, key=lambda x: (x not in ("dockerhub", "github", "ghcr"), x)):
        s = _st(src)
        req = sum(1 for t in s["requests"] if t > now - 3600)
        hits = sum(1 for t in s["cache_hits"] if t > now - 3600)
        login = _login_for_registry("docker.io" if src == "dockerhub" else ("ghcr.io" if src == "ghcr" else src))
        out.append({
            "source": src, "label": SOURCE_LABELS.get(src, src), "requests_1h": req, "cache_hits_1h": hits,
            "blocked_until": int(blocked_until(src)) or 0, "remaining": s["remaining"], "limit": s["limit"],
            "reset": int(s["reset"]) if s["reset"] else 0, "last_error": s["last_error"],
            "authenticated": bool(get_setting("github_token", "").strip()) if src == "github" else bool(login),
        })
    return out


# ---------------------------------------------------------------- đăng nhập registry cho docker CLI (pull image riêng tư)
_DOCKER_HUB_AUTH_KEY = "https://index.docker.io/v1/"


def docker_config_dir():
    from app.core.database import DATA_DIR

    return DATA_DIR / "docker-config"


def apply_docker_logins() -> None:
    """
    Ghi thông tin đăng nhập vào <data>/docker-config/config.json (gộp với ~/.docker/config.json nếu người dùng đã mount
    sẵn của host) và đặt DOCKER_CONFIG để mọi lệnh docker pull / compose pull của AppManager dùng được.
    """
    import os
    from pathlib import Path

    logins = registry_logins()
    cfg_dir = docker_config_dir()
    host_cfg = Path(os.path.expanduser("~/.docker/config.json"))
    if not logins:
        if (cfg_dir / "config.json").exists():
            (cfg_dir / "config.json").unlink()
        os.environ.pop("DOCKER_CONFIG", None)
        return
    data: dict[str, Any] = {}
    try:
        if host_cfg.is_file():
            data = json.loads(host_cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    auths = data.setdefault("auths", {})
    for lg in logins:
        key = _DOCKER_HUB_AUTH_KEY if lg["registry"].lower() in ("docker.io", "index.docker.io", "registry-1.docker.io") else lg["registry"]
        auths[key] = {"auth": base64.b64encode(f"{lg['username']}:{lg['token']}".encode()).decode()}
    cfg_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg_dir / "config.json.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(cfg_dir / "config.json")
    os.environ["DOCKER_CONFIG"] = str(cfg_dir)


async def test_login(registry: str, username: str, token: str) -> tuple[bool, str]:
    """Kiểm tra tài khoản: xin token pull của registry bằng tài khoản này (không tải gì)."""
    reg = registry.lower().strip()
    auth = httpx.BasicAuth(username, token)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        try:
            if reg in ("docker.io", "index.docker.io", "registry-1.docker.io"):
                r = await c.get("https://auth.docker.io/token",
                                params={"service": "registry.docker.io", "scope": "repository:library/alpine:pull"}, auth=auth)
            else:
                # localhost / 127.x: Docker cho phép registry HTTP thường
                scheme = "http" if reg.split(":")[0] in ("localhost", "127.0.0.1") else "https"
                base = f"{scheme}://{reg}/v2/"
                ping = await c.get(base)
                if ping.status_code == 200:
                    return True, "Registry does not require a login"
                www = ping.headers.get("www-authenticate", "")
                params: dict[str, str] = {}
                for m in re.finditer(r'(\w+)="([^"]*)"', www):
                    params[m.group(1)] = m.group(2)
                if www.lower().startswith("basic") or not params.get("realm"):
                    r = await c.get(base, auth=auth)
                else:
                    r = await c.get(params["realm"], params={"service": params.get("service", reg)}, auth=auth)
        except Exception as exc:
            return False, f"Cannot reach {reg}: {str(exc)[:150]}"
    if r.status_code == 200:
        return True, "Login OK"
    if r.status_code in (401, 403):
        return False, "Wrong username or token"
    return False, f"HTTP {r.status_code}"


def save_login(registry: str, username: str, token: str) -> None:
    reg = registry.lower().strip()
    items = [d for d in registry_logins() if d["registry"].lower() != reg]
    items.append({"registry": reg, "username": username.strip(), "token": token.strip()})
    set_setting("registry_logins", json.dumps(items))
    _hub_jwt.update(token="", exp=0.0)
    apply_docker_logins()


def delete_login(registry: str) -> None:
    reg = registry.lower().strip()
    set_setting("registry_logins", json.dumps([d for d in registry_logins() if d["registry"].lower() != reg]))
    _hub_jwt.update(token="", exp=0.0)
    apply_docker_logins()
