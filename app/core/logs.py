"""
Log container (0.21): xem theo khoảng thời gian, tìm chữ, lọc mức (lỗi / cảnh báo), tải về file .txt.

- Lấy từ Docker (`container.logs`, kèm thời gian) — không lưu log riêng, không tốn ổ đĩa.
- Tìm: không phân biệt hoa thường; nhiều từ cách nhau bằng dấu cách = dòng phải có đủ các từ; "-từ" = bỏ dòng có từ đó.
- Mức: nhận theo chữ thường gặp trong log (ERROR / FATAL / Traceback…, WARN…). Dòng nằm trong một khối lỗi
  (vd các dòng tiếp theo của Traceback, bắt đầu bằng khoảng trắng) được tính theo dòng lỗi phía trên.
- Giới hạn để không làm chậm máy: xem tối đa MAX_SCAN dòng mới nhất mỗi lần, trả về tối đa `limit` dòng khớp;
  tải về tối đa MAX_DOWNLOAD byte.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Iterator, Optional

import docker
from docker.errors import NotFound

from app.core.docker_client import get_docker_client

RANGES = {"15m": 900, "1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "all": 0}
LEVELS = ("", "warn", "error")
MAX_SCAN = 50_000
MAX_LIMIT = 5_000
MAX_DOWNLOAD = 50 * 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")

_ERR = re.compile(r"\b(error|err|fatal|fail(?:ed|ure)?|crit(?:ical)?|panic|emerg|alert|exception|traceback|segfault)\b"
                  r"|\[(?:e|err|error|fatal|crit)\]|\blevel=(?:error|fatal|crit)", re.I)
_WARN = re.compile(r"\b(warn(?:ing)?|deprecated)\b|\[(?:w|warn|warning)\]|\blevel=warn", re.I)
_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z?)\s?")


class LogError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def level_of(text: str) -> str:
    if _ERR.search(text):
        return "error"
    if _WARN.search(text):
        return "warn"
    return ""


def parse_query(q: str) -> tuple[list[str], list[str]]:
    q = (q or "").strip()[:200]
    inc, exc = [], []
    for w in q.split():
        if w.startswith("-") and len(w) > 1:
            exc.append(w[1:].lower())
        else:
            inc.append(w.lower())
    return inc, exc


def _since(rng: str) -> Optional[int]:
    if rng not in RANGES:
        raise LogError(400, "Invalid time range")
    sec = RANGES[rng]
    return int(time.time()) - sec if sec else None


def _container(name: str):
    if not NAME_RE.match(name or ""):
        raise LogError(400, "Invalid container name")
    try:
        return get_docker_client().containers.get(name)
    except NotFound:
        raise LogError(404, "App not found")
    except docker.errors.DockerException as exc:
        raise LogError(502, f"Docker error: {exc}")


class _Filter:
    """Lọc từng dòng; nhớ mức của dòng trước để dòng tiếp nối (thụt lề) của một khối lỗi đi cùng nó."""

    def __init__(self, q: str, level: str):
        if level not in LEVELS:
            raise LogError(400, "Invalid level")
        self.inc, self.exc = parse_query(q)
        self.level = level
        self.prev_level = ""

    def match(self, line: str) -> bool:
        m = _TS.match(line)
        text = line[m.end():] if m else line
        lv = level_of(text)
        if not lv and text[:1] in (" ", "\t") and self.prev_level:
            lv = self.prev_level  # dòng tiếp theo của Traceback / stack trace
        self.prev_level = lv
        if self.level == "error" and lv != "error":
            return False
        if self.level == "warn" and lv not in ("warn", "error"):
            return False
        low = text.lower()
        if self.inc and not all(w in low for w in self.inc):
            return False
        if self.exc and any(w in low for w in self.exc):
            return False
        return True


def fetch(name: str, rng: str = "1h", q: str = "", level: str = "", limit: int = 2000) -> dict[str, Any]:
    """Dòng log khớp (mới nhất ở cuối). `scanned` = số dòng đã xem; `capped` = còn dòng cũ hơn chưa xem."""
    since = _since(rng)
    limit = max(50, min(int(limit or 2000), MAX_LIMIT))
    flt = _Filter(q, level)
    c = _container(name)
    kw: dict[str, Any] = {"stdout": True, "stderr": True, "timestamps": True, "tail": MAX_SCAN}
    if since:
        kw["since"] = since
    try:
        raw = c.logs(**kw)
    except docker.errors.DockerException as exc:
        raise LogError(502, f"Docker error: {exc}")
    lines = raw.decode("utf-8", errors="replace").splitlines()
    matched = [ln for ln in lines if flt.match(ln)]
    return {
        "name": name, "range": rng, "q": q, "level": level,
        "scanned": len(lines), "capped": len(lines) >= MAX_SCAN,
        "matched": len(matched), "truncated": len(matched) > limit,
        "text": "\n".join(matched[-limit:]) + ("\n" if matched else ""),
    }


def download(name: str, rng: str = "24h", q: str = "", level: str = "") -> tuple[str, Iterator[bytes]]:
    """(tên file, luồng byte) — đọc dần từ Docker để không giữ cả file log trong RAM."""
    since = _since(rng)
    flt = _Filter(q, level)
    c = _container(name)
    kw: dict[str, Any] = {"stdout": True, "stderr": True, "timestamps": True, "stream": True, "follow": False}
    if since:
        kw["since"] = since
    try:
        stream = c.logs(**kw)
    except docker.errors.DockerException as exc:
        raise LogError(502, f"Docker error: {exc}")
    fname = f"{name}-logs-{rng}-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"

    def gen() -> Iterator[bytes]:
        sent, buf = 0, b""
        head = (f"# AppManager Pro — logs of {name} · range: {rng}"
                + (f" · search: {q}" if q else "") + (f" · level: {level}" if level else "") + "\n").encode()
        yield head
        try:
            for chunk in stream:
                buf += chunk
                *done, buf = buf.split(b"\n")
                out = [ln for ln in done if flt.match(ln.decode("utf-8", errors="replace"))]
                if out:
                    data = b"\n".join(out) + b"\n"
                    if sent + len(data) > MAX_DOWNLOAD:
                        yield b"\n# ... stopped: the file reached 50 MB. Choose a shorter range or a search.\n"
                        return
                    sent += len(data)
                    yield data
            if buf and flt.match(buf.decode("utf-8", errors="replace")):
                yield buf + b"\n"
        finally:
            try:
                stream.close()
            except Exception:
                pass

    return fname, gen()
