"""
Sao lưu / khôi phục CẤU HÌNH AppManager (0.24) ra 1 file mã hoá bằng mật khẩu (`.ampbak`).

Khác với sao lưu app (app_backup.py: file cài đặt của từng app trước khi cập nhật), đây là cấu hình của chính AppManager:
tài khoản + Vai trò (kèm mã băm mật khẩu, 2FA), SSO, API Token, kênh thông báo, máy chủ khác, tài khoản registry, quy
tắc cập nhật từng app và cài đặt chung. Dùng để chuyển sang máy mới / cài lại / quay về cấu hình cũ.

Mã hoá: khoá 256-bit từ mật khẩu bằng scrypt (N=2^15, r=8, p=1, salt ngẫu nhiên 16 byte), AES-256-GCM (aes.py thuần
Python, nonce 12 byte), phần đầu file (định dạng, phiên bản, ngày, danh sách phần) là AAD -> sửa phần đầu cũng bị phát
hiện. Nội dung nén zlib trước khi mã hoá. Sai mật khẩu / file hỏng -> không giải mã được (GCM).

Không đưa vào file: khoá phiên (session_secret), bộ đệm, trạng thái tạm (khoá IP, tin để dành, máy đang mất kết nối…),
lịch sử cập nhật, nhật ký hoạt động, dữ liệu app.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import time
import zlib
from pathlib import Path
from typing import Any, Optional

from app.core import aes
from app.core.database import DATA_DIR, get_connection

FORMAT = "appmanager-config"
VERSION = 1
MAX_FILE = 20 * 1024 * 1024
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
SAFETY_DIR = DATA_DIR / "config-backups"
SAFETY_KEEP = 5

# Phần cấu hình -> khoá settings thuộc phần đó (accounts / app_rules là bảng riêng)
SETTING_SECTIONS: dict[str, tuple[str, ...]] = {
    "settings": ("check_interval_hours", "auto_update_enabled", "auto_update_time", "prune_old_images", "github_token",
                 "auto_rollback", "health_wait_seconds", "backup_before_update", "backup_max_mb", "backup_file_max_mb",
                 "backup_keep", "auto_prune_enabled", "auto_prune_freq", "auto_prune_time", "auto_prune_weekday",
                 "auto_prune_images", "auto_prune_cache", "update_all_excluded"),
    "notify": ("notify_channels", "notify_lang", "notify_quiet_enabled", "notify_quiet_start", "notify_quiet_end",
               "notify_disk_pct", "notify_known_events", "webpush_vapid", "webpush_subs"),
    "sso": ("oidc_config",),
    "tokens": ("api_tokens",),
    "servers": ("remote_servers",),
    "registry": ("registry_logins",),
}
SECTIONS = ("accounts", "sso", "tokens", "notify", "servers", "registry", "app_rules", "settings")
_USER_FIELDS = ("username", "password_hash", "totp_secret", "totp_enabled", "totp_last_step", "backup_codes", "totp_pending",
                "role", "disabled", "session_ver", "last_login", "last_ip", "created_by", "created_at", "auth_source", "oidc_sub", "email")


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------- thu thập
def _table(conn, sql: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql).fetchall()]


def collect(sections: Optional[list[str]] = None) -> dict[str, Any]:
    want = [s for s in (sections or SECTIONS) if s in SECTIONS]
    out: dict[str, Any] = {}
    conn = get_connection()
    try:
        for sec in want:
            if sec == "accounts":
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
                fields = [f for f in _USER_FIELDS if f in cols]
                out[sec] = _table(conn, f"SELECT {', '.join(fields)} FROM users ORDER BY id")
            elif sec == "app_rules":
                out[sec] = _table(conn, "SELECT * FROM app_prefs ORDER BY container_name")
            else:
                vals = {}
                for k in SETTING_SECTIONS[sec]:
                    row = conn.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone()
                    if row is not None:
                        vals[k] = row["value"]
                out[sec] = vals
    finally:
        conn.close()
    return out


def _jl(raw: Any) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def summary(data: dict[str, Any]) -> dict[str, Any]:
    """Tóm tắt từng phần để người dùng xem trước (không có bí mật)."""
    s: dict[str, Any] = {}
    if "accounts" in data:
        s["accounts"] = {"count": len(data["accounts"]),
                         "items": [{"username": u.get("username"), "role": u.get("role") or "admin", "disabled": bool(u.get("disabled")),
                                    "sso": (u.get("auth_source") or "local") == "oidc" or bool(u.get("oidc_sub"))} for u in data["accounts"]],
                         "admins": sum(1 for u in data["accounts"] if (u.get("role") or "admin") == "admin" and not u.get("disabled"))}
    if "sso" in data:
        try:
            c = json.loads(data["sso"].get("oidc_config") or "{}")
        except Exception:
            c = {}
        s["sso"] = {"count": 1 if c.get("issuer") else 0, "enabled": bool(c.get("enabled")), "label": c.get("label") or "", "issuer": c.get("issuer") or ""}
    if "tokens" in data:
        t = _jl(data["tokens"].get("api_tokens"))
        s["tokens"] = {"count": len(t), "items": [f"{x.get('name')} ({x.get('scope')})" for x in t]}
    if "notify" in data:
        ch = _jl(data["notify"].get("notify_channels"))
        s["notify"] = {"count": len(ch), "items": [f"{x.get('name') or x.get('type')} ({x.get('type')})" for x in ch]}
    if "servers" in data:
        sv = _jl(data["servers"].get("remote_servers"))
        s["servers"] = {"count": len(sv), "items": [f"{x.get('name')} — {x.get('url')}" for x in sv]}
    if "registry" in data:
        rg = _jl(data["registry"].get("registry_logins"))
        s["registry"] = {"count": len(rg), "items": [f"{x.get('registry')} ({x.get('username')})" for x in rg]}
    if "app_rules" in data:
        rules = data["app_rules"]
        s["app_rules"] = {"count": len(rules), "items": [r.get("container_name") for r in rules][:50]}
    if "settings" in data:
        s["settings"] = {"count": len(data["settings"]), "items": sorted(data["settings"].keys())}
    return s


# ---------------------------------------------------------------- mã hoá
def _key(password: str, salt: bytes, kdf: dict[str, int]) -> bytes:
    n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
    if n > 2 ** 20 or r > 16 or p > 4:  # chặn file cố tình làm treo máy
        raise ConfigError("Unsupported key settings in this file")
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024, dklen=32)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def encrypt(data: dict[str, Any], password: str, app_version: str) -> str:
    if len(password or "") < 8:
        raise ConfigError("The backup password must be at least 8 characters")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = {"format": FORMAT, "version": VERSION, "app_version": app_version, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "host": socket.gethostname()[:64], "sections": list(data.keys()),
              "kdf": {"name": "scrypt", **SCRYPT, "salt": _b64(salt)}, "cipher": "AES-256-GCM", "nonce": _b64(nonce)}
    aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    plain = zlib.compress(json.dumps({"format": FORMAT, "data": data}, separators=(",", ":")).encode(), 9)
    ct = aes.gcm_encrypt(_key(password, salt, SCRYPT), nonce, plain, aad)
    return json.dumps({**header, "data": _b64(ct)}, indent=1) + "\n"


def decrypt(text: str, password: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(phần đầu, dữ liệu). Sai mật khẩu / file hỏng / bị sửa -> ConfigError."""
    if not text or len(text) > MAX_FILE:
        raise ConfigError("The file is empty or too large")
    try:
        env = json.loads(text)
        assert isinstance(env, dict) and env.get("format") == FORMAT
    except Exception:
        raise ConfigError("This is not an AppManager configuration backup (.ampbak)")
    if int(env.get("version") or 0) > VERSION:
        raise ConfigError("This backup was made by a newer AppManager; update AppManager first")
    if env.get("cipher") != "AES-256-GCM" or (env.get("kdf") or {}).get("name") != "scrypt":
        raise ConfigError("Unsupported encryption in this file")
    header = {k: v for k, v in env.items() if k != "data"}
    aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    try:
        kdf = env["kdf"]; salt = base64.b64decode(kdf["salt"]); nonce = base64.b64decode(env["nonce"]); ct = base64.b64decode(env["data"])
    except Exception:
        raise ConfigError("The file is damaged")
    try:
        plain = aes.gcm_decrypt(_key(password or "", salt, kdf), nonce, ct, aad)
    except ValueError:
        raise ConfigError("Wrong password, or the file was damaged / changed")
    try:
        inner = json.loads(zlib.decompress(plain))
        assert inner.get("format") == FORMAT and isinstance(inner.get("data"), dict)
    except Exception:
        raise ConfigError("The file is damaged")
    return header, inner["data"]


