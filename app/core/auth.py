import time
from collections import defaultdict
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, Response, WebSocket, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.database import (
    create_admin_user,
    get_setting,
    get_user_by_username,
    has_admin_user,
)

COOKIE_NAME = "amp_session"
SESSION_SHORT_AGE = 60 * 60 * 12        # 12 giờ
SESSION_LONG_AGE = 60 * 60 * 24 * 30    # 30 ngày (Ghi nhớ đăng nhập)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60               # Khóa IP 15 phút nếu sai 5 lần

ph = PasswordHasher()

# Bộ đếm chống Brute-force theo IP thật: {ip: [timestamps]}
_failed_attempts: dict[str, list[float]] = defaultdict(list)


def get_client_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_ip_locked(ip: str) -> int:
    now = time.time()
    recent = [ts for ts in _failed_attempts[ip] if now - ts < LOCKOUT_SECONDS]
    _failed_attempts[ip] = recent
    if len(recent) >= MAX_FAILED_ATTEMPTS:
        remaining = int(LOCKOUT_SECONDS - (now - recent[0]))
        return max(1, remaining)
    return 0


def record_failed_attempt(ip: str) -> None:
    _failed_attempts[ip].append(time.time())


def clear_failed_attempts(ip: str) -> None:
    _failed_attempts.pop(ip, None)


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
    token = _get_serializer().dumps({"u": username, "r": remember})
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


def verify_session_token(token: Optional[str]) -> Optional[str]:
    if not token or not has_admin_user():
        return None
    try:
        data = _get_serializer().loads(token, max_age=SESSION_LONG_AGE)
        username = data.get("u")
        if username and get_user_by_username(username):
            return username
    except (BadSignature, SignatureExpired):
        return None
    return None


def get_current_user_optional(request: Request) -> Optional[str]:
    return verify_session_token(request.cookies.get(COOKIE_NAME))


def require_user(request: Request) -> str:
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    return user


def verify_websocket_user(websocket: WebSocket) -> Optional[str]:
    return verify_session_token(websocket.cookies.get(COOKIE_NAME))


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
