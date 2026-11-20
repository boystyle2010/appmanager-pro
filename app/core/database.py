import os
import secrets
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "appmanager.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
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
            """
        )

        # Tạo session secret cố định riêng cho từng server để không bị văng login khi restart
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'session_secret'"
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('session_secret', ?)",
                (secrets.token_hex(32),),
            )

        # Hỗ trợ reset tài khoản khẩn cấp qua biến môi trường RESET_AUTH=true
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
