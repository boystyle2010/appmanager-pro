"""
Sao lưu / khôi phục thư mục dữ liệu của app (vd: /DATA/AppData/<app>) trước khi cập nhật.

- Bản sao lưu: <APP_DATA_DIR>/app-backups/<container>/<YYYYmmdd-HHMMSS>.tar.gz (+ file .json mô tả)
- Bỏ qua nếu thư mục lớn hơn giới hạn (mặc định 2 GB) để không làm đầy SSD.
- Chỉ giữ N bản mới nhất cho mỗi app.
- Bản sao lưu ghi kèm PHIÊN BẢN app lúc đó (image id + tên image + file compose + service).
- Khôi phục: dừng container -> đổi tên thư mục hiện tại thành "<dir>.pre-restore" -> giải nén ->
  nếu container đang chạy image khác và image cũ vẫn còn trên máy -> đưa lại đúng phiên bản cũ
  (gắn lại tag, sửa image trong compose nếu cần, tạo lại container); nếu không thì chạy lại container.
  Dữ liệu mà không kèm phiên bản thì vô ích khi bản mới đã đổi cấu trúc dữ liệu.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
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


def create_backup(
    container_name: str,
    source_dir: str,
    version: str,
    max_mb: int,
    keep: int,
    *,
    image_id: str = "",
    image_ref: str = "",
    compose_path: str = "",
    service: str = "",
) -> dict[str, Any]:
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
        json.dumps({
            "source": str(src), "version": version, "created": int(time.time()), "data_bytes": size,
            "image_id": image_id, "image_ref": image_ref, "compose_path": compose_path, "service": service,
        }),
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


def _split_ref(ref: str) -> tuple[str, str]:
    if not ref or "@" in ref:
        return "", ""
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = ref.rsplit(":", 1)
        return repo, tag
    return ref, "latest"


def _set_compose_image(compose_path: str, service: str, image_ref: str) -> bool:
    """Đặt lại image của service trong compose (giữ comment & x-casaos). Trả về True nếu có đổi."""
    from ruamel.yaml import YAML

    path = Path(compose_path)
    ryaml = YAML()
    ryaml.preserve_quotes = True
    text = path.read_text(encoding="utf-8")
    data = ryaml.load(text) or {}
    svc = (data.get("services") or {}).get(service)
    if not isinstance(svc, dict) or str(svc.get("image", "")).strip() == image_ref or "$" in str(svc.get("image", "")):
        return False
    path.with_name(path.name + ".bak").write_text(text, encoding="utf-8")
    svc["image"] = image_ref
    with path.open("w", encoding="utf-8") as f:
        ryaml.dump(data, f)
    return True


def _restore_version(client, meta: dict[str, Any], current_image_id: str) -> tuple[bool, str]:
    """
    Đưa container về đúng image lúc sao lưu. Trả về (đã_tạo_lại_container, thông_báo).
    Không làm gì nếu container đang chạy đúng image đó, hoặc thiếu thông tin / image cũ đã bị xoá.
    """
    image_id = meta.get("image_id") or ""
    image_ref = meta.get("image_ref") or ""
    compose_path = meta.get("compose_path") or ""
    service = meta.get("service") or ""
    if not image_id or image_id == current_image_id:
        return False, ""
    if not compose_path or not Path(compose_path).is_file() or not service:
        return False, "Data restored; the app version was not changed (compose file unknown)."
    repo, tag = _split_ref(image_ref)
    if not repo:
        return False, "Data restored; the app version was not changed (image pinned by digest)."
    try:
        client.images.get(image_id).tag(repo, tag=tag)
    except Exception:
        return False, "Data restored, but the previous app version's image is no longer on this server."
    changed = _set_compose_image(compose_path, service, image_ref)
    proc = subprocess.run(
        ["docker", "compose", "-f", compose_path, "up", "-d", "--force-recreate", "--no-deps", service],
        cwd=str(Path(compose_path).parent), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(f"Data restored, but recreating the container failed: {tail}")
    note = " (docker-compose.yml image reverted; previous file saved as .bak)" if changed else ""
    return True, f"Previous version {meta.get('version') or image_ref} restored{note}."


def restore_backup(
    container_name: str, filename: str, *, start: bool = True, restore_version: bool = True
) -> dict[str, Any]:
    """
    start=False: chỉ khôi phục dữ liệu, để container dừng (dùng khi rollback, bước sau tự tạo lại container).
    restore_version=False: không đụng tới image/compose.
    """
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
    current_image_id = ""
    try:
        container = client.containers.get(container_name)
        current_image_id = container.attrs.get("Image") or ""
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
        if container is not None and was_running and start:
            try:
                container.start()
            except Exception:
                pass
        return {"ok": False, "error": f"Restore failed: {exc}"}

    base_msg = f"Restored {filename}. Previous data kept at {previous.name}."
    if not start:
        return {"ok": True, "message": base_msg}
    version_note = ""
    if restore_version:
        try:
            recreated, version_note = _restore_version(client, meta, current_image_id)
        except Exception as exc:
            return {"ok": True, "warning": str(exc)}
        if recreated:
            return {"ok": True, "message": f"{base_msg} {version_note}"}
    if container is not None:
        # Sau khi khôi phục luôn chạy lại app (kể cả khi trước đó nó đã dừng vì lỗi)
        try:
            container.start()
        except Exception as exc:
            return {"ok": True, "warning": f"Data restored, but the container did not start: {exc}"}
    if version_note:
        return {"ok": True, "warning": f"{base_msg} {version_note}"}
    return {"ok": True, "message": base_msg}
