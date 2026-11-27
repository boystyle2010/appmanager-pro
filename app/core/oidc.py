"""
Đăng nhập một lần (SSO) qua OpenID Connect (0.23) — Authentik, Authelia, Keycloak, Google, Pocket ID, Zitadel…

Luồng Authorization Code + PKCE (S256), state + nonce (cookie ký, hết hạn sau 10 phút):
  /api/auth/oidc/login -> nhà cung cấp -> /api/auth/oidc/callback -> đổi code lấy token (kèm client secret)
  -> kiểm tra id_token (iss, aud, azp, exp, iat, nonce) -> lấy thông tin người dùng (claims + userinfo)
  -> tìm / tạo tài khoản, vai trò theo nhóm -> phiên đăng nhập như đăng nhập mật khẩu.

Chữ ký id_token: RS256 / RS384 / RS512 được kiểm tra bằng khoá công khai (JWKS) — RSA thuần Python (pow), không cần
thư viện `cryptography` (không có sẵn cho armv7). Thuật toán khác (ES256, EdDSA…): theo OpenID Connect Core 3.1.3.7,
id_token nhận TRỰC TIẾP từ token endpoint qua HTTPS (máy chủ xác thực bằng chứng chỉ TLS) thì không bắt buộc kiểm chữ
ký -> chỉ chấp nhận khi token endpoint là HTTPS; HTTP + thuật toán khác RS* bị từ chối. "none" luôn bị từ chối.

Tài khoản SSO: users.auth_source = 'oidc', oidc_sub = "<issuer>|<sub>" (gắn cố định, không theo tên). Không gắn vào
tài khoản mật khẩu có sẵn trùng tên (tránh chiếm quyền) trừ khi Quản trị bật "Gắn tài khoản có sẵn cùng tên".
Mật khẩu: tài khoản SSO không có mật khẩu dùng được; 2FA của AppManager bỏ qua (nhà cung cấp lo MFA).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import httpx

from app.core import net
from app.core.database import get_setting, set_setting

SETTING = "oidc_config"
ROLES = ("admin", "operator", "viewer")
DEFAULT = {
    "enabled": False, "label": "SSO", "issuer": "", "client_id": "", "client_secret": "",
    "scopes": "openid profile email groups", "username_claim": "preferred_username", "groups_claim": "groups",
    "admin_groups": "", "operator_groups": "", "viewer_groups": "", "default_role": "none",
    "auto_create": True, "link_existing": False, "verify_tls": True, "public_url": "",
}
_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
STATE_MAX_AGE = 600
CLOCK_SKEW = 120


class OIDCError(Exception):
    """Lỗi có lời giải thích dễ hiểu (hiện trên trang đăng nhập)."""


# ---------------------------------------------------------------- cấu hình
def config() -> dict[str, Any]:
    try:
        data = json.loads(get_setting(SETTING, "{}") or "{}")
    except Exception:
        data = {}
    return {**DEFAULT, **(data if isinstance(data, dict) else {})}


PROVIDERS = ("google", "authentik", "keycloak", "authelia", "gitlab", "okta", "auth0", "cloudflare", "nextcloud")


def provider_kind(c: Optional[dict[str, Any]] = None) -> str:
    """Nhận ra nhà cung cấp (để trang đăng nhập hiện đúng biểu tượng) từ tên hiển thị + địa chỉ issuer."""
    c = c or config()
    text = f"{c.get('label') or ''} {urlparse(c.get('issuer') or '').hostname or ''} {c.get('issuer') or ''}".lower()
    if "accounts.google.com" in text or "google" in text:
        return "google"
    if "cloudflareaccess.com" in text:
        return "cloudflare"
    for p in PROVIDERS:
        if p in text:
            return p
    if "/realms/" in text:
        return "keycloak"
    if "/application/o/" in text:
        return "authentik"
    return "oidc"


def public_config() -> dict[str, Any]:
    c = config()
    out = {k: v for k, v in c.items() if k != "client_secret"}
    out["has_secret"] = bool(c.get("client_secret"))
    return out


def _groups(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,\n]+", str(raw or ""))
    return [g.strip() for g in items if str(g).strip()][:50]


def normalize_issuer(raw: str) -> str:
    u = (raw or "").strip().rstrip("/")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or p.query or p.fragment or p.username:
        raise ValueError("Issuer must be the provider address, e.g. https://auth.example.com/application/o/appmanager")
    if u.endswith("/.well-known/openid-configuration"):
        u = u[: -len("/.well-known/openid-configuration")]
    return u


def save(data: dict[str, Any]) -> dict[str, Any]:
    cur = config()
    new = dict(cur)
    for k in ("label", "client_id", "scopes", "username_claim", "groups_claim", "default_role", "public_url"):
        if k in data and data[k] is not None:
            new[k] = str(data[k]).strip()
    for k in ("enabled", "auto_create", "link_existing", "verify_tls"):
        if k in data and data[k] is not None:
            new[k] = bool(data[k])
    for k in ("admin_groups", "operator_groups", "viewer_groups"):
        if k in data and data[k] is not None:
            new[k] = ", ".join(_groups(data[k]))
    if data.get("client_secret"):
        new["client_secret"] = str(data["client_secret"]).strip()
    if "issuer" in data and data["issuer"] is not None:
        new["issuer"] = normalize_issuer(data["issuer"]) if str(data["issuer"]).strip() else ""
    new["label"] = (new["label"] or "SSO")[:40]
    if new["default_role"] not in ("none",) + ROLES:
        raise ValueError("Invalid default role")
    if "openid" not in new["scopes"].split():
        new["scopes"] = ("openid " + new["scopes"]).strip()
    if new["public_url"]:
        p = urlparse(new["public_url"].rstrip("/"))
        if p.scheme not in ("http", "https") or not p.hostname or p.query or p.fragment:
            raise ValueError("AppManager address must look like https://appmanager.example.com")
        new["public_url"] = new["public_url"].rstrip("/")
    if new["enabled"] and not (new["issuer"] and new["client_id"] and new["client_secret"]):
        raise ValueError("Enter the issuer, Client ID and Client Secret before turning SSO on")
    set_setting(SETTING, json.dumps(new))
    _DISCOVERY_CACHE.clear(); _JWKS_CACHE.clear()
    return new


def redirect_uri(base_url: str, cfg: Optional[dict[str, Any]] = None) -> str:
    cfg = cfg or config()
    return (cfg.get("public_url") or base_url.rstrip("/")) + "/api/auth/oidc/callback"


# ---------------------------------------------------------------- mạng
def _client(cfg: dict[str, Any]) -> httpx.AsyncClient:
    return net.client(verify=bool(cfg.get("verify_tls", True)), follow_redirects=False, timeout=httpx.Timeout(15.0, connect=6.0))


async def _get_json(cfg: dict[str, Any], url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    try:
        async with _client(cfg) as c:
            r = await c.get(url, headers={"Accept": "application/json", **(headers or {})})
    except httpx.ConnectError as exc:
        if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper():
            raise OIDCError(f"The HTTPS certificate of {urlparse(url).netloc} is not trusted (self-signed?). Use a trusted certificate or turn off certificate checking.")
        raise OIDCError(f"Cannot connect to {urlparse(url).netloc}: check the address and that AppManager can reach it.")
    except httpx.HTTPError as exc:
        raise OIDCError(f"Connection to {urlparse(url).netloc} failed: {str(exc)[:200]}")
    if r.status_code != 200:
        raise OIDCError(f"{url} answered HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception:
        raise OIDCError(f"{url} did not return JSON")
    if not isinstance(data, dict):
        raise OIDCError(f"{url} did not return a JSON object")
    return data


async def discover(cfg: Optional[dict[str, Any]] = None, fresh: bool = False) -> dict[str, Any]:
    cfg = cfg or config()
    iss = cfg.get("issuer") or ""
    if not iss:
        raise OIDCError("SSO is not set up (no issuer)")
    hit = _DISCOVERY_CACHE.get(iss)
    if hit and not fresh and hit[0] > time.time():
        return hit[1]
    d = await _get_json(cfg, iss + "/.well-known/openid-configuration")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not d.get(k):
            raise OIDCError(f"The provider's discovery document has no {k}")
    if (d.get("issuer") or "").rstrip("/") != iss.rstrip("/"):
        raise OIDCError(f"Issuer mismatch: the provider says {d.get('issuer')!r}, settings say {iss!r}. Copy the exact issuer URL from the provider.")
    _DISCOVERY_CACHE[iss] = (time.time() + 3600, d)
    return d


def effective_scopes(cfg: dict[str, Any], d: dict[str, Any]) -> tuple[str, list[str]]:
    """Scope gửi đi = scope trong cài đặt mà nhà cung cấp hỗ trợ (vd Keycloak không có scope 'groups' -> bỏ, nhóm đến qua
    mapper). Nhà cung cấp không công bố scopes_supported -> gửi nguyên. Trả (chuỗi scope, các scope đã bỏ)."""
    want = [x for x in (cfg.get("scopes") or "openid").split() if x]
    sup = set(d.get("scopes_supported") or [])
    if not sup:
        return " ".join(want), []
    keep = [x for x in want if x == "openid" or x in sup]
    return " ".join(keep), [x for x in want if x not in keep]


async def test(cfg: dict[str, Any]) -> dict[str, Any]:
    d = await discover(cfg, fresh=True)
    jwks = await _get_json(cfg, d["jwks_uri"])
    return {"ok": True, "issuer": d.get("issuer"), "authorization_endpoint": d.get("authorization_endpoint"),
            "token_endpoint": d.get("token_endpoint"), "userinfo_endpoint": d.get("userinfo_endpoint", ""),
            "keys": len(jwks.get("keys") or []), "algs": d.get("id_token_signing_alg_values_supported") or [],
            "scopes_supported": d.get("scopes_supported") or [], "scopes_dropped": effective_scopes(cfg, d)[1],
            "pkce": "S256" in (d.get("code_challenge_methods_supported") or ["S256"])}


# ---------------------------------------------------------------- state (cookie ký bằng session_secret)
def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: dict[str, Any]) -> str:
    key = (get_setting("session_secret") or "").encode()
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _unsign(token: str) -> Optional[dict[str, Any]]:
    try:
        body, sig = token.split(".", 1)
        key = (get_setting("session_secret") or "").encode()
        if not hmac.compare_digest(sig, _b64u(hmac.new(key, body.encode(), hashlib.sha256).digest())):
            return None
        data = json.loads(_b64u_dec(body))
        if time.time() - float(data.get("t", 0)) > STATE_MAX_AGE:
            return None
        return data
    except Exception:
        return None


async def start(base_url: str, remember: bool = True) -> tuple[str, str]:
    """(URL chuyển tới nhà cung cấp, giá trị cookie state)."""
    cfg = config()
    if not cfg["enabled"]:
        raise OIDCError("SSO is turned off")
    d = await discover(cfg)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64u(hashlib.sha256(verifier.encode()).digest())
    q = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri(base_url, cfg),
         "scope": effective_scopes(cfg, d)[0], "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    url = d["authorization_endpoint"] + ("&" if "?" in d["authorization_endpoint"] else "?") + urlencode(q)
    cookie = _sign({"s": state, "n": nonce, "v": verifier, "t": int(time.time()), "r": bool(remember), "b": base_url})
    return url, cookie


# ---------------------------------------------------------------- RSA (RS256/384/512) thuần Python
_DIGEST_INFO = {  # tiền tố DER DigestInfo của EMSA-PKCS1-v1_5 (RFC 8017)
    "RS256": ("sha256", bytes.fromhex("3031300d060960864801650304020105000420")),
    "RS384": ("sha384", bytes.fromhex("3041300d060960864801650304020205000430")),
    "RS512": ("sha512", bytes.fromhex("3051300d060960864801650304020305000440")),
}


def rsa_verify(alg: str, n: int, e: int, message: bytes, signature: bytes) -> bool:
    if alg not in _DIGEST_INFO or n.bit_length() < 2048 or e < 3:
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    m = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    hname, prefix = _DIGEST_INFO[alg]
    t = prefix + hashlib.new(hname, message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(m, expected)


async def _check_signature(cfg: dict[str, Any], d: dict[str, Any], id_token: str, token_endpoint_https: bool) -> dict[str, Any]:
    try:
        h64, p64, s64 = id_token.split(".")
        header = json.loads(_b64u_dec(h64)); payload = json.loads(_b64u_dec(p64)); sig = _b64u_dec(s64)
    except Exception:
        raise OIDCError("The provider returned an invalid id_token")
    alg = header.get("alg") or ""
    if alg == "none" or not alg:
        raise OIDCError("Unsigned id_token refused")
    if alg in _DIGEST_INFO:
        uri = d["jwks_uri"]
        for attempt in (0, 1):  # khoá mới (xoay khoá) -> tải lại JWKS một lần
            hit = _JWKS_CACHE.get(uri)
            if not hit or hit[0] < time.time() or attempt:
                jwks = await _get_json(cfg, uri)
                _JWKS_CACHE[uri] = (time.time() + 3600, jwks)
            else:
                jwks = hit[1]
            keys = [k for k in jwks.get("keys") or [] if k.get("kty") == "RSA" and (not header.get("kid") or k.get("kid") == header.get("kid"))]
            for k in keys:
                try:
                    n = int.from_bytes(_b64u_dec(k["n"]), "big"); e = int.from_bytes(_b64u_dec(k["e"]), "big")
                except Exception:
                    continue
                if rsa_verify(alg, n, e, f"{h64}.{p64}".encode(), sig):
                    return payload
        raise OIDCError("id_token signature does not match the provider's keys")
    if token_endpoint_https:
        return payload  # OIDC Core 3.1.3.7: nhận trực tiếp từ token endpoint qua TLS
    raise OIDCError(f"id_token is signed with {alg}, which AppManager can only accept over HTTPS. Use HTTPS for the provider or switch it to RS256.")


def _check_claims(cfg: dict[str, Any], d: dict[str, Any], claims: dict[str, Any], nonce: str) -> None:
    now = time.time()
    if (claims.get("iss") or "").rstrip("/") != (d.get("issuer") or "").rstrip("/"):
        raise OIDCError("id_token issuer does not match")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if cfg["client_id"] not in auds:
        raise OIDCError("id_token was not issued for this Client ID")
    if len(auds) > 1 and claims.get("azp") not in (None, cfg["client_id"]):
        raise OIDCError("id_token authorized party (azp) does not match")
    if not claims.get("exp") or float(claims["exp"]) < now - CLOCK_SKEW:
        raise OIDCError("id_token has expired — check the clock of AppManager and the provider")
    if claims.get("iat") and float(claims["iat"]) > now + CLOCK_SKEW:
        raise OIDCError("id_token is from the future — check the clock of AppManager and the provider")
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise OIDCError("id_token nonce does not match (sign-in started in another tab?) — try again")
    if not claims.get("sub"):
        raise OIDCError("id_token has no subject (sub)")


async def finish(code: str, state: str, cookie: str) -> dict[str, Any]:
    """Đổi code -> thông tin người dùng đã kiểm tra: {sub_key, username, email, groups, role, remember}."""
    cfg = config()
    if not cfg["enabled"]:
        raise OIDCError("SSO is turned off")
    st = _unsign(cookie or "")
    if not st or not state or not hmac.compare_digest(str(st.get("s")), state):
        raise OIDCError("Sign-in expired or was started elsewhere — try again")
    d = await discover(cfg)
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(st.get("b") or "", cfg),
            "code_verifier": st["v"], "client_id": cfg["client_id"], "client_secret": cfg["client_secret"]}
    methods = d.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    headers = {"Accept": "application/json"}
    if "client_secret_post" not in methods:  # mặc định của OIDC: Basic
        form.pop("client_secret")
        raw = f"{_urlenc(cfg['client_id'])}:{_urlenc(cfg['client_secret'])}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    try:
        async with _client(cfg) as c:
            r = await c.post(d["token_endpoint"], data=form, headers=headers)
    except httpx.HTTPError as exc:
        raise OIDCError(f"Cannot reach the provider's token endpoint: {str(exc)[:200]}")
    try:
        tok = r.json()
    except Exception:
        tok = {}
    if r.status_code != 200 or not tok.get("id_token"):
        desc = tok.get("error_description") or tok.get("error") or f"HTTP {r.status_code}"
        raise OIDCError(f"The provider refused the sign-in: {desc} (check the Client ID / Secret and the Redirect URI)")
    claims = await _check_signature(cfg, d, tok["id_token"], d["token_endpoint"].startswith("https://"))
    _check_claims(cfg, d, claims, st["n"])
    info = dict(claims)
    if d.get("userinfo_endpoint") and tok.get("access_token"):
        try:
            ui = await _get_json(cfg, d["userinfo_endpoint"], {"Authorization": f"Bearer {tok['access_token']}"})
            if ui.get("sub") == claims["sub"]:  # userinfo phải đúng người
                info = {**ui, **{k: v for k, v in claims.items() if k in ("iss", "aud", "sub", "exp", "iat", "nonce")}}
        except OIDCError:
            pass
    username = str(info.get(cfg["username_claim"]) or info.get("preferred_username") or info.get("email") or "").strip()
    groups_raw = info.get(cfg["groups_claim"]) or []
    groups = [str(g) for g in (groups_raw if isinstance(groups_raw, list) else [groups_raw])]
    return {"sub_key": f"{claims['iss'].rstrip('/')}|{claims['sub']}", "username": username, "email": str(info.get("email") or ""),
            "groups": groups, "role": role_for(groups, cfg), "remember": bool(st.get("r", True))}


def _urlenc(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def role_for(groups: list[str], cfg: Optional[dict[str, Any]] = None) -> str:
    """Vai trò cao nhất mà nhóm của người dùng khớp; không khớp -> vai trò mặc định ('none' = không cho đăng nhập).
    So khớp không phân biệt hoa thường, nhận cả đường dẫn nhóm Keycloak (/Admins)."""
    cfg = cfg or config()
    have = {g.strip().strip("/").lower() for g in groups}
    for role in ROLES:
        want = {g.strip().strip("/").lower() for g in _groups(cfg.get(f"{role}_groups"))}
        if want & have:
            return role
    return cfg.get("default_role") or "none"


SAFE_NAME = re.compile(r"[^A-Za-z0-9._@-]+")


def safe_username(raw: str) -> str:
    """Tên đăng nhập hợp lệ cho AppManager từ claim (bỏ ký tự lạ, cắt 40 ký tự)."""
    name = SAFE_NAME.sub("-", raw or "").strip("-._@")[:40]
    if len(name) < 3:
        name = (name + "-sso")[:40]
    if not name[0].isalnum():
        name = "u" + name[:39]
    return name
