"""
Thông báo: Telegram, Discord, Slack, Microsoft Teams, Google Chat, Mattermost, Matrix, Signal, ntfy, Gotify,
Bark (iPhone), Pushover, Pushbullet, Email (SMTP), Apprise (cổng tới hơn 100 dịch vụ khác) và Webhook.

- Mỗi kênh chọn sự kiện riêng; gửi trong luồng nền (không làm chậm cập nhật), thử lại khi lỗi mạng.
- Giờ im lặng: tin QUAN TRỌNG (lỗi cập nhật, app gặp sự cố, bảo mật, ổ đĩa) vẫn gửi ngay; tin thường
  (có bản mới, cập nhật xong) được để dành và gửi gộp một tin khi hết giờ im lặng.
- Không spam: "có bản mới" chỉ báo phiên bản chưa báo; app gặp sự cố chỉ báo khi chuyển sang lỗi (và khi hồi phục);
  ổ đĩa đầy tối đa một lần mỗi ngày cho mỗi thư mục.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import queue
import secrets
import threading
import time
from datetime import datetime
from typing import Any, Optional

from app.core.database import get_setting, set_setting

logger = logging.getLogger(__name__)

CHANNEL_TYPES = ("telegram", "discord", "slack", "teams", "googlechat", "mattermost", "matrix", "signal",
                 "ntfy", "gotify", "bark", "pushover", "pushbullet", "email", "apprise", "webhook")
EVENTS = ("update_available", "update_success", "update_failed", "self_update", "app_unhealthy", "disk_low", "security")
CRITICAL = {"update_failed", "app_unhealthy", "disk_low", "security"}
SECRET_FIELDS = {"telegram": ("bot_token",), "discord": ("webhook_url",), "ntfy": ("token",), "gotify": ("app_token",),
                 "webhook": ("secret",), "slack": ("webhook_url",), "teams": ("webhook_url",), "googlechat": ("webhook_url",),
                 "mattermost": ("webhook_url",), "matrix": ("access_token",), "signal": (), "bark": ("device_key",),
                 "pushover": ("app_token", "user_key"), "pushbullet": ("access_token",), "email": ("password",),
                 "apprise": ("urls",)}
REQUIRED = {"telegram": ("bot_token", "chat_id"), "discord": ("webhook_url",), "ntfy": ("topic",),
            "gotify": ("server", "app_token"), "webhook": ("url",), "slack": ("webhook_url",), "teams": ("webhook_url",),
            "googlechat": ("webhook_url",), "mattermost": ("webhook_url",), "matrix": ("server", "access_token", "room_id"),
            "signal": ("server", "number", "recipients"), "bark": ("device_key",), "pushover": ("app_token", "user_key"),
            "pushbullet": ("access_token",), "email": ("host", "sender", "to"), "apprise": ("server",)}
EMAIL_SECURITY = ("starttls", "ssl", "none")

T = {
    "en": {
        "update_available": "🆕 Updates available", "update_success": "✅ Updated", "update_failed": "❌ Update failed",
        "rolled_back": "↩️ Update failed — rolled back", "self_update": "🔄 AppManager Pro", "app_unhealthy": "⚠️ App problem",
        "app_recovered": "✅ App running again", "disk_low": "💾 Disk almost full", "security": "🔒 Security",
        "test": "🔔 Test notification", "digest": "🕘 While notifications were quiet",
        "test_body": "AppManager Pro can reach this channel.", "used": "used", "free": "free",
        "config": "settings applied", "recovery": "recovered after an interruption",
    },
    "vi": {
        "update_available": "🆕 Có bản cập nhật mới", "update_success": "✅ Đã cập nhật", "update_failed": "❌ Cập nhật thất bại",
        "rolled_back": "↩️ Cập nhật lỗi — đã quay về bản cũ", "self_update": "🔄 AppManager Pro", "app_unhealthy": "⚠️ App gặp sự cố",
        "app_recovered": "✅ App đã chạy lại bình thường", "disk_low": "💾 Ổ đĩa sắp đầy", "security": "🔒 Bảo mật",
        "test": "🔔 Tin thử", "digest": "🕘 Trong giờ im lặng",
        "test_body": "AppManager Pro gửi được tới kênh này.", "used": "đã dùng", "free": "còn trống",
        "config": "đã áp dụng cấu hình", "recovery": "đã phục hồi sau sự cố",
    },
}


def _lang() -> str:
    return "vi" if get_setting("notify_lang", "en") == "vi" else "en"


def tr(key: str) -> str:
    return T[_lang()].get(key, T["en"].get(key, key))


# ---------------------------------------------------------------- cấu hình
def channels() -> list[dict[str, Any]]:
    try:
        data = json.loads(get_setting("notify_channels", "[]") or "[]")
        return [c for c in data if isinstance(c, dict) and c.get("type") in CHANNEL_TYPES]
    except Exception:
        return []


def _save_channels(items: list[dict[str, Any]]) -> None:
    set_setting("notify_channels", json.dumps(items))


def masked_channels() -> list[dict[str, Any]]:
    out = []
    for c in channels():
        cfg = dict(c.get("config") or {})
        for f in SECRET_FIELDS.get(c["type"], ()):
            if cfg.get(f):
                cfg[f] = ""
                cfg[f"has_{f}"] = True
        out.append({**c, "config": cfg})
    return out


def upsert_channel(data: dict[str, Any]) -> dict[str, Any]:
    ctype = data.get("type")
    if ctype not in CHANNEL_TYPES:
        raise ValueError("Unknown channel type")
    items = channels()
    cid = data.get("id") or secrets.token_hex(6)
    old = next((c for c in items if c["id"] == cid), None)
    cfg = {k: str(v).strip() for k, v in (data.get("config") or {}).items() if not k.startswith("has_") and v is not None}
    if old and old["type"] == ctype:  # ô bí mật để trống khi sửa = giữ giá trị cũ
        for f in SECRET_FIELDS.get(ctype, ()):
            if not cfg.get(f):
                cfg[f] = (old.get("config") or {}).get(f, "")
    missing = [f for f in REQUIRED[ctype] if not cfg.get(f)]
    if missing:
        raise ValueError("Missing: " + ", ".join(missing))
    for key in ("server", "url", "webhook_url"):
        if cfg.get(key) and not cfg[key].startswith(("http://", "https://")):
            raise ValueError(f"{key} must start with http:// or https://")
    if ctype == "email":
        cfg["security"] = cfg.get("security") or "starttls"
        if cfg["security"] not in EMAIL_SECURITY:
            raise ValueError("security must be starttls, ssl or none")
        port = cfg.get("port") or ("465" if cfg["security"] == "ssl" else "587")
        if not port.isdigit() or not 0 < int(port) < 65536:
            raise ValueError("Invalid SMTP port")
        cfg["port"] = port
        if "@" not in cfg["sender"] or not all("@" in x for x in _split(cfg["to"])):
            raise ValueError("Enter valid e-mail addresses")
    if ctype == "apprise" and not (cfg.get("urls") or cfg.get("key")):
        raise ValueError("Enter Apprise URLs or a configuration key")
    ch = {
        "id": cid, "type": ctype, "name": (data.get("name") or ctype.title()).strip()[:60],
        "enabled": bool(data.get("enabled", True)),
        "events": [e for e in (data.get("events") or list(EVENTS)) if e in EVENTS],
        "config": cfg, "last": (old or {}).get("last") or {},
    }
    items = [c for c in items if c["id"] != cid] + [ch]
    _save_channels(items)
    return ch


def delete_channel(cid: str) -> None:
    _save_channels([c for c in channels() if c["id"] != cid])


def _set_last(cid: str, ok: bool, detail: str) -> None:
    items = channels()
    for c in items:
        if c["id"] == cid:
            c["last"] = {"ok": ok, "detail": detail[:200], "at": int(time.time())}
    _save_channels(items)


def settings() -> dict[str, Any]:
    return {
        "quiet_enabled": get_setting("notify_quiet_enabled", "false") == "true",
        "quiet_start": get_setting("notify_quiet_start", "22:00"),
        "quiet_end": get_setting("notify_quiet_end", "07:00"),
        "disk_pct": int(get_setting("notify_disk_pct", "90") or 90),
        "lang": _lang(),
    }


def save_settings(data: dict[str, Any]) -> None:
    if "quiet_enabled" in data:
        set_setting("notify_quiet_enabled", "true" if data["quiet_enabled"] else "false")
    for key in ("quiet_start", "quiet_end"):
        v = str(data.get(key) or "")
        if len(v) == 5 and v[2] == ":" and v.replace(":", "").isdigit():
            set_setting(f"notify_{key}", v)
    if data.get("disk_pct"):
        set_setting("notify_disk_pct", str(max(50, min(99, int(data["disk_pct"])))))
    if data.get("lang") in ("vi", "en"):
        set_setting("notify_lang", data["lang"])


def in_quiet_hours(now: Optional[datetime] = None) -> bool:
    s = settings()
    if not s["quiet_enabled"]:
        return False
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    a = int(s["quiet_start"][:2]) * 60 + int(s["quiet_start"][3:])
    b = int(s["quiet_end"][:2]) * 60 + int(s["quiet_end"][3:])
    return (a <= cur < b) if a < b else (cur >= a or cur < b)


# ---------------------------------------------------------------- gửi
def _split(v: str) -> list[str]:
    return [x.strip() for x in str(v or "").replace(";", ",").replace("\n", ",").split(",") if x.strip()]


def _send_email(cfg: dict[str, Any], title: str, body: str) -> tuple[bool, str]:
    """Email qua SMTP (không phải HTTP nên không đi qua net.client)."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid

    msg = EmailMessage()
    msg["Subject"] = title.replace("\n", " ")[:200]
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(_split(cfg["to"]))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="appmanager-pro")
    msg.set_content(f"{title}\n\n{body}\n\n— AppManager Pro")
    sec, port, ctx = cfg.get("security") or "starttls", int(cfg.get("port") or 587), ssl.create_default_context()
    smtp = smtplib.SMTP_SSL(cfg["host"], port, timeout=20, context=ctx) if sec == "ssl" else smtplib.SMTP(cfg["host"], port, timeout=20)
    try:
        if sec == "starttls":
            smtp.starttls(context=ctx)
        if cfg.get("username"):
            smtp.login(cfg["username"], cfg.get("password", ""))
        refused = smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return (not refused), ("SMTP OK" if not refused else f"refused: {', '.join(refused)}")