# ---------------------------------------------------------------- khôi phục
def _safety_backup(password: str, app_version: str) -> str:
    """Lưu cấu hình HIỆN TẠI (mọi phần) trước khi ghi đè — mã hoá bằng cùng mật khẩu — để quay lại được."""
    SAFETY_DIR.mkdir(parents=True, exist_ok=True)
    name = f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}.ampbak"  # 2 lần trong cùng 1 giây không ghi đè nhau
    path = SAFETY_DIR / name
    path.write_text(encrypt(collect(), password, app_version))
    os.chmod(path, 0o600)
    files = sorted(SAFETY_DIR.glob("before-restore-*.ampbak"), key=lambda f: f.stat().st_mtime)
    for old in files[:-SAFETY_KEEP]:
        old.unlink(missing_ok=True)
    return name


def safety_files() -> list[dict[str, Any]]:
    if not SAFETY_DIR.is_dir():
        return []
    out = []
    for f in sorted(SAFETY_DIR.glob("before-restore-*.ampbak"), key=lambda f: f.stat().st_mtime, reverse=True):
        st = f.stat()
        out.append({"name": f.name, "size": st.st_size, "created": int(st.st_mtime)})
    return out


def safety_path(name: str) -> Path:
    if not name.startswith("before-restore-") or not name.endswith(".ampbak") or "/" in name or ".." in name:
        raise ConfigError("Invalid file name")
    p = SAFETY_DIR / name
    if not p.is_file():
        raise ConfigError("File not found")
    return p


