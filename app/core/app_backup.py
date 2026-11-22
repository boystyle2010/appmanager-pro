"""
Sao lưu / khôi phục thư mục dữ liệu của app (vd: /DATA/AppData/<app>) trước khi cập nhật.

- Bản sao lưu: <APP_DATA_DIR>/app-backups/<container>/<YYYYmmdd-HHMMSS>.tar.gz (+ file .json mô tả)
- Bỏ qua nếu thư mục lớn hơn giới hạn (mặc định 2 GB) để không làm đầy SSD.
- Chỉ giữ N bản mới nhất cho mỗi app.
- Khôi phục: dừng container -> đổi tên thư mục hiện tại thành "<dir>.pre-restore" -> giải nén -> chạy lại container.
"""
from __future__ import annotations

import json
import re
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

from app.core.database import DATA_DIR
from app.core.docker_client import APPDATA_DIR, get_docker_client

BACKUP_ROOT = DATA_DIR / "app-backups"
_NAME_RE = re.compile(r"^\d{8}-\d{6}\.tar\.gz$")
_SAFE_APP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def format_bytes(num: float) -> str:
    val = float(max(0, num or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} TB"


def _app_dir(container_name: str) -> Path:
    if not _SAFE_APP_RE.match(container_name or ""):
        raise ValueError("Invalid app name")
    return BACKUP_ROOT / container_name


def _inside(child: Path, parent: Path) -> bool:
    try:
        child = child.resolve()
        parent = parent.resolve()
        return child != parent and parent in child.parents
    except Exception:
        return False


def dir_size(path: Path, stop_after: int | None = None) -> int:
    """Tổng dung lượng thư mục (dừng sớm khi vượt stop_after để khỏi quét lâu)."""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
                if stop_after is not None and total > stop_after:
                    return total
        except OSError:
            continue
    return total


def create_backup(container_name: str, source_dir: str, version: str, max_mb: int, keep: int) -> dict[str, Any]:
    if not source_dir:
        return {"ok": False, "skipped": True, "message": "No app data folder detected"}
    src = Path(source_dir)
    if not src.is_dir() or not _inside(src, APPDATA_DIR):
        return {"ok": False, "skipped": True, "message": f"Data folder is not inside {APPDATA_DIR}"}
    if _inside(BACKUP_ROOT, src) or src.resolve() == DATA_DIR.resolve() or _inside(DATA_DIR, src):
        return {"ok": False, "skipped": True, "message": "Refusing to back up AppManager Pro's own data"}

    limit = max(1, int(max_mb)) * 1024 * 1024
    size = dir_size(src, stop_after=limit)
    if size > limit:
        return {"ok": False, "skipped": True, "message": f"Data folder is larger than {max_mb} MB — backup skipped"}

    bdir = _app_dir(container_name)
    bdir.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S") + ".tar.gz"
    target = bdir / name
    tmp = bdir / (name + ".part")
    try:
        with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
            tar.add(str(src), arcname=".")
        tmp.rename(target)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return {"ok": False, "message": f"Backup failed: {exc}"}

    (bdir / (name + ".json")).write_text(
        json.dumps({"source": str(src), "version": version, "created": int(time.time()), "data_bytes": size}),
        encoding="utf-8",
    )
    _apply_retention(bdir, keep)
    return {"ok": True, "file": name, "size": format_bytes(target.stat().st_size), "message": f"Backup saved: {name}"}


def _apply_retention(bdir: Path, keep: int) -> None:
    files = sorted((p for p in bdir.glob("*.tar.gz") if _NAME_RE.match(p.name)), reverse=True)
    for old in files[max(1, int(keep)):]:
        old.unlink(missing_ok=True)
        Path(str(old) + ".json").unlink(missing_ok=True)


def list_backups() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not BACKUP_ROOT.exists():
        return out
    for adir in sorted(BACKUP_ROOT.iterdir()):
        if not adir.is_dir():
            continue
        for f in sorted(adir.glob("*.tar.gz"), reverse=True):
            if not _NAME_RE.match(f.name):
                continue
            meta: dict[str, Any] = {}
            try:
                meta = json.loads(Path(str(f) + ".json").read_text(encoding="utf-8"))
            except Exception:
                pass
            out.append(
                {
                    "app": adir.name,
                    "file": f.name,
                    "size": format_bytes(f.stat().st_size),
                    "created": meta.get("created") or int(f.stat().st_mtime),
                    "version": meta.get("version") or "",
                    "source": meta.get("source") or "",
                }
            )
    out.sort(key=lambda x: x["created"], reverse=True)
    return out


def _backup_file(container_name: str, filename: str) -> Path:
    if not _NAME_RE.match(filename or ""):
        raise ValueError("Invalid backup name")
    f = _app_dir(container_name) / filename
    if not f.exists():
        raise FileNotFoundError("Backup not found")
    return f


def delete_backup(container_name: str, filename: str) -> None:
    f = _backup_file(container_name, filename)
    f.unlink(missing_ok=True)
    Path(str(f) + ".json").unlink(missing_ok=True)


def restore_backup(container_name: str, filename: str) -> dict[str, Any]:
    f = _backup_file(container_name, filename)
    try:
        meta = json.loads(Path(str(f) + ".json").read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "Backup metadata is missing"}
    dest = Path(meta.get("source") or "")
    if not _inside(dest, APPDATA_DIR):
        return {"ok": False, "error": "Backup target is outside the app data folder"}

    client = get_docker_client()
    container = None
    was_running = False
    try:
        container = client.containers.get(container_name)
        # "restarting" = app đang lỗi & khởi động lại liên tục (thường gặp sau cập nhật hỏng): vẫn phải
        # dừng trước khi ghi đè dữ liệu và chạy lại sau khi khôi phục.
        was_running = container.status in ("running", "restarting")
        if was_running:
            container.stop(timeout=30)
    except Exception:
        container = None

    previous = dest.with_name(dest.name + ".pre-restore")
    try:
        if previous.exists():
            shutil.rmtree(previous)
        if dest.exists():
            dest.rename(previous)
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(f, "r:gz") as tar:
            # Bản sao lưu do chính app tạo -> giữ nguyên quyền & chủ sở hữu, nhưng vẫn chặn đường dẫn thoát ra ngoài
            root = dest.resolve()
            for m in tar.getmembers():
                target = (root / m.name).resolve()
                if m.name.startswith("/") or (target != root and root not in target.parents):
                    raise ValueError(f"Unsafe path in backup: {m.name}")
                if m.islnk() and m.linkname.startswith("/"):
                    raise ValueError(f"Unsafe link in backup: {m.name}")
            try:
                tar.extractall(dest, numeric_owner=True, filter="fully_trusted")
            except TypeError:  # Python cũ không có tham số filter
                tar.extractall(dest, numeric_owner=True)
    except Exception as exc:
        # Hoàn tác: trả lại thư mục cũ
        try:
            if dest.exists():
                shutil.rmtree(dest)
            if previous.exists():
                previous.rename(dest)
        except Exception:
            pass
        if container is not None and was_running:
            try:
                container.start()
            except Exception:
                pass
        return {"ok": False, "error": f"Restore failed: {exc}"}

    if container is not None and was_running:
        try:
            container.start()
        except Exception as exc:
            return {"ok": True, "warning": f"Data restored, but the container did not start: {exc}"}
    return {"ok": True, "message": f"Restored {filename}. Previous data kept at {previous.name}"}
