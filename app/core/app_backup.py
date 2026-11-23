"""
Sao lưu / khôi phục FILE CÀI ĐẶT của app (trong /DATA/AppData/<app>) trước khi cập nhật — không sao lưu cả thư mục.

Chỉ lấy những gì giữ cài đặt người dùng đã thiết lập: file cấu hình (json, yaml, toml, ini, conf, env, xml...),
database nhỏ (.db/.sqlite kèm -wal/-shm), chứng chỉ & khoá, file cấu hình không đuôi dạng văn bản ≤ 1 MB
(vd .storage/core.config_entries của Home Assistant). Không lấy media, file người dùng, log, cache...:
  - chỉ trong các thư mục / file được MOUNT vào container và nằm trong /DATA/AppData;
  - không duyệt mount / thư mục con tên kiểu media/storage/downloads/backups/cache... (SKIP_NAMES);
  - bỏ file cài đặt lớn hơn giới hạn mỗi file (mặc định 50 MB, vd database lịch sử hàng GB).
Khôi phục chỉ ghi đè đúng các file cài đặt đó; mọi file khác (dữ liệu, media, log) giữ nguyên.

- Bản sao lưu: <APP_DATA_DIR>/app-backups/<container>/<YYYYmmdd-HHMMSS>.tar.gz (+ file .json mô tả)
- Bỏ qua nếu phần cần sao lưu vẫn lớn hơn giới hạn tổng (mặc định 2 GB).
- Chỉ giữ N bản mới nhất cho mỗi app.
- Bản sao lưu ghi kèm PHIÊN BẢN app lúc đó (image id + tên image + file compose + service).
- Khôi phục: dừng container -> chuyển các file sẽ bị ghi đè / không có trong bản sao lưu sang "<dir>.pre-restore"
  -> giải nén ->
  nếu container đang chạy image khác và image cũ vẫn còn trên máy -> đưa lại đúng phiên bản cũ
  (gắn lại tag, sửa image trong compose nếu cần, tạo lại container); nếu không thì chạy lại container.
  Dữ liệu mà không kèm phiên bản thì vô ích khi bản mới đã đổi cấu trúc dữ liệu.
"""
from __future__ import annotations

import json
import os
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
DEFAULT_FILE_MAX_MB = 50

# Tên thư mục (mount đích hoặc thư mục con) chứa nội dung người dùng / dữ liệu nặng / tạo lại được -> không sao lưu
SKIP_NAMES = {
    "media", "movies", "movie", "tv", "series", "music", "audio", "photos", "photo", "pictures", "images",
    "videos", "video", "downloads", "download", "torrents", "storage", "share", "shares", "files", "library",
    "sync", "syncthing", "backup", "backups", "cache", "caches", ".cache", "tmp", "temp", "transcode",
    "transcodes", "thumbnails", "thumbs", "trash", ".trash", ".recycle", "recycle", "host_root", "mnt",
}
# CHỈ sao lưu file cài đặt / lõi của app: cấu hình, database nhỏ, chứng chỉ & khoá
CONFIG_EXTS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".config", ".env", ".xml", ".properties",
    ".plist", ".db", ".sqlite", ".sqlite3", ".db3", ".pem", ".crt", ".cer", ".key", ".p12", ".pfx",
    ".htpasswd", ".htaccess",
    ".tdb", ".ldb",                          # database của Samba (mật khẩu SMB, vd OmniDrive data/wpro/samba)
    ".secret", ".token", ".passwd", ".shadow",  # khoá phiên / mật khẩu đã băm
}
DB_EXTS = {".db", ".sqlite", ".sqlite3", ".db3"}
TEXT_NOEXT_MAX = 1024 * 1024  # file không đuôi (vd .storage/core.config_entries) <= 1 MB và là văn bản


_LOG_RE = re.compile(r"\.(log|jsonl|ndjson)(\.\d+)?(\.gz)?$", re.IGNORECASE)


def _is_log(rel: str) -> bool:
    """File log: khi khôi phục luôn giữ bản hiện tại (đầy đủ lịch sử hơn bản trong sao lưu)."""
    parts = [x.lower() for x in Path(rel).parts]
    return bool(_LOG_RE.search(rel)) or any(x in ("log", "logs") for x in parts[:-1])


def _skip_name(name: str) -> bool:
    return name.strip("/").lower() in SKIP_NAMES


