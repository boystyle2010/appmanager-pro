import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "appmanager.db"

DEFAULT_SETTINGS = {
    "check_interval_hours": "6",
    "auto_update_enabled": "false",
    "auto_update_time": "03:30",
    "prune_old_images": "true",
    "github_token": "",
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
            """
        )

        # Tự động thêm cột target_tag cho database cũ mà không mất tài khoản Admin
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(update_cache)").fetchall()
        }
        if "target_tag" not in cols:
            conn.execute("ALTER TABLE update_cache ADD COLUMN target_tag TEXT DEFAULT ''")

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
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_username(username: str):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
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
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO update_cache (
                container_name, image, local_digest, remote_digest,
                current_version, remote_version, target_tag, has_update, source_url,
                changelog, release_tag, release_url, published_at, checked_at, error
            ) VALUES (
                :container_name, :image, :local_digest, :remote_digest,
                :current_version, :remote_version, :target_tag, :has_update, :source_url,
                :changelog, :release_tag, :release_url, :published_at, :checked_at, :error
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
                error = excluded.error
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
        }
    finally:
        conn.close()


def save_app_pref(
    container_name: str,
    auto_update: bool | None = None,
    custom_repo: str | None = None,
    skipped_digest: str | None = None,
) -> dict[str, Any]:
    current = get_app_pref(container_name)
    new_auto = int(auto_update) if auto_update is not None else current["auto_update"]
    new_repo = custom_repo.strip() if custom_repo is not None else current["custom_repo"]
    new_skip = skipped_digest.strip() if skipped_digest is not None else current["skipped_digest"]

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO app_prefs (container_name, auto_update, custom_repo, skipped_digest)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(container_name) DO UPDATE SET
                auto_update = excluded.auto_update,
                custom_repo = excluded.custom_repo,
                skipped_digest = excluded.skipped_digest
            """,
            (container_name, new_auto, new_repo, new_skip),
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


def get_update_history(limit: int = 40) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM update_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
