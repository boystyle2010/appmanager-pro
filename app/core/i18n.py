"""Ngôn ngữ giao diện (0.27).

- Tiếng Anh + tiếng Việt: nằm sẵn trong `app/static/js/i18n.js` (giao diện), `auth.html` (trang đăng nhập) và
  `notify.T` (tin nhắn thông báo) — là bản GỐC, mọi khoá mới phải có ở cả hai.
- Ngôn ngữ khác: mỗi ngôn ngữ một file `app/static/i18n/<mã>.json` (`_meta` + `ui` + `login` + `notify`). Trình duyệt
  chỉ tải file của ngôn ngữ đang chọn; khoá thiếu tự hiện tiếng Anh. Thêm ngôn ngữ = thêm 1 file JSON (xem TRANSLATING.md).
- `en.json` là bản mẫu sinh tự động (`python scripts/i18n.py export`) để người dịch biết cần dịch gì.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("appmanager.i18n")

I18N_DIR = Path(__file__).resolve().parent.parent / "static" / "i18n"
SECTIONS = ("ui", "login", "notify")
BUILTIN = {
    "en": {"name": "English", "english": "English", "locale": "en-US"},
    "vi": {"name": "Tiếng Việt", "english": "Vietnamese", "locale": "vi-VN"},
}
CODE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


@lru_cache(maxsize=None)
def pack(code: str) -> dict[str, Any]:
    """Nội dung file <mã>.json ({} nếu không có / hỏng)."""
    if not CODE_RE.match(code or ""):
        return {}
    f = I18N_DIR / f"{code}.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # file dịch hỏng không được làm sập AppManager
        logger.warning("Cannot read translation %s: %s", f.name, exc)
        return {}


def _count(d: dict[str, Any]) -> int:
    return sum(len(d.get(s) or {}) for s in SECTIONS)


@lru_cache(maxsize=1)
def languages() -> list[dict[str, Any]]:
    """Danh sách ngôn ngữ cho giao diện: mã, tên gốc, tên tiếng Anh, locale (ngày giờ), % đã dịch, bản nháp máy dịch?"""
    src = pack("en")
    total = _count(src) or 1
    src_keys = {s: set((src.get(s) or {}).keys()) for s in SECTIONS}
    out = [{"code": c, **m, "coverage": 100, "draft": False} for c, m in BUILTIN.items()]
    for f in sorted(I18N_DIR.glob("*.json")):
        code = f.stem
        if code in BUILTIN or not CODE_RE.match(code):
            continue
        d = pack(code)
        meta = d.get("_meta") or {}
        if not meta.get("name"):
            continue
        done = sum(len(src_keys[s] & set((d.get(s) or {}).keys())) for s in SECTIONS)
        out.append({"code": code, "name": meta["name"], "english": meta.get("english", code), "locale": meta.get("locale", code),
                    "coverage": min(100, round(done * 100 / total)), "draft": bool(meta.get("machine_draft"))})
    return out


def codes() -> set[str]:
    return {x["code"] for x in languages()}


def notify_text(code: str, key: str) -> str | None:
    """Câu thông báo của ngôn ngữ ngoài EN/VI (None = chưa dịch -> dùng tiếng Anh)."""
    v = (pack(code).get("notify") or {}).get(key)
    return v if isinstance(v, str) and v else None
