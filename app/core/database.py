import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "appmanager.db"

DEFAULT_SETTINGS = {
    "check_interval_hours": "6",
    "auto_update_enabled": "false",
    "auto_update_time": "03:30",
    "prune_old_images": "true",
    "github_token": "",
    "auto_rollback": "true",
    "health_wait_seconds": "25",
    "backup_before_update": "true",
    "backup_max_mb": "2048",
    "backup_file_max_mb": "50",
    "backup_keep": "3",
}


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS update_cache (
                container_name TEXT PRIMARY KEY,
                image TEXT,
                local_digest TEXT,
                remote_digest TEXT,
                current_version TEXT,
                remote_version TEXT,
                target_tag TEXT DEFAULT '',
                has_update INTEGER DEFAULT 0,
                source_url TEXT DEFAULT '',
                changelog TEXT DEFAULT '',
                release_tag TEXT DEFAULT '',
                release_url TEXT DEFAULT '',
                published_at TEXT DEFAULT '',
                checked_at TEXT DEFAULT '',
                error TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS app_prefs (
                container_name TEXT PRIMARY KEY,
                auto_update INTEGER DEFAULT 0,
                custom_repo TEXT DEFAULT '',
                skipped_digest TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS update_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_name TEXT NOT NULL,
                app_title TEXT NOT NULL,
                from_version TEXT DEFAULT '',
                to_version TEXT DEFAULT '',
                mode TEXT DEFAULT 'manual',
                status TEXT NOT NULL,
                message TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS login_attempts (
                ip TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip);

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                username TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                action TEXT NOT NULL,
                target TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                ok INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS resource_samples (
                ts INTEGER NOT NULL,
                container TEXT NOT NULL,
                cpu_pct REAL DEFAULT 0,
                mem_bytes INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_resource_samples ON resource_samples(container, ts);
            """
        )

        # Cột mới cho bảng users (2FA) — thêm an toàn cho database cũ
        ucols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, ddl in (
            ("totp_secret", "TEXT DEFAULT ''"),
            ("totp_enabled", "INTEGER DEFAULT 0"),
            ("totp_last_step", "INTEGER DEFAULT 0"),
            ("backup_codes", "TEXT DEFAULT '[]'"),
            ("totp_pending", "TEXT DEFAULT ''"),
            # 0.22 nhiều tài khoản: tài khoản cũ (trước 0.22) là Quản trị
            ("role", "TEXT DEFAULT 'admin'"),
            ("disabled", "INTEGER DEFAULT 0"),
            ("session_ver", "INTEGER DEFAULT 1"),
            ("last_login", "TEXT DEFAULT ''"),
            ("last_ip", "TEXT DEFAULT ''"),
            ("created_by", "TEXT DEFAULT ''"),
            # 0.23 SSO (OIDC): 'local' = mật khẩu, 'oidc' = tạo bởi SSO; oidc_sub = "<issuer>|<sub>"
            ("auth_source", "TEXT DEFAULT 'local'"),
            ("oidc_sub", "TEXT DEFAULT ''"),
            ("email", "TEXT DEFAULT ''"),
        ):
            if col not in ucols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

        # Tự động thêm cột target_tag cho database cũ mà không mất tài khoản Admin
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(update_cache)").fetchall()
        }
        if "target_tag" not in cols:
            conn.execute("ALTER TABLE update_cache ADD COLUMN target_tag TEXT DEFAULT ''")
        if "channels" not in cols:  # JSON: các kênh phát hành (latest / beta...) của image
            conn.execute("ALTER TABLE update_cache ADD COLUMN channels TEXT DEFAULT ''")
        # 0.20: lúc AppManager phát hiện bản mới lần đầu (cho quy tắc "đợi N ngày")
        if "first_seen" not in cols:
            conn.execute("ALTER TABLE update_cache ADD COLUMN first_seen TEXT DEFAULT ''")
        if "first_seen_key" not in cols:
            conn.execute("ALTER TABLE update_cache ADD COLUMN first_seen_key TEXT DEFAULT ''")
        pcols = {r["name"] for r in conn.execute("PRAGMA table_info(app_prefs)").fetchall()}
        if "policy" not in pcols:  # 0.20: JSON quy tắc tự cập nhật (mức, đợi N ngày, ngày, giờ)
            conn.execute("ALTER TABLE app_prefs ADD COLUMN policy TEXT DEFAULT ''")
        if "last_auto" not in pcols:  # ngày (YYYY-MM-DD) đã chạy tự cập nhật cho app
            conn.execute("ALTER TABLE app_prefs ADD COLUMN last_auto TEXT DEFAULT ''")

        # Nhật ký đầy đủ của mỗi lần cập nhật (để xem lại vì sao hỏng sau khi container đã bị tạo lại)
        hcols = {r["name"] for r in conn.execute("PRAGMA table_info(update_history)").fetchall()}
        if "log" not in hcols:
            conn.execute("ALTER TABLE update_history ADD COLUMN log TEXT DEFAULT ''")

        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'session_secret'"
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('session_secret', ?)",
                (secrets.token_hex(32),),
            )

        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )

        if os.getenv("RESET_AUTH", "false").lower() == "true":
            conn.execute("DELETE FROM users;")
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = 'session_secret'",
                (secrets.token_hex(32),),
            )

        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def get_public_settings() -> dict[str, Any]:
    return {
        "check_interval_hours": int(get_setting("check_interval_hours", "6") or 6),
        "auto_update_enabled": get_setting("auto_update_enabled", "false").lower() == "true",
        "auto_update_time": get_setting("auto_update_time", "03:30"),
        "prune_old_images": get_setting("prune_old_images", "true").lower() == "true",
        "auto_rollback": get_setting("auto_rollback", "true").lower() == "true",
        "health_wait_seconds": int(get_setting("health_wait_seconds", "25") or 25),
        "auto_prune_enabled": get_setting("auto_prune_enabled", "false").lower() == "true",
        "auto_prune_freq": get_setting("auto_prune_freq", "weekly"),
        "auto_prune_weekday": int(get_setting("auto_prune_weekday", "6") or 6),
        "auto_prune_time": get_setting("auto_prune_time", "04:00"),
        "auto_prune_images": get_setting("auto_prune_images", "dangling"),
        "auto_prune_cache": get_setting("auto_prune_cache", "true").lower() == "true",
        "auto_prune_last": get_setting("auto_prune_last", ""),
        "backup_before_update": get_setting("backup_before_update", "true").lower() == "true",
        "backup_max_mb": int(get_setting("backup_max_mb", "2048") or 2048),
        "backup_file_max_mb": int(get_setting("backup_file_max_mb", "50") or 50),
        "backup_keep": int(get_setting("backup_keep", "3") or 3),
        "has_github_token": bool(get_setting("github_token", "").strip()),
    }


def has_admin_user() -> bool:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        return row["cnt"] > 0
    finally:
        conn.close()


def create_admin_user(username: str, password_hash: str) -> None:
    create_user(username, password_hash, "admin", "")


def create_user(username: str, password_hash: str, role: str, created_by: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_by) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, created_by),
        )
        conn.commit()
    finally:
        conn.close()


_USER_COLS = ("id, username, password_hash, totp_secret, totp_enabled, totp_last_step, backup_codes, totp_pending, "
              "role, disabled, session_ver, last_login, last_ip, created_by, created_at, auth_source, oidc_sub, email")


def get_user_by_username(username: str):
    conn = get_connection()
    try:
        return conn.execute(f"SELECT {_USER_COLS} FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    finally:
        conn.close()


def get_user_by_oidc_sub(sub_key: str):
    if not sub_key:
        return None
    conn = get_connection()
    try:
        return conn.execute(f"SELECT {_USER_COLS} FROM users WHERE oidc_sub = ?", (sub_key,)).fetchone()
    finally:
        conn.close()


def list_users() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(f"SELECT {_USER_COLS} FROM users ORDER BY id").fetchall()]
    finally:
        conn.close()


def delete_user(username: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
    finally:
        conn.close()


def update_user_fields(username: str, **fields: Any) -> None:
    allowed = {"password_hash", "totp_secret", "totp_enabled", "totp_last_step", "backup_codes", "totp_pending",
               "role", "disabled", "session_ver", "last_login", "last_ip", "auth_source", "oidc_sub", "email"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE users SET {', '.join(f'{c} = ?' for c in cols)} WHERE username = ?",
            (*[fields[c] for c in cols], username),
        )
        conn.commit()
    finally:
        conn.close()


def rotate_session_secret() -> None:
    """Đổi khoá phiên -> mọi phiên đăng nhập cũ hết hiệu lực."""
    set_setting("session_secret", secrets.token_hex(32))


# ---------------- Chống dò mật khẩu (lưu bền vững) ----------------

def count_recent_failures(ip: str, window_seconds: int) -> tuple[int, float]:
    """Trả về (số lần sai trong cửa sổ, thời điểm lần sai cũ nhất trong cửa sổ)."""
    conn = get_connection()
    try:
        cutoff = time.time() - window_seconds
        conn.execute("DELETE FROM login_attempts WHERE ts < ?", (time.time() - 86400,))
        row = conn.execute(
            "SELECT COUNT(*) AS c, MIN(ts) AS first FROM login_attempts WHERE ip = ? AND ts >= ?",
            (ip, cutoff),
        ).fetchone()
        conn.commit()
        return int(row["c"] or 0), float(row["first"] or 0)
    finally:
        conn.close()


def add_login_failure(ip: str) -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (ip, time.time()))
        conn.commit()
    finally:
        conn.close()


def clear_login_failures(ip: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
        conn.commit()
    finally:
        conn.close()


# ---------------- Nhật ký thao tác (audit log) ----------------

def add_audit(action: str, username: str = "", ip: str = "", target: str = "", detail: str = "", ok: bool = True) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO audit_log (username, ip, action, target, detail, ok) VALUES (?, ?, ?, ?, ?, ?)",
            (username or "", ip or "", action, (target or "")[:200], (detail or "")[:500], 1 if ok else 0),
        )
        # Giữ tối đa 3000 dòng gần nhất
        conn.execute("DELETE FROM audit_log WHERE id <= (SELECT MAX(id) FROM audit_log) - 3000")
        conn.commit()
    finally:
        conn.close()


def get_audit_log(limit: int = 200, username: str = "") -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if username:
            rows = conn.execute("SELECT * FROM audit_log WHERE username = ? ORDER BY id DESC LIMIT ?", (username, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------- Lịch sử tài nguyên ----------------

def add_resource_samples(ts: int, rows: list[tuple[str, float, int]]) -> None:
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO resource_samples (ts, container, cpu_pct, mem_bytes) VALUES (?, ?, ?, ?)",
            [(ts, name, cpu, mem) for name, cpu, mem in rows],
        )
        conn.execute("DELETE FROM resource_samples WHERE ts < ?", (ts - 7 * 86400,))
        conn.commit()
    finally:
        conn.close()


def get_resource_samples(container: str, since_ts: int) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ts, cpu_pct, mem_bytes FROM resource_samples WHERE container = ? AND ts >= ? ORDER BY ts",
            (container, since_ts),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_resource_totals(since_ts: int) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ts, SUM(cpu_pct) AS cpu_pct, SUM(mem_bytes) AS mem_bytes FROM resource_samples "
            "WHERE ts >= ? GROUP BY ts ORDER BY ts",
            (since_ts,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_update_cache() -> dict[str, dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM update_cache").fetchall()
        return {r["container_name"]: dict(r) for r in rows}
    finally:
        conn.close()


def get_update_cache_item(container_name: str) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM update_cache WHERE container_name = ?", (container_name,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def save_update_cache(item: dict[str, Any]) -> None:
    item.setdefault("target_tag", "")
    item.setdefault("channels", "")
    conn = get_connection()
    try:
        # Mốc phát hiện bản mới: giữ nguyên khi vẫn là cùng bản mới (cùng digest / tag / phiên bản)
        key = (f"{item.get('remote_digest') or ''}|{item.get('target_tag') or ''}|{item.get('remote_version') or ''}"
               if item.get("has_update") else "")
        prev = conn.execute("SELECT first_seen, first_seen_key FROM update_cache WHERE container_name = ?",
                            (item["container_name"],)).fetchone()
        if not key:
            item["first_seen"], item["first_seen_key"] = "", ""
        elif prev and prev["first_seen_key"] == key and prev["first_seen"]:
            item["first_seen"], item["first_seen_key"] = prev["first_seen"], key
        else:
            item["first_seen"], item["first_seen_key"] = datetime.now(timezone.utc).isoformat(timespec="seconds"), key
        conn.execute(
            """
            INSERT INTO update_cache (
                container_name, image, local_digest, remote_digest,
                current_version, remote_version, target_tag, has_update, source_url,
                changelog, release_tag, release_url, published_at, checked_at, error, channels,
                first_seen, first_seen_key
            ) VALUES (
                :container_name, :image, :local_digest, :remote_digest,
                :current_version, :remote_version, :target_tag, :has_update, :source_url,
                :changelog, :release_tag, :release_url, :published_at, :checked_at, :error, :channels,
                :first_seen, :first_seen_key
            )
            ON CONFLICT(container_name) DO UPDATE SET
                image = excluded.image,
                local_digest = excluded.local_digest,
                remote_digest = excluded.remote_digest,
                current_version = excluded.current_version,
                remote_version = excluded.remote_version,
                target_tag = excluded.target_tag,
                has_update = excluded.has_update,
                source_url = excluded.source_url,
                changelog = excluded.changelog,
                release_tag = excluded.release_tag,
                release_url = excluded.release_url,
                published_at = excluded.published_at,
                checked_at = excluded.checked_at,
                error = excluded.error,
                channels = excluded.channels,
                first_seen = excluded.first_seen,
                first_seen_key = excluded.first_seen_key
            """,
            item,
        )
        conn.commit()
    finally:
        conn.close()


def get_all_app_prefs() -> dict[str, dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM app_prefs").fetchall()
        return {r["container_name"]: dict(r) for r in rows}
    finally:
        conn.close()


def get_app_pref(container_name: str) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM app_prefs WHERE container_name = ?", (container_name,)
        ).fetchone()
        if row:
            return dict(row)
        return {
            "container_name": container_name,
            "auto_update": 0,
            "custom_repo": "",
            "skipped_digest": "",
            "policy": "",
            "last_auto": "",
        }
    finally:
        conn.close()


def save_app_pref(
    container_name: str,
    auto_update: bool | None = None,
    custom_repo: str | None = None,
    skipped_digest: str | None = None,
    policy: str | None = None,
    last_auto: str | None = None,
) -> dict[str, Any]:
    current = get_app_pref(container_name)
    new_auto = int(auto_update) if auto_update is not None else current["auto_update"]
    new_repo = custom_repo.strip() if custom_repo is not None else current["custom_repo"]
    new_skip = skipped_digest.strip() if skipped_digest is not None else current["skipped_digest"]
    new_policy = policy if policy is not None else (current.get("policy") or "")
    new_last = last_auto if last_auto is not None else (current.get("last_auto") or "")

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO app_prefs (container_name, auto_update, custom_repo, skipped_digest, policy, last_auto)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(container_name) DO UPDATE SET
                auto_update = excluded.auto_update,
                custom_repo = excluded.custom_repo,
                skipped_digest = excluded.skipped_digest,
                policy = excluded.policy,
                last_auto = excluded.last_auto
            """,
            (container_name, new_auto, new_repo, new_skip, new_policy, new_last),
        )
        conn.commit()
    finally:
        conn.close()
    return get_app_pref(container_name)


def add_update_history(
    container_name: str,
    app_title: str,
    from_version: str,
    to_version: str,
    mode: str,
    status: str,
    message: str = "",
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO update_history
                (container_name, app_title, from_version, to_version, mode, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (container_name, app_title, from_version, to_version, mode, status, message),
        )
        conn.commit()
    finally:
        conn.close()
    try:  # thông báo (Telegram / Discord / ...) cho mọi lần cập nhật / khôi phục / sửa cấu hình
        from app.core.notify import on_history

        on_history(container_name, app_title, from_version, to_version, mode, status, message)
    except Exception:
        pass


UPDATE_LOG_MAX_CHARS = 60_000  # giữ phần cuối nhật ký (chỗ báo lỗi) nếu quá dài


def get_update_history(limit: int = 40) -> list[dict[str, Any]]:
    """Danh sách lịch sử (không kèm nội dung nhật ký cho nhẹ; chỉ báo có hay không)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, container_name, app_title, from_version, to_version, mode, status, message, created_at, "
            "(COALESCE(log, '') != '') AS has_log FROM update_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{**dict(r), "has_log": bool(r["has_log"])} for r in rows]
    finally:
        conn.close()


def get_last_update_history_id() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM update_history").fetchone()
        return int(row["m"] or 0)
    finally:
        conn.close()


def attach_update_log(container_name: str, after_id: int, log: str) -> None:
    """Gắn nhật ký vào (các) dòng lịch sử mà lần cập nhật này vừa ghi cho app đó."""
    if len(log) > UPDATE_LOG_MAX_CHARS:
        log = "…(truncated)…\n" + log[-UPDATE_LOG_MAX_CHARS:]
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE update_history SET log = ? WHERE container_name = ? AND id > ?",
            (log, container_name, after_id),
        )
        # Chỉ giữ nhật ký của 50 lần cập nhật gần nhất để database không phình to
        conn.execute(
            "UPDATE update_history SET log = '' WHERE log != '' AND id NOT IN "
            "(SELECT id FROM update_history WHERE log != '' ORDER BY id DESC LIMIT 50)"
        )
        conn.commit()
    finally:
        conn.close()


def get_update_log(history_id: int) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, app_title, status, message, created_at, COALESCE(log, '') AS log "
            "FROM update_history WHERE id = ?",
            (history_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
