"""
Ghi nhớ "bản compose chạy tốt gần nhất" của từng app (<data>/compose-good/<container>.yml).

Vì sao: file compose có thể đã bị sửa (CasaOS, Terminal, trình sửa) mà CHƯA áp dụng vào container. Lần cập nhật
kế tiếp sẽ áp dụng luôn chỗ sửa đó; nếu app hỏng thì phải quay về đúng compose đã tạo ra container đang chạy
tốt — không phải file hiện tại.

Khi nào lưu:
  - sau khi cập nhật / Save & Apply thành công và app chạy ổn;
  - định kỳ: app đang chạy ổn và file compose KHÔNG bị sửa sau lúc tạo container (=> chính file đó tạo ra container).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.database import DATA_DIR

SNAP_DIR = DATA_DIR / "compose-good"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
logger = logging.getLogger("appmanager.compose_snapshot")


def _paths(container: str) -> tuple[Path, Path]:
    if not _SAFE.match(container or ""):
        raise ValueError("Invalid container name")
    return SNAP_DIR / f"{container}.yml", SNAP_DIR / f"{container}.json"


def save_good(container: str, compose_path: str, text: Optional[str] = None) -> None:
    try:
        if text is None:
            text = Path(compose_path).read_text(encoding="utf-8")
        yml, meta = _paths(container)
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        if yml.exists() and yml.read_text(encoding="utf-8") == text and meta.exists():
            m = json.loads(meta.read_text(encoding="utf-8"))
            if m.get("compose_path") == compose_path:
                return
        yml.write_text(text, encoding="utf-8")
        meta.write_text(json.dumps({"compose_path": compose_path, "saved": int(time.time())}), encoding="utf-8")
    except Exception:
        logger.exception("Cannot save compose snapshot of %s", container)


def get_good(container: str, compose_path: str) -> Optional[str]:
    """Bản compose chạy tốt gần nhất của app — chỉ khi nó thuộc đúng file compose này."""
    try:
        yml, meta = _paths(container)
        if not yml.exists() or not meta.exists():
            return None
        if json.loads(meta.read_text(encoding="utf-8")).get("compose_path") != compose_path:
            return None
        return yml.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_docker_time(value: str) -> float:
    # "2026-11-22T23:20:01.123456789Z" -> epoch (bỏ phần lẻ nano giây)
    try:
        base = value.split(".")[0].rstrip("Z")
        return datetime.fromisoformat(base + "+00:00").timestamp()
    except Exception:
        return 0.0


def compose_changed_since_created(compose_path: str, container_attrs: dict[str, Any]) -> bool:
    """File compose bị sửa SAU lúc tạo container (=> nội dung hiện tại chưa từng được áp dụng)."""
    try:
        created = _parse_docker_time(container_attrs.get("Created") or "")
        return bool(created) and Path(compose_path).stat().st_mtime > created + 2
    except Exception:
        return False


def rollback_compose_text(container: str, compose_path: str, current_text: str, container_attrs: dict[str, Any]) -> tuple[str, str]:
    """
    Compose để quay về khi cập nhật / sửa hỏng. Trả về (nội_dung, ghi_chú).
    File đã bị sửa sau lúc tạo container và có bản chạy tốt khác nội dung -> dùng bản chạy tốt.
    """
    if compose_changed_since_created(compose_path, container_attrs):
        good = get_good(container, compose_path)
        if good is not None and good != current_text:
            return good, ("docker-compose.yml was changed after this container was created; "
                          "a failure will restore the last compose that ran correctly")
    return current_text, ""


def snapshot_running_apps() -> None:
    """Định kỳ: lưu compose của các app đang chạy ổn mà file compose chưa bị sửa từ lúc tạo container."""
    from app.core.docker_client import get_docker_client, list_all_apps

    try:
        apps = list_all_apps(False)["apps"]
        client = get_docker_client()
    except Exception:
        return
    for a in apps:
        path = a.get("compose_path") or ""
        if not path or a.get("status") != "running" or not Path(path).is_file():
            continue
        try:
            c = client.containers.get(a["name"])
            st = c.attrs.get("State", {}) or {}
            if st.get("Restarting") or ((st.get("Health") or {}).get("Status") == "unhealthy"):
                continue
            if time.time() - _parse_docker_time(st.get("StartedAt") or "") < 120:
                continue  # vừa khởi động: chưa chắc đã ổn
            if compose_changed_since_created(path, c.attrs):
                continue
            save_good(a["name"], path)
        except Exception:
            continue