async def _send(ch: dict[str, Any], title: str, body: str, event: str, data: dict[str, Any]) -> tuple[bool, str]:
    from app.core import net

    cfg = ch.get("config") or {}
    t = ch["type"]
    text = f"{title}\n{body}".strip()
    if t == "email":
        try:
            return await asyncio.to_thread(_send_email, cfg, title, body)
        except Exception as exc:
            return False, f"SMTP: {str(exc)[:180]}"
    crit = event in CRITICAL
    async with net.client(timeout=15) as c:
        if t == "telegram":
            r = await c.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                             json={"chat_id": cfg["chat_id"], "text": text[:4000], "disable_web_page_preview": True})
        elif t == "discord":
            color = 0xE11D48 if event in CRITICAL else 0x10B981 if event == "update_success" else 0x0EA5E9
            r = await c.post(cfg["webhook_url"], json={"username": "AppManager Pro",
                                                       "embeds": [{"title": title[:250], "description": body[:4000], "color": color}]})
        elif t == "ntfy":
            server = (cfg.get("server") or "https://ntfy.sh").rstrip("/")
            auth = {"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else {}
            # Gửi dạng JSON: tiêu đề tiếng Việt (UTF-8) không đi qua header được
            r = await c.post(server, json={"topic": cfg["topic"], "title": title, "message": body or title,
                                           "priority": 4 if event in CRITICAL else 3, "tags": ["appmanager"]}, headers=auth)
        elif t == "gotify":
            r = await c.post(f"{cfg['server'].rstrip('/')}/message", params={"token": cfg["app_token"]},
                             json={"title": title, "message": body or title, "priority": 8 if event in CRITICAL else 4})
        elif t in ("slack", "mattermost"):
            mark = "*" if t == "slack" else "**"
            r = await c.post(cfg["webhook_url"], json={"text": f"{mark}{title}{mark}\n{body}".strip(), "username": "AppManager Pro"})
        elif t == "googlechat":
            r = await c.post(cfg["webhook_url"], json={"text": f"*{title}*\n{body}".strip()})
        elif t == "teams":  # Teams Workflows ("Post to a channel when a webhook request is received"): Adaptive Card
            card = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
                    "body": [{"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True,
                              "color": "Attention" if crit else "Default"},
                             {"type": "TextBlock", "text": body or " ", "wrap": True}]}
            r = await c.post(cfg["webhook_url"], json={"type": "message", "attachments": [
                {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}]})
        elif t == "matrix":
            from html import escape
            from urllib.parse import quote

            url = (f"{cfg['server'].rstrip('/')}/_matrix/client/v3/rooms/{quote(cfg['room_id'], safe='')}"
                   f"/send/m.room.message/amp{int(time.time() * 1000)}{secrets.token_hex(3)}")
            r = await c.put(url, headers={"Authorization": f"Bearer {cfg['access_token']}"},
                            json={"msgtype": "m.text", "body": text, "format": "org.matrix.custom.html",
                                  "formatted_body": f"<b>{escape(title)}</b><br>{escape(body).replace(chr(10), '<br>')}"})
        elif t == "signal":  # signal-cli-rest-api (bbernhard/signal-cli-rest-api)
            r = await c.post(f"{cfg['server'].rstrip('/')}/v2/send",
                             json={"message": text, "number": cfg["number"], "recipients": _split(cfg["recipients"])})
        elif t == "bark":
            server = (cfg.get("server") or "https://api.day.app").rstrip("/")
            r = await c.post(f"{server}/push", json={"device_key": cfg["device_key"], "title": title, "body": body or title,
                                                    "group": "AppManager Pro", "level": "timeSensitive" if crit else "active"})
        elif t == "pushover":
            r = await c.post("https://api.pushover.net/1/messages.json",
                             data={"token": cfg["app_token"], "user": cfg["user_key"], "title": title[:250],
                                   "message": (body or title)[:1024], "priority": "1" if crit else "0"})
        elif t == "pushbullet":
            r = await c.post("https://api.pushbullet.com/v2/pushes", headers={"Access-Token": cfg["access_token"]},
                             json={"type": "note", "title": title, "body": body})
        elif t == "apprise":  # Apprise API (caronc/apprise): URL đã lưu theo key, hoặc gửi kèm danh sách URL
            server = cfg["server"].rstrip("/")
            kind = "failure" if crit else "success" if event == "update_success" else "info"
            payload = {"title": title, "body": body or title, "type": kind}
            if cfg.get("key"):
                r = await c.post(f"{server}/notify/{cfg['key']}", json=payload)
            else:
                r = await c.post(f"{server}/notify", json={**payload, "urls": cfg["urls"]})
        else:  # webhook
            payload = {"event": event, "title": title, "message": body, "data": data, "time": int(time.time()), "source": "appmanager-pro"}
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if cfg.get("secret"):
                headers["X-AppManager-Signature"] = "sha256=" + hmac.new(cfg["secret"].encode(), raw, hashlib.sha256).hexdigest()
            r = await c.post(cfg["url"], content=raw, headers=headers)
    ok = 200 <= r.status_code < 300
    return ok, f"HTTP {r.status_code}" + ("" if ok else f": {r.text[:150]}")


