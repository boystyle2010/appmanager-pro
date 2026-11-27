import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote, urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response, WebSocket, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core import api_tokens, users
from app.core.database import (
    add_login_failure,
    clear_login_failures,
    count_recent_failures,
    create_admin_user,
    get_setting,
    get_user_by_username,
    has_admin_user,
    update_user_fields,
)

COOKIE_NAME = "amp_session"
SESSION_SHORT_AGE = 60 * 60 * 12        # 12 giờ
SESSION_LONG_AGE = 60 * 60 * 24 * 30    # 30 ngày (Ghi nhớ đăng nhập)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60               # Khóa IP 15 phút nếu sai 5 lần

ph = PasswordHasher()

# Chỉ tin header IP (X-Forwarded-For / CF-Connecting-IP) khi request đến từ các proxy này.
# Mặc định CHỈ tin localhost. Nếu dùng reverse proxy / Cloudflare Tunnel, khai báo IP của proxy
# trong biến TRUSTED_PROXIES (vd: "172.17.0.1" hoặc "172.18.0.5,192.168.68.10").
# Không nên tin cả dải 172.16.0.0/12: mọi container khác cũng nằm trong dải đó và có thể giả IP.
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128"


def _trusted_networks() -> list:
    nets = []
    for part in (os.getenv("TRUSTED_PROXIES") or _DEFAULT_TRUSTED).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


_TRUSTED = _trusted_networks()


def _is_trusted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in _TRUSTED)


def get_client_ip(request: Request) -> str:
    """IP thật của người dùng. Header proxy chỉ được tin khi kết nối đến từ proxy tin cậy (chống giả IP)."""
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer):
        return peer
    # CF-Connecting-IP chỉ được tin khi bật rõ ràng (proxy khác có thể chuyển tiếp nguyên header do kẻ tấn công gửi)
    if os.getenv("TRUST_CF_CONNECTING_IP", "false").lower() == "true":
        cf_ip = _valid_ip((request.headers.get("cf-connecting-ip") or "").strip())
        if cf_ip:
            return cf_ip
    xff = request.headers.get("x-forwarded-for") or ""
    # Đi từ phải sang trái, bỏ qua các proxy tin cậy -> IP hợp lệ đầu tiên không tin cậy là client thật
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        ip = _valid_ip(hop)
        if not ip:
            break
        if not _is_trusted(ip):
            return ip
    return peer


def _valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def is_ip_locked(ip: str) -> int:
    count, first = count_recent_failures(ip, LOCKOUT_SECONDS)
    if count >= MAX_FAILED_ATTEMPTS:
        return max(1, int(LOCKOUT_SECONDS - (time.time() - first)))
    return 0


def record_failed_attempt(ip: str) -> None:
    add_login_failure(ip)


def clear_failed_attempts(ip: str) -> None:
    clear_login_failures(ip)


