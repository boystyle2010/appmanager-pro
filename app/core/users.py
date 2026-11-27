"""
Nhiều tài khoản + phân quyền (0.22).

Vai trò:
- admin    (Quản trị): mọi thứ — cài đặt, tài khoản, API Token, máy chủ, sửa / gỡ / triển khai app.
- operator (Cập nhật): xem mọi thứ (trừ dữ liệu nhạy cảm) + kiểm tra bản mới, cập nhật (kể cả đổi kênh / phiên bản),
             bật / tắt / khởi động lại app, khôi phục bản sao lưu, bỏ qua bản / tự cập nhật / quy tắc của từng app.
- viewer   (Chỉ xem): xem danh sách app, phiên bản, changelog, log, lịch sử.
Mọi vai trò đều tự đổi mật khẩu / bật 2FA của mình và đăng xuất được.

Quyền được kiểm tra ở máy chủ cho MỌI request (`role_allows`, gọi trong auth.require_user / _session_only và
WebSocket). Giao diện chỉ ẩn nút cho gọn — không dựa vào giao diện để chặn.
Đổi vai trò / khoá / đặt lại mật khẩu -> tăng `session_ver` -> phiên đăng nhập cũ của người đó hết hiệu lực ngay.
"""
from __future__ import annotations

import re
from typing import Any, Optional

ROLES = ("admin", "operator", "viewer")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,39}$")
MAX_USERS = 50

# Ai cũng được: tài khoản của chính mình
_SELF = (
    ("GET", re.compile(r"^/api/auth/(security|me)$")),
    ("POST", re.compile(r"^/api/auth/(logout|password|2fa/(setup|enable|disable|backup-codes))$")),
)
# GET chỉ cho Quản trị (có mật khẩu / biến môi trường / cấu hình nhạy cảm)
_ADMIN_GET = re.compile(
    r"^/api/(tokens|users|audit|sso|config|notify|setup/|system/api-status|system/registry-logins"
    r"|apps/[^/]+/(compose|compose-convert|run-command|uninstall-check)$)"
)
# POST của vai trò Cập nhật
_OPERATOR_POST = re.compile(
    r"^/api/("
    r"updates/check|update-all|update-all/excluded|backups/restore"
    r"|apps/[^/]+/(check|update|prefs|start|stop|restart)"
    r"|servers/[^/]+/(check|update-all|backups/restore|apps/[^/]+/(update|start|stop|restart))"
    r")$"
)
# WebSocket: xem log / tài nguyên = mọi vai trò; cập nhật = Cập nhật trở lên; còn lại (triển khai) = Quản trị
_WS_ALL = re.compile(r"^/ws/(logs/[^/]+|task-manager)$")
_WS_OPERATOR = re.compile(r"^/ws/(update/[^/]+|update-all)$")


def role_allows(role: str, method: str, path: str) -> bool:
    if role == "admin":
        return True
    if role not in ROLES:
        return False
    method = method.upper()
    if path.startswith("/ws/"):
        return bool(_WS_ALL.match(path)) or (role == "operator" and bool(_WS_OPERATOR.match(path)))
    if any(m == method and r.match(path) for m, r in _SELF):
        return True
    if method in ("GET", "HEAD"):
        return not _ADMIN_GET.match(path)
    if role == "operator" and method == "POST":
        return bool(_OPERATOR_POST.match(path))
    return False


def denied_detail(role: str) -> str:
    label = {"operator": "Update", "viewer": "View only"}.get(role, role)
    return f"Your account ({label}) is not allowed to do this. Ask an administrator."


def public(u: Any) -> dict[str, Any]:
    d = dict(u)
    return {
        "username": d["username"], "role": d.get("role") or "admin", "disabled": bool(d.get("disabled")),
        "totp_enabled": bool(d.get("totp_enabled")), "last_login": d.get("last_login") or "",
        "last_ip": d.get("last_ip") or "", "created_by": d.get("created_by") or "", "created_at": str(d.get("created_at") or ""),
        "auth_source": d.get("auth_source") or "local", "sso_linked": bool(d.get("oidc_sub")), "email": d.get("email") or "",
    }


def validate_username(name: str) -> str:
    name = (name or "").strip()
    if not USERNAME_RE.match(name) or name.lower().startswith("token:"):
        raise ValueError("User name: 3-40 characters, letters, numbers and . _ @ - (start with a letter or number)")
    return name


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError("Invalid role")
    return role


def active_admins(users: list[dict[str, Any]], exclude: Optional[str] = None) -> int:
    return sum(1 for u in users if (u.get("role") or "admin") == "admin" and not u.get("disabled") and u["username"] != exclude)