def _run_send(ch: dict[str, Any], title: str, body: str, event: str, data: dict[str, Any]) -> tuple[bool, str]:
    """Chạy _send ở mọi nơi gọi: trong luồng thường dùng asyncio.run; đang ở trong event loop thì chạy ở luồng riêng."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_send(ch, title, body, event, data))
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["r"] = asyncio.run(_send(ch, title, body, event, data))
        except Exception as exc:
            box["r"] = (False, str(exc)[:200])

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(60)
    return box.get("r", (False, "timeout"))


def _deliver(ch: dict[str, Any], title: str, body: str, event: str, data: dict[str, Any]) -> tuple[bool, str]:
    last = (False, "")
    for attempt in range(3):
        try:
            last = _run_send(ch, title, body, event, data)
        except Exception as exc:
            last = (False, str(exc)[:200])
        if last[0] or (last[1].startswith("HTTP 4") and not last[1].startswith("HTTP 429")):
            break  # thành công, hoặc lỗi cấu hình (4xx): thử lại vô ích
        time.sleep(2 * (attempt + 1))
    _set_last(ch["id"], *last)
    return last


_q: "queue.Queue[tuple]" = queue.Queue()
_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()


def _run_worker() -> None:
    while True:
        ch, title, body, event, data = _q.get()
        try:
            _deliver(ch, title, body, event, data)
        except Exception:
            logger.exception("Notification failed")
        finally:
            _q.task_done()


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="notify", daemon=True)
            _worker.start()


def notify(event: str, title: str, body: str = "", data: Optional[dict[str, Any]] = None) -> int:
    """Gửi tới mọi kênh đang bật có chọn sự kiện này. Trả về số kênh được xếp hàng gửi."""
    targets = [c for c in channels() if c.get("enabled") and event in (c.get("events") or [])]
    if not targets:
        return 0
    if event not in CRITICAL and in_quiet_hours():
        _defer(event, title, body)
        return 0
    _ensure_worker()
    for ch in targets:
        _q.put((ch, title, body, event, data or {}))
    return len(targets)


def send_test(ch: dict[str, Any]) -> tuple[bool, str]:
    return _deliver(ch, tr("test"), tr("test_body"), "test", {})


def wait_idle(timeout: float = 30) -> None:
    end = time.time() + timeout
    while _q.unfinished_tasks and time.time() < end:
        time.sleep(0.1)


# ---------------------------------------------------------------- giờ im lặng: để dành rồi gửi gộp
def _defer(event: str, title: str, body: str) -> None:
    try:
        items = json.loads(get_setting("notify_deferred", "[]") or "[]")
    except Exception:
        items = []
    items.append({"event": event, "title": title, "body": body, "at": int(time.time())})
    set_setting("notify_deferred", json.dumps(items[-100:]))


def flush_deferred() -> int:
    """Hết giờ im lặng: gửi các tin đã để dành thành MỘT tin cho mỗi kênh. Gọi định kỳ (bộ lập lịch)."""
    if in_quiet_hours():
        return 0
    try:
        items = json.loads(get_setting("notify_deferred", "[]") or "[]")
    except Exception:
        items = []
    if not items:
        return 0
    set_setting("notify_deferred", "[]")
    _ensure_worker()
    n = 0
    for ch in channels():
        if not ch.get("enabled"):
            continue
        mine = [i for i in items if i["event"] in (ch.get("events") or [])]
        if not mine:
            continue
        body = "\n\n".join(f"{i['title']}\n{i['body']}".strip() for i in mine)
        _q.put((ch, tr("digest"), body[:3800], "digest", {"count": len(mine)}))
        n += 1
    return n


# ---------------------------------------------------------------- các nguồn sự kiện
def on_history(container: str, title: str, from_v: str, to_v: str, mode: str, status: str, message: str) -> None:
    """Gọi từ add_update_history: mọi lần cập nhật / khôi phục / sửa cấu hình đều đi qua đây."""
    try:
        is_self = container == "appmanager-pro" or title == "AppManager Pro"
        arrow = f"{from_v} → {to_v}" if (from_v or to_v) and from_v != to_v else (to_v or from_v)
        what = tr("config") if mode == "config" else tr("recovery") if mode == "recovery" else arrow
        if status == "success":
            notify("self_update" if is_self else "update_success",
                   f"{tr('self_update') if is_self else tr('update_success')}: {title}", what,
                   {"app": container, "from": from_v, "to": to_v, "mode": mode, "status": status})
        elif status in ("failed", "rolled_back"):
            head = tr("rolled_back") if status == "rolled_back" else tr("update_failed")
            notify("update_failed", f"{head}: {title}", f"{what}\n{message}".strip(),
                   {"app": container, "from": from_v, "to": to_v, "mode": mode, "status": status, "message": message})
            if is_self:
                notify("self_update", f"{tr('self_update')}: {head}", f"{what}\n{message}".strip(), {"status": status})
    except Exception:
        logger.exception("notify on_history failed")


def on_updates_found(apps: list[dict[str, Any]]) -> None:
    """Sau mỗi lần kiểm tra: báo các bản mới CHƯA từng báo (gộp một tin)."""
    try:
        seen = json.loads(get_setting("notify_seen_updates", "{}") or "{}")
    except Exception:
        seen = {}
    fresh, current = [], {}
    for a in apps:
        if not a.get("has_update") or a.get("is_skipped"):
            continue
        key = a.get("remote_digest") or a.get("remote_version") or "?"
        current[a["name"]] = key
        if seen.get(a["name"]) != key:
            fresh.append(a)
    set_setting("notify_seen_updates", json.dumps(current))
    if fresh:
        lines = [f"• {a.get('title') or a['name']}: {a.get('version') or '?'} → {a.get('remote_version') or '?'}" for a in fresh[:30]]
        notify("update_available", f"{tr('update_available')} ({len(fresh)})", "\n".join(lines),
               {"apps": [{"name": a["name"], "from": a.get("version"), "to": a.get("remote_version")} for a in fresh]})


def on_security(text: str, data: Optional[dict[str, Any]] = None) -> None:
    notify("security", tr("security"), text, data or {})


# Theo dõi app gặp sự cố (gọi định kỳ): chỉ báo khi chuyển trạng thái
_health: dict[str, dict[str, Any]] = {}
_health_ready = False


def check_app_health() -> list[str]:
    """
    App gặp sự cố khi: đang khởi động lại, số lần khởi động lại tăng >= 2 từ lần kiểm tra trước (vòng lặp crash —
    giữa hai lần crash container vẫn hiện "running"), healthcheck "unhealthy", hoặc đang chạy thì thoát với mã lỗi.
    Chỉ báo khi chuyển sang lỗi (và khi hồi phục); lần chạy đầu sau khi khởi động chỉ ghi mốc.
    """
    global _health_ready
    from app.core.docker_client import get_docker_client
    from app.core.run_manager import manage_kind

    try:
        from app.core.updater import _UPDATE_LOCKS
        busy = {n for n, lk in _UPDATE_LOCKS.items() if lk.locked()}
    except Exception:
        busy = set()
    sent: list[str] = []
    now_state: dict[str, dict[str, Any]] = {}
    for c in get_docker_client().containers.list(all=True):
        name = c.name
        labels = (c.attrs.get("Config") or {}).get("Labels") or {}
        if name.endswith("-amp-old") or "-pre-compose-" in name or manage_kind(labels) == "helper" or name in busy:
            continue
        st = c.attrs.get("State") or {}
        rc = int(c.attrs.get("RestartCount") or 0)
        health = (st.get("Health") or {}).get("Status") or ""
        prev = _health.get(name)
        prev_rc = prev["rc"] if prev else 0
        bad = ""
        if st.get("Restarting") or rc - prev_rc >= 2:
            bad = f"keeps restarting (restart count {rc})"
        elif health == "unhealthy":
            bad = "healthcheck unhealthy"
        elif st.get("Status") == "exited" and st.get("ExitCode") not in (0, 137, 143) and prev and prev.get("running"):
            bad = f"exited with code {st.get('ExitCode')}"
        elif prev and prev["bad"].startswith("keeps restarting") and st.get("Status") != "running":
            bad = prev["bad"]  # vẫn đang lỗi (dừng giữa hai lần khởi động lại)
        now_state[name] = {"bad": bad, "rc": rc, "running": st.get("Status") == "running"}
        if not _health_ready:
            continue
        kind = bad.split(" ")[0] if bad else ""
        prev_kind = prev["bad"].split(" ")[0] if prev and prev["bad"] else ""
        if bad and kind != prev_kind:
            notify("app_unhealthy", f"{tr('app_unhealthy')}: {name}", bad, {"app": name, "problem": bad})
            sent.append(name)
        elif not bad and prev_kind and st.get("Status") == "running" and rc == prev_rc:
            notify("app_unhealthy", f"{tr('app_recovered')}: {name}", "", {"app": name, "recovered": True})
            sent.append(name)
        elif not bad and prev_kind and rc != prev_rc:
            now_state[name]["bad"] = prev["bad"]  # vừa khởi động lại thêm: chưa coi là đã hồi phục
    _health.clear()
    _health.update(now_state)
    _health_ready = True
    return sent


def check_disk() -> list[str]:
    import shutil

    from app.core.database import DATA_DIR
    from app.core.docker_client import APPDATA_DIR

    pct_limit = settings()["disk_pct"]
    try:
        sent_log = json.loads(get_setting("notify_disk_sent", "{}") or "{}")
    except Exception:
        sent_log = {}
    out = []
    for path in dict.fromkeys([str(APPDATA_DIR), str(DATA_DIR)]):
        try:
            u = shutil.disk_usage(path)
        except Exception:
            continue
        pct = round(u.used / u.total * 100, 1) if u.total else 0
        if pct >= pct_limit and time.time() - float(sent_log.get(path, 0)) > 24 * 3600:
            gb = lambda b: f"{b / 1024 ** 3:.1f} GB"  # noqa: E731
            notify("disk_low", f"{tr('disk_low')}: {path}", f"{pct}% {tr('used')} • {gb(u.free)} {tr('free')}",
                   {"path": path, "used_pct": pct, "free_bytes": u.free})
            sent_log[path] = time.time()
            out.append(path)
    set_setting("notify_disk_sent", json.dumps(sent_log))
    return out