def _is_config_file(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in CONFIG_EXTS:
        return True
    for tail in ("-wal", "-shm", "-journal"):  # đi kèm database SQLite: phải sao lưu/khôi phục cùng nhau
        if name.endswith(tail) and Path(name[: -len(tail)]).suffix in DB_EXTS:
            return True
    if suffix in (".log", ".jsonl", ".ndjson", ".gz", ".zip", ".tar", ".bak", ".tmp", ".lock", ".pid", ".sock"):
        return False  # nhật ký / file tạm / file nén: không phải cài đặt
    # Còn lại: file nhỏ dạng văn bản — không đuôi (settings, .env...) bất kỳ văn bản nào; đuôi lạ
    # (vd .storage/core.config_entries của Home Assistant) chỉ khi nội dung là JSON.
    try:
        if path.lstat().st_size > TEXT_NOEXT_MAX:
            return False
        with open(path, "rb") as f:
            head = f.read(4096)
        if not head or b"\x00" in head:
            return False
        text = head.decode("utf-8", errors="strict") if len(head) < 4096 else head[:4000].decode("utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return False
    if suffix == "" or name.startswith("."):
        return True
    return text.lstrip()[:1] in ("{", "[")


def _wanted_file(path: Path, file_max: int) -> tuple[bool, str]:
    """(có sao lưu không, lý do bỏ qua — rỗng nếu chỉ đơn giản không phải file cài đặt)."""
    if path.is_symlink():
        return True, ""
    if not _is_config_file(path):
        return False, ""
    try:
        size = path.lstat().st_size
    except OSError:
        return False, "unreadable"
    if size > file_max:
        return False, f"larger than {file_max // (1024 * 1024)} MB ({format_bytes(size)})"
    return True, ""


def plan_backup_roots(top: Path, mounts: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """
    Các đường dẫn (tương đối so với thư mục app) cần sao lưu, và các mount bị bỏ qua.
    Chỉ mount bind nằm trong thư mục app; bỏ mount có tên kiểu media/storage/backups...
    """
    roots: list[str] = []
    skipped: list[str] = []
    top_r = top.resolve()
    for m in mounts or []:
        src = m.get("Source") or ""
        dst = m.get("Destination") or ""
        if m.get("Type", "bind") != "bind" or not src:
            continue
        try:
            sp = Path(src).resolve()
        except Exception:
            continue
        if sp != top_r and top_r not in sp.parents:
            continue  # ngoài thư mục app (vd /DATA, /media, /) -> không phải dữ liệu riêng của app
        if _skip_name(Path(dst).name) or (sp != top_r and _skip_name(sp.name)):
            skipped.append(f"{src} -> {dst}")
            continue
        rel = "." if sp == top_r else str(sp.relative_to(top_r))
        roots.append(rel)
    # Bỏ mục nằm trong mục khác đã chọn
    roots = sorted(set(roots), key=lambda r: (r.count("/"), r))
    final: list[str] = []
    for r in roots:
        if not any(r == f or f == "." or r.startswith(f + "/") for f in final):
            final.append(r)
    return final, skipped


def _walk_wanted(top: Path, roots: list[str], file_max: int, skipped: list[str] | None = None):
    """Duyệt các file/thư mục thuộc diện sao lưu: trả về (đường_dẫn, tên_tương_đối, là_thư_mục)."""
    for rel in roots:
        base = (top / rel) if rel != "." else top
        if base.is_symlink() or base.is_file():
            ok, why = _wanted_file(base, file_max)
            if ok:
                yield base, rel, False
            elif skipped is not None and why:
                skipped.append(f"{rel} ({why})")
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            d = Path(dirpath)
            drel = os.path.relpath(d, top)
            yield d, drel, True
            keep_dirs = []
            for dn in dirnames:
                full = d / dn
                if _skip_name(dn):
                    if skipped is not None:
                        skipped.append(f"{os.path.relpath(full, top)}/ (folder skipped)")
                elif full.is_symlink():
                    yield full, os.path.relpath(full, top), False  # link thư mục: lưu link, không đi theo
                else:
                    keep_dirs.append(dn)
            dirnames[:] = keep_dirs
            for fn in filenames:
                fp = d / fn
                ok, why = _wanted_file(fp, file_max)
                if ok:
                    yield fp, os.path.relpath(fp, top), False
                elif skipped is not None and why:
                    skipped.append(f"{os.path.relpath(fp, top)} ({why})")
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
    mounts: list[dict[str, Any]] | None = None,
    file_max_mb: int = DEFAULT_FILE_MAX_MB,
    image_id: str = "",
    image_ref: str = "",
    compose_path: str = "",
    service: str = "",
    compose_text: str | None = None,
) -> dict[str, Any]:
    if not source_dir:
        return {"ok": False, "skipped": True, "message": "No app data folder detected"}
    src = Path(source_dir)
    if not src.is_dir() or not _inside(src, APPDATA_DIR):
        return {"ok": False, "skipped": True, "message": f"Data folder is not inside {APPDATA_DIR}"}
    if _inside(BACKUP_ROOT, src) or src.resolve() == DATA_DIR.resolve() or _inside(DATA_DIR, src):
        return {"ok": False, "skipped": True, "message": "Refusing to back up AppManager Pro's own data"}

    roots, skipped_mounts = plan_backup_roots(src, mounts or [])
    if not roots:
        return {"ok": False, "skipped": True,
                "message": "No app configuration folder to back up (only media / large folders are mounted)"}
    file_max = max(1, int(file_max_mb)) * 1024 * 1024
    limit = max(1, int(max_mb)) * 1024 * 1024
    skipped: list[str] = []
    walked = list(_walk_wanted(src, roots, file_max, skipped))
    files = [(p, rel, d) for p, rel, d in walked if not d]
    # Chỉ giữ thư mục cha của file được sao lưu (giữ quyền/chủ sở hữu), không lưu cả cây thư mục rỗng
    needed_dirs: set[str] = set()
    for _p, rel, _d in files:
        parent = Path(rel).parent
        while str(parent) not in ("", "."):
            needed_dirs.add(os.path.normpath(str(parent)))
            parent = parent.parent
    entries = [(p, rel, d) for p, rel, d in walked if d and os.path.normpath(rel) in needed_dirs] + files
    if not files:
        return {"ok": False, "skipped": True, "message": "No configuration files found to back up"}
    size = 0
    for p, _rel, is_dir in entries:
        if not is_dir and not p.is_symlink():
            try:
                size += p.stat().st_size
            except OSError:
                pass
    if size > limit:
        return {"ok": False, "skipped": True,
                "message": f"App configuration is larger than {max_mb} MB ({format_bytes(size)}) — backup skipped"}

    bdir = _app_dir(container_name)
    bdir.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S") + ".tar.gz"
    target = bdir / name
    tmp = bdir / (name + ".part")
    try:
        with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
            for p, rel, _is_dir in entries:
                tar.add(str(p), arcname=rel, recursive=False)
        tmp.rename(target)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return {"ok": False, "message": f"Backup failed: {exc}"}

    (bdir / (name + ".json")).write_text(
        json.dumps({
            "source": str(src), "version": version, "created": int(time.time()), "data_bytes": size,
            "roots": roots, "file_max_bytes": file_max, "skipped_mounts": skipped_mounts,
            "skipped": skipped[:200], "skipped_count": len(skipped),
            "image_id": image_id, "image_ref": image_ref, "compose_path": compose_path, "service": service,
            "compose_text": compose_text,
        }),
        encoding="utf-8",
    )
    _apply_retention(bdir, keep)
    return {
        "ok": True, "file": name, "size": format_bytes(target.stat().st_size),
        "message": f"Backup saved: {name} ({len(files)} settings file(s), {format_bytes(size)})",
        "roots": roots, "skipped_mounts": skipped_mounts, "skipped": skipped,
    }


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
    Đưa app về đúng trạng thái lúc sao lưu: docker-compose.yml + image. Trả về (đã_tạo_lại_container, thông_báo).
    Không làm gì nếu container đang chạy đúng image đó và compose không khác.
    """
    image_id = meta.get("image_id") or ""
    image_ref = meta.get("image_ref") or ""
    compose_path = meta.get("compose_path") or ""
    compose_text = meta.get("compose_text")
    service = meta.get("service") or ""
    if not compose_path or not Path(compose_path).is_file() or not service:
        if image_id and image_id != current_image_id:
            return False, "Data restored; the app version was not changed (compose file unknown)."
        return False, ""

    current_text = Path(compose_path).read_text(encoding="utf-8")
    compose_differs = compose_text is not None and compose_text != current_text
    image_differs = bool(image_id) and image_id != current_image_id
    if not compose_differs and not image_differs:
        return False, ""

    notes: list[str] = []
    if image_differs:
        repo, tag = _split_ref(image_ref)
        try:
            if not repo:
                raise ValueError("pinned by digest")
            client.images.get(image_id).tag(repo, tag=tag)
            notes.append(f"previous version {meta.get('version') or image_ref} restored")
        except Exception:
            if not compose_differs:
                return False, "Data restored, but the previous app version's image is no longer on this server."
            notes.append("previous image is no longer on this server")
    if compose_differs:
        path = Path(compose_path)
        path.with_name(path.name + ".bak").write_text(current_text, encoding="utf-8")
        path.write_text(compose_text, encoding="utf-8")
        notes.append("docker-compose.yml restored (current file saved as .bak)")
    elif image_differs and _set_compose_image(compose_path, service, image_ref):
        notes.append("compose image reverted (previous file saved as .bak)")

    proc = subprocess.run(
        ["docker", "compose", "-f", compose_path, "up", "-d", "--force-recreate", "--no-deps", service],
        cwd=str(Path(compose_path).parent), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(f"Data restored, but recreating the container failed: {tail}")
    msg = "; ".join(notes)
    return True, (msg[:1].upper() + msg[1:] + ".") if msg else ""


def _safe_members(tar: tarfile.TarFile, root: Path) -> list[tarfile.TarInfo]:
    """Bản sao lưu do chính app tạo -> giữ quyền & chủ sở hữu, nhưng chặn đường dẫn thoát ra ngoài."""
    root = root.resolve()
    members = tar.getmembers()
    for m in members:
        target = (root / m.name).resolve() if not m.issym() else (root / m.name).parent.resolve()
        if m.name.startswith("/") or (target != root and root not in target.parents):
            raise ValueError(f"Unsafe path in backup: {m.name}")
        if m.islnk() and m.linkname.startswith("/"):
            raise ValueError(f"Unsafe link in backup: {m.name}")
    return members


def _extract(tar: tarfile.TarFile, dest: Path, members: list[tarfile.TarInfo]) -> None:
    try:
        tar.extractall(dest, members=members, numeric_owner=True, filter="fully_trusted")
    except TypeError:  # Python cũ không có tham số filter
        tar.extractall(dest, members=members, numeric_owner=True)


def _restore_whole_folder(f: Path, dest: Path, previous: Path) -> None:
    if previous.exists():
        shutil.rmtree(previous)
    if dest.exists():
        dest.rename(previous)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(f, "r:gz") as tar:
            _extract(tar, dest, _safe_members(tar, dest))
    except Exception:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        if previous.exists():
            previous.rename(dest)
        raise


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))


def _restore_selected(f: Path, dest: Path, previous: Path, meta: dict[str, Any]) -> None:
    """
    Chỉ thay các file thuộc diện sao lưu. File hiện có sẽ bị ghi đè, và file thuộc diện sao lưu nhưng không có
    trong bản sao lưu (sinh ra sau đó, vd bản mới tạo thêm), được chuyển sang <dir>.pre-restore.
    Media / file lớn / thư mục bị bỏ qua và FILE LOG hiện có thì giữ nguyên.
    """
    roots = list(meta.get("roots") or [])
    file_max = int(meta.get("file_max_bytes") or DEFAULT_FILE_MAX_MB * 1024 * 1024)
    if previous.exists():
        shutil.rmtree(previous)
    previous.mkdir(parents=True)
    moved: list[tuple[Path, Path]] = []
    with tarfile.open(f, "r:gz") as tar:
        members = _safe_members(tar, dest)
        in_backup = {os.path.normpath(m.name) for m in members if not m.isdir()}
        try:
            # 1) File hiện tại thuộc diện sao lưu: chuyển sang pre-restore (sẽ được thay bằng bản trong sao lưu)
            current = [
                (p, os.path.normpath(rel)) for p, rel, is_dir in _walk_wanted(dest, roots, file_max)
                if not is_dir and not _is_log(rel)
            ]
            for p, rel in current:
                if p.exists() or p.is_symlink():
                    _move(p, previous / rel)
                    moved.append((previous / rel, p))
            # 2) File trong sao lưu mà hiện có ở chỗ khác diện (vd đã lớn hơn giới hạn): cũng giữ lại bản hiện tại
            keep_logs = set()
            for rel in in_backup:
                p = dest / rel
                if (p.exists() or p.is_symlink()) and not p.is_dir():
                    if _is_log(rel):
                        keep_logs.add(rel)  # log hiện có -> giữ nguyên, không lấy bản cũ
                        continue
                    _move(p, previous / rel)
                    moved.append((previous / rel, p))
            _extract(tar, dest, [m for m in members if os.path.normpath(m.name) not in keep_logs])
        except Exception:
            for saved, original in reversed(moved):  # hoàn tác: trả file về chỗ cũ
                try:
                    _move(saved, original)
                except Exception:
                    pass
            raise


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
        if meta.get("roots") is not None:
            _restore_selected(f, dest, previous, meta)
        else:
            _restore_whole_folder(f, dest, previous)  # bản sao lưu cũ: cả thư mục
    except Exception as exc:
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