# ---------------- Xác thực 2 lớp (TOTP, RFC 6238) ----------------
TOTP_PERIOD = 30
TOTP_DIGITS = 6


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = TOTP_DIGITS) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret_b32: str, at: Optional[float] = None) -> str:
    return _hotp(secret_b32, int((at if at is not None else time.time()) // TOTP_PERIOD))


def verify_totp(secret_b32: str, code: str, last_step: int = 0, at: Optional[float] = None) -> int:
    """Trả về bước thời gian hợp lệ (>0) nếu mã đúng (cho lệch ±1 bước, chống dùng lại mã cũ), ngược lại 0."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != TOTP_DIGITS or not secret_b32:
        return 0
    step = int((at if at is not None else time.time()) // TOTP_PERIOD)
    for s in (step - 1, step, step + 1):
        if s > last_step and hmac.compare_digest(_hotp(secret_b32, s), code):
            return s
    return 0


def totp_uri(secret_b32: str, username: str) -> str:
    label = quote(f"AppManager Pro:{username}")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer=AppManager%20Pro&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"


def totp_qr_svg(uri: str) -> str:
    """QR dạng SVG (cần thư viện segno; nếu thiếu thì trả chuỗi rỗng, người dùng nhập khoá thủ công)."""
    try:
        import io

        import segno

        buf = io.BytesIO()
        segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, dark="#0f172a", light="#ffffff")
        return buf.getvalue().decode()
    except Exception:
        return ""


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().replace("-", "").encode()).hexdigest()


def new_backup_codes(n: int = 8) -> tuple[list[str], str]:
    """Tạo mã dự phòng dùng 1 lần. Trả về (mã hiển thị cho người dùng, JSON hash để lưu)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, json.dumps([_hash_code(c) for c in codes])


def use_backup_code(username: str, stored_json: str, code: str) -> bool:
    try:
        hashes = json.loads(stored_json or "[]")
    except Exception:
        hashes = []
    h = _hash_code(code)
    for i, item in enumerate(hashes):
        if hmac.compare_digest(item, h):
            hashes.pop(i)
            update_user_fields(username, backup_codes=json.dumps(hashes))
            return True
    return False


def check_second_factor(user, code: str) -> bool:
    """Kiểm tra mã 2FA (TOTP 6 số hoặc mã dự phòng). Tự lưu bước đã dùng để chặn dùng lại."""
    code = (code or "").strip()
    if not code:
        return False
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == TOTP_DIGITS and len(code.replace(" ", "")) == TOTP_DIGITS:
        step = verify_totp(user["totp_secret"], digits, int(user["totp_last_step"] or 0))
        if step:
            update_user_fields(user["username"], totp_last_step=step)
            return True
        return False
    return use_backup_code(user["username"], user["backup_codes"], code)


def _get_serializer() -> URLSafeTimedSerializer:
    secret = get_setting("session_secret")
    return URLSafeTimedSerializer(secret, salt="appmanager-pro-auth")


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def is_https_request(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.lower() == "https"


def set_session_cookie(
    response: Response, request: Request, username: str, remember: bool = False
) -> None:
    max_age = SESSION_LONG_AGE if remember else SESSION_SHORT_AGE
    u = get_user_by_username(username)
    ver = int((u["session_ver"] if u else 1) or 1)
    token = _get_serializer().dumps({"u": username, "r": remember, "v": ver})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=is_https_request(request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def session_user(token: Optional[str]):
    """Bản ghi người dùng của phiên (None nếu phiên sai / hết hạn / tài khoản bị khoá / phiên đã bị thu hồi)."""
    if not token or not has_admin_user():
        return None
    try:
        data = _get_serializer().loads(token, max_age=SESSION_LONG_AGE)
    except (BadSignature, SignatureExpired):
        return None
    username = data.get("u")
    u = get_user_by_username(username) if username else None
    if not u or u["username"] != username or u["disabled"]:
        return None
    if int(data.get("v") or 1) != int(u["session_ver"] or 1):  # đổi vai trò / mật khẩu / bị khoá -> phiên cũ hết hiệu lực
        return None
    return u


def verify_session_token(token: Optional[str]) -> Optional[str]:
    u = session_user(token)
    return u["username"] if u else None


def revoke_sessions(username: str) -> None:
    """Đăng xuất mọi thiết bị của MỘT người (không ảnh hưởng người khác)."""
    u = get_user_by_username(username)
    if u:
        update_user_fields(u["username"], session_ver=int(u["session_ver"] or 1) + 1)


def check_role(request_or_ws, role: str, method: str, path: str) -> None:
    if not users.role_allows(role, method, path):
        raise HTTPException(status_code=403, detail=users.denied_detail(role))


def get_current_user_optional(request: Request) -> Optional[str]:
    return verify_session_token(request.cookies.get(COOKIE_NAME))


def token_user(request: Request) -> Optional[str]:
    """Xác thực bằng API token (header Authorization: Bearer amp_…). None = request không có token."""
    token = api_tokens.bearer(request.headers)
    if not token:
        return None
    ip = get_client_ip(request)
    wait = is_ip_locked(ip)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many failed attempts from {ip}; try again in {wait // 60 + 1} min",
                            headers={"Retry-After": str(wait)})
    try:
        rec = api_tokens.verify(token, ip, request.method, request.url.path)
    except api_tokens.TokenError as exc:
        if exc.status == 401:
            record_failed_attempt(ip)
        raise HTTPException(status_code=exc.status, detail=exc.detail,
                            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None)
    request.state.api_token = rec
    return f"token:{rec['name']}"


def require_user(request: Request) -> str:
    """Người đăng nhập (cookie phiên) hoặc API token hợp lệ có đủ quyền cho request này.
    Người đăng nhập: vai trò (Quản trị / Cập nhật / Chỉ xem) phải cho phép request (users.role_allows)."""
    tu = token_user(request)
    if tu:
        return tu
    u = session_user(request.cookies.get(COOKIE_NAME))
    if not u:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    role = u["role"] or "admin"
    request.state.role = role
    check_role(request, role, request.method, request.url.path)
    return u["username"]


def _allowed_hosts(headers) -> set[str]:
    hosts = {
        (headers.get("host") or "").lower(),
        (headers.get("x-forwarded-host") or "").split(",")[0].strip().lower(),
    }
    # Tên miền bổ sung (vd khi proxy đổi Host): ALLOWED_ORIGINS="am.example.com,192.168.1.10:8098"
    for h in (os.getenv("ALLOWED_ORIGINS") or "").split(","):
        h = h.strip().lower()
        if h:
            hosts.add(urlparse(h).netloc or h if "://" in h else h)
    hosts.discard("")
    return hosts


def origin_allowed(headers) -> bool:
    """Request từ trình duyệt phải đến từ chính trang của app (chống CSRF / cross-site WebSocket)."""
    origin = headers.get("origin") or headers.get("referer") or ""
    if not origin or origin == "null":
        return not origin  # không có Origin = không phải trình duyệt; "null" = trang lạ (sandbox) -> chặn
    try:
        netloc = urlparse(origin).netloc.lower()
    except Exception:
        return False
    return bool(netloc) and netloc in _allowed_hosts(headers)


def verify_websocket_user(websocket: WebSocket) -> Optional[str]:
    if not origin_allowed(websocket.headers):
        return None
    u = session_user(websocket.cookies.get(COOKIE_NAME))
    if not u:
        return None
    if not users.role_allows(u["role"] or "admin", "GET", websocket.url.path):
        websocket.state.denied = True  # đã đăng nhập nhưng không đủ quyền -> đóng mã 4403 (không đẩy về trang đăng nhập)
        return None
    return u["username"]


def setup_first_admin(username: str, password: str) -> None:
    if has_admin_user():
        raise HTTPException(status_code=400, detail="Admin already configured")
    username = username.strip()
    if len(username) < 3 or len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Username must be at least 3 chars and password at least 8 chars",
        )
    create_admin_user(username, hash_password(password))


def validate_new_password(password: str) -> None:
    if len(password or "") < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