def restore(data: dict[str, Any], sections: list[str], password: str, app_version: str) -> dict[str, Any]:
    chosen = [s for s in SECTIONS if s in sections and s in data]
    if not chosen:
        raise ConfigError("Choose at least one part to restore")
    if "accounts" in chosen:
        users = data["accounts"]
        if not isinstance(users, list) or not users:
            raise ConfigError("The backup has no accounts")
        if not any((u.get("role") or "admin") == "admin" and not u.get("disabled") for u in users):
            raise ConfigError("The backup has no active administrator; accounts not restored")
        names = [str(u.get("username") or "").lower() for u in users]
        if len(set(names)) != len(names) or not all(names):
            raise ConfigError("The backup has duplicate or empty user names")
    safety = _safety_backup(password, app_version)
    report: dict[str, Any] = {}
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        for sec in chosen:
            if sec == "accounts":
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
                conn.execute("DELETE FROM users")
                for u in data["accounts"]:
                    fields = [f for f in _USER_FIELDS if f in cols and f in u]
                    conn.execute(f"INSERT INTO users ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                                 [u[f] for f in fields])
                report[sec] = len(data["accounts"])
            elif sec == "app_rules":
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(app_prefs)").fetchall()}
                conn.execute("DELETE FROM app_prefs")
                for r in data["app_rules"]:
                    fields = [f for f in r if f in cols]
                    if "container_name" not in fields:
                        continue
                    conn.execute(f"INSERT INTO app_prefs ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                                 [r[f] for f in fields])
                report[sec] = len(data["app_rules"])
            else:
                allowed = SETTING_SECTIONS[sec]
                vals = {k: v for k, v in (data[sec] or {}).items() if k in allowed}
                for k in allowed:  # khoá có trong máy nhưng không có trong file -> giữ nguyên (file bản cũ)
                    if k in vals:
                        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                     (k, str(vals[k])))
                report[sec] = len(vals)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"restored": report, "safety_backup": safety}


def filename() -> str:
    return f"appmanager-config-{time.strftime('%Y%m%d-%H%M')}.ampbak"

