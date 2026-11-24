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
from app.core.docker_client import APPDATA_DIR, compose_cmd, get_docker_client

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
    image_digest: str = "",
    compose_path: str = "",
    service: str = "",
    compose_text: str | None = None,
) -> dict[str, Any]:
    # Luôn tạo bản sao lưu: tối thiểu là PHIÊN BẢN (image + digest) + docker-compose.yml để khôi phục được,
    # kể cả app không có thư mục cấu hình trong /DATA/AppData (vd cloudflared chỉ có biến môi trường).
    note = ""
    roots: list[str] = []
    skipped_mounts: list[str] = []
    skipped: list[str] = []
    entries: list[tuple[Path, str, bool]] = []
    files: list[tuple[Path, str, bool]] = []
    size = 0
    file_max = max(1, int(file_max_mb)) * 1024 * 1024
    src = Path(source_dir) if source_dir else None
    if src is None:
        note = "no config folder in " + str(APPDATA_DIR)
    elif not src.is_dir() or not _inside(src, APPDATA_DIR):
        note = f"data folder is not inside {APPDATA_DIR}"
        src = None
    elif _inside(BACKUP_ROOT, src) or src.resolve() == DATA_DIR.resolve() or _inside(DATA_DIR, src):
        note = "AppManager Pro's own data is not archived"
        src = None
    if src is not None:
        roots, skipped_mounts = plan_backup_roots(src, mounts or [])
        limit = max(1, int(max_mb)) * 1024 * 1024
        walked = list(_walk_wanted(src, roots, file_max, skipped)) if roots else []
        files = [(p, rel, d) for p, rel, d in walked if not d]
        # Chỉ giữ thư mục cha của file được sao lưu (giữ quyền/chủ sở hữu), không lưu cả cây thư mục rỗng
        needed_dirs: set[str] = set()
        for _p, rel, _d in files:
            parent = Path(rel).parent
            while str(parent) not in ("", "."):
                needed_dirs.add(os.path.normpath(str(parent)))
                parent = parent.parent
        entries = [(p, rel, d) for p, rel, d in walked if d and os.path.normpath(rel) in needed_dirs] + files
        for p, _rel, is_dir in entries:
            if not is_dir and not p.is_symlink():
                try:
                    size += p.stat().st_size
                except OSError:
                    pass
        if size > limit:
            note = f"config files ({format_bytes(size)}) exceed {max_mb} MB — not archived"
            entries, files, size = [], [], 0
        elif not files:
            note = "no config files found"
    if not files:
        roots = []  # bản chỉ có phiên bản: khôi phục không đụng tới file nào

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
            "source": str(src) if (src is not None and files) else "", "version": version, "version_only": not files, "created": int(time.time()), "data_bytes": size,
            "roots": roots, "file_max_bytes": file_max, "skipped_mounts": skipped_mounts,
            "skipped": skipped[:200], "skipped_count": len(skipped),
            "image_id": image_id, "image_ref": image_ref, "image_digest": image_digest,
            "compose_path": compose_path, "service": service, "compose_text": compose_text,
        }),
        encoding="utf-8",
    )
    _apply_retention(bdir, keep)
    return {
        "ok": True, "file": name, "size": format_bytes(target.stat().st_size),
        "message": (f"Backup saved: {name} ({len(files)} settings file(s), {format_bytes(size)})" if files
                    else f"Backup saved: {name} (image + docker-compose.yml only; {note})"),
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


def _image_exists(client, ref: str) -> str:
    try:
        return client.images.get(ref).id
    except Exception:
        return ""


def _pull_previous_image(client, meta: dict[str, Any], log: list[str]) -> str:
    """
    Image cũ đã bị xoá (vd "Tự xoá image cũ sau khi update") -> tải lại từ registry.
    Thứ tự: đúng digest đã lưu lúc sao lưu (chính xác tuyệt đối) -> tag theo phiên bản (bản sao lưu cũ chưa có digest).
    Trả về image id, hoặc "" nếu không tải được.
    """
    repo, _tag = _split_ref(meta.get("image_ref") or "")
    if not repo:
        return ""
    candidates: list[str] = []
    if meta.get("image_digest"):
        candidates.append(f"{repo}@{meta['image_digest']}")
    version = str(meta.get("version") or "").strip()
    if version and re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", version) and not version.startswith("build-"):
        candidates.append(f"{repo}:{version}")
        if not version.startswith("v"):
            candidates.append(f"{repo}:v{version}")
    for ref in candidates:
        log.append(f"Pulling {ref} ...")
        try:
            proc = subprocess.run(["docker", "pull", ref], capture_output=True, text=True, timeout=900)
        except Exception as exc:
            log.append(f"  failed: {exc}")
            continue
        if proc.returncode == 0:
            image_id = _image_exists(client, ref)
            if image_id:
                log.append(f"  OK ({image_id[:19]})")
                return image_id
        log.append(f"  failed: {((proc.stderr or proc.stdout or '').strip().splitlines() or ['?'])[-1][:200]}")
    return ""


def _restore_version(client, meta: dict[str, Any], current_image_id: str, log: list[str]) -> tuple[bool, str]:
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
            return False, "Image was not changed: docker-compose.yml of the app is unknown."
        return False, ""

    current_text = Path(compose_path).read_text(encoding="utf-8")
    compose_differs = compose_text is not None and compose_text != current_text
    image_differs = bool(image_id) and image_id != current_image_id
    if not compose_differs and not image_differs:
        log.append("Image and docker-compose.yml already match the backup.")
        return False, ""

    notes: list[str] = []
    if image_differs:
        repo, tag = _split_ref(image_ref)
        version = meta.get("version") or image_ref
        source_id = image_id if _image_exists(client, image_id) else ""
        if not source_id:
            log.append(f"Image {image_id[:19]} ({version}) is not on this host.")
            source_id = _pull_previous_image(client, meta, log)
        if source_id and repo:
            client.images.get(source_id).tag(repo, tag=tag)
            log.append(f"Tagged {source_id[:19]} as {repo}:{tag}")
            notes.append(f"image {version} restored")
        elif not compose_differs:
            log.append("Previous image could not be restored.")
            return False, f"Image {version} is not available (removed from host and not pullable from the registry)."
        else:
            notes.append(f"image {version} unavailable")
    if compose_differs:
        path = Path(compose_path)
        path.with_name(path.name + ".bak").write_text(current_text, encoding="utf-8")
        path.write_text(compose_text, encoding="utf-8")
        log.append("docker-compose.yml restored (current file saved as .bak)")
        notes.append("docker-compose.yml restored")
    elif image_differs and _set_compose_image(compose_path, service, image_ref):
        log.append("Image reference in docker-compose.yml reverted (previous file saved as .bak)")

    log.append(f"$ docker compose -f {compose_path} up -d --force-recreate --no-deps {service}")
    proc = subprocess.run(
        [*compose_cmd(compose_path), "up", "-d", "--force-recreate", "--no-deps", service],
        cwd=str(Path(compose_path).parent), capture_output=True, text=True, timeout=600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if out.strip():
        log.append(out.strip()[-1500:])
    if proc.returncode != 0:
        raise RuntimeError(f"Recreating the container failed (exit {proc.returncode}).")
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
    Kết quả có "log": các bước đã làm (hiện trong giao diện).
    """
    log: list[str] = []
    f = _backup_file(container_name, filename)
    try:
        meta = json.loads(Path(str(f) + ".json").read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "Backup metadata is missing"}
    version_only = not meta.get("source")
    dest = Path(meta.get("source") or "")
    if not version_only and not _inside(dest, APPDATA_DIR):
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
            log.append(f"Stopping container {container_name} ...")
            container.stop(timeout=30)
    except Exception:
        container = None

    previous = dest.with_name(dest.name + ".pre-restore") if not version_only else dest
    if version_only:
        log.append("Backup contains image + docker-compose.yml only (no config files to restore).")
    else:
        log.append(f"Restoring config files from {filename} into {dest} ...")
    try:
        if version_only:
            pass
        elif meta.get("roots") is not None:
            _restore_selected(f, dest, previous, meta)
        else:
            _restore_whole_folder(f, dest, previous)  # bản sao lưu cũ: cả thư mục
    except Exception as exc:
        if container is not None and was_running and start:
            try:
                container.start()
            except Exception:
                pass
        log.append(f"[ERROR] {exc}")
        return {"ok": False, "error": f"Restore failed: {exc}", "log": log}

    if not version_only:
        log.append(f"Config files restored. Replaced files kept in {previous.name}.")
    base_msg = f"Restored from {filename}." if version_only else f"Config files restored from {filename}."
    if not start:
        return {"ok": True, "message": base_msg, "log": log}
    version_note = ""
    if restore_version:
        try:
            recreated, version_note = _restore_version(client, meta, current_image_id, log)
        except Exception as exc:
            log.append(f"[ERROR] {exc}")
            return {"ok": True, "warning": f"{base_msg} {exc}", "log": log}
        if recreated:
            log.append("Container recreated.")
            return {"ok": True, "message": f"{base_msg} {version_note}".strip(), "log": log}
    if container is not None:
        # Sau khi khôi phục luôn chạy lại app (kể cả khi trước đó nó đã dừng vì lỗi)
        log.append(f"Starting container {container_name} ...")
        try:
            container.start()
        except Exception as exc:
            log.append(f"[ERROR] {exc}")
            return {"ok": True, "warning": f"{base_msg} Container failed to start: {exc}", "log": log}
    if version_note:
        return {"ok": True, "warning": f"{base_msg} {version_note}", "log": log}
    return {"ok": True, "message": base_msg, "log": log}
