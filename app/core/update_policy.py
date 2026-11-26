"""
Quy tắc tự cập nhật theo từng app (0.20).

Chỉ áp dụng cho TỰ cập nhật theo lịch; bấm tay "Cập nhật" vẫn cập nhật như cũ.
- level: "all" (mọi bản) | "minor" (giữ số đầu: 1.x) | "patch" (giữ 2 số đầu: 1.2.x)
- min_age_days: đợi N ngày kể từ khi AppManager phát hiện bản mới (0 = không đợi)
- days: các ngày trong tuần được tự cập nhật (0 = thứ Hai … 6 = Chủ nhật; rỗng = mọi ngày)
- time: giờ riêng "HH:MM" (rỗng = theo giờ tự cập nhật chung trong Cài đặt)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

LEVELS = ("all", "minor", "patch")
DEFAULT = {"level": "all", "min_age_days": 0, "days": [], "time": ""}
_NUM = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse(raw: Any) -> dict[str, Any]:
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else (raw if isinstance(raw, dict) else {})
    except Exception:
        data = {}
    return normalize(data)


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hoá + kiểm tra (ValueError khi sai)."""
    out = dict(DEFAULT)
    level = str(data.get("level") or "all")
    if level not in LEVELS:
        raise ValueError("level must be all, minor or patch")
    out["level"] = level
    try:
        age = int(data.get("min_age_days") or 0)
    except (TypeError, ValueError):
        raise ValueError("min_age_days must be a number")
    if not 0 <= age <= 90:
        raise ValueError("min_age_days must be 0-90")
    out["min_age_days"] = age
    days = sorted({int(d) for d in (data.get("days") or [])})
    if any(d < 0 or d > 6 for d in days):
        raise ValueError("days must be 0 (Monday) to 6 (Sunday)")
    out["days"] = [] if len(days) == 7 else days
    t = str(data.get("time") or "").strip()
    if t and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
        raise ValueError("time must be HH:MM")
    out["time"] = t
    return out


def is_default(p: dict[str, Any]) -> bool:
    return normalize(p) == DEFAULT


def version_parts(v: str) -> Optional[tuple[int, int, int]]:
    """'v1.2.3', '1.27-alpine', '2024.10.1', 'latest-1.2' -> (1, 2, 3). Không có số -> None."""
    m = _NUM.search(str(v or "").lstrip("vV"))
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())  # type: ignore[return-value]


def change_level(current: str, new: str) -> str:
    """'same' (cùng bản, chỉ build lại) | 'patch' | 'minor' | 'major' | 'unknown'."""
    if current and new and current == new:
        return "same"
    a, b = version_parts(current), version_parts(new)
    if not a or not b:
        return "unknown"
    if a == b:
        return "same"
    if a[0] != b[0]:
        return "major"
    if a[1] != b[1]:
        return "minor"
    return "patch"


def _age_days(first_seen: str, now: datetime) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 86400
    except Exception:
        return None


def hold_reason(policy: dict[str, Any], current: str, new: str, first_seen: str,
                now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """None = được tự cập nhật; ngược lại {code, ...} giải thích vì sao đang giữ lại."""
    now = now or datetime.now(timezone.utc)
    level = policy.get("level", "all")
    if level != "all":
        ch = change_level(current, new)
        if ch == "unknown":
            return {"code": "unknown_version", "from": current, "to": new}
        if ch == "major" or (ch == "minor" and level == "patch"):
            return {"code": "level", "change": ch, "from": current, "to": new, "level": level}
    wait = int(policy.get("min_age_days") or 0)
    if wait:
        age = _age_days(first_seen, now) if first_seen else 0.0
        if age is None or age < wait:
            left = max(1, int(wait - (age or 0) + 0.999))
            return {"code": "wait", "days_left": left, "wait": wait}
    return None


def due_today(policy: dict[str, Any], global_time: str, last_auto: str, now_local: datetime) -> bool:
    """Tới giờ tự cập nhật của app hôm nay (giờ máy chủ) và hôm nay chưa chạy."""
    days = policy.get("days") or []
    if days and now_local.weekday() not in days:
        return False
    t = policy.get("time") or global_time or "03:30"
    try:
        hh, mm = (int(x) for x in t.split(":", 1))
    except Exception:
        hh, mm = 3, 30
    if (now_local.hour, now_local.minute) < (hh, mm):
        return False
    return last_auto != now_local.strftime("%Y-%m-%d")
