"""
Việc chạy nền cho API (token / tự động hoá): cập nhật 1 app hoặc cập nhật tất cả.

Giao diện web dùng WebSocket để xem log trực tiếp; script / Home Assistant gọi HTTP nên cần
"bắt đầu việc -> trả mã việc ngay -> hỏi lại trạng thái". Việc chỉ giữ trong bộ nhớ (50 việc gần nhất);
kết quả lâu dài vẫn nằm trong Lịch sử cập nhật như mọi lần cập nhật khác.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any, Awaitable, Callable, Optional

MAX_JOBS = 50
MAX_LOG = 200_000
_JOBS: dict[str, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()


def _public(j: dict[str, Any], log: bool = False) -> dict[str, Any]:
    out = {k: v for k, v in j.items() if k != "log"}
    if log:
        out["log"] = j["log"]
    return out


def get(job_id: str, log: bool = True) -> Optional[dict[str, Any]]:
    j = _JOBS.get(job_id)
    return _public(j, log) if j else None


def recent(limit: int = 20) -> list[dict[str, Any]]:
    return [_public(j) for j in sorted(_JOBS.values(), key=lambda x: x["started"], reverse=True)[:limit]]


def running(kind: str, target: str = "") -> Optional[dict[str, Any]]:
    return next((_public(j) for j in _JOBS.values() if j["status"] == "running" and j["kind"] == kind
                 and j["target"] == target), None)


def start(kind: str, target: str, user: str, runner: Callable[[Callable[[str], Awaitable[None]]], Awaitable[dict]]) -> dict:
    """runner(append_log) chạy việc và trả dict kết quả (ok, ...)."""
    if len(_JOBS) >= MAX_JOBS:
        for old in sorted((j for j in _JOBS.values() if j["status"] != "running"), key=lambda x: x["started"])[: len(_JOBS) - MAX_JOBS + 1]:
            _JOBS.pop(old["id"], None)
    job = {"id": secrets.token_hex(6), "kind": kind, "target": target, "user": user, "status": "running",
           "started": time.time(), "finished": 0, "result": {}, "log": ""}
    _JOBS[job["id"]] = job

    async def append(text: str) -> None:
        if "__SELF_UPDATE_RELOAD__" in text:
            return
        job["log"] = (job["log"] + text)[-MAX_LOG:]

    async def main() -> None:
        try:
            res = await runner(append) or {}
            job["result"] = {k: v for k, v in res.items() if isinstance(v, (str, int, float, bool, type(None)))}
            job["status"] = "success" if res.get("ok") else "failed"
        except Exception as exc:  # việc nền không được làm sập server
            job["status"] = "failed"
            job["result"] = {"error": str(exc)[:300]}
            await append(f"\n[ERROR] {exc}\n")
        finally:
            job["finished"] = time.time()

    task = asyncio.get_running_loop().create_task(main())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return _public(job)
