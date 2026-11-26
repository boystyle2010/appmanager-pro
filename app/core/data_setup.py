"""
Thiết lập thư mục Data App cho người dùng mới.

AppManager đọc docker-compose.yml và file cài đặt của các app theo ĐÚNG đường dẫn trên host (nhãn của Docker
Compose ghi đường dẫn host), nên các thư mục đó phải được mount vào AppManager với cùng đường dẫn
(vd /DATA/AppData:/DATA/AppData). Module này:
  - kiểm tra app nào AppManager chưa đọc được compose (chưa mount),
  - quét tìm thư mục Data: nhanh qua nhãn Docker, sâu bằng container phụ đọc ổ đĩa host (chỉ đọc),
  - thêm thư mục người dùng xác nhận vào docker-compose.yml của AppManager rồi tạo lại AppManager bằng
    container phụ (cùng cơ chế tự cập nhật: kiểm tra sức khoẻ, hỏng thì trả compose cũ).
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
import threading
import time
from pathlib import Path
from typing import Any

import re

from app.core.docker_client import APPDATA_DIR, get_docker_client, portainer_compose_root, translate_portainer_path

logger = logging.getLogger(__name__)

COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
# Thư mục hệ thống: không bao giờ đề xuất / cho phép mount
FORBIDDEN = {
    "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/proc", "/root", "/run",
    "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var", "/var/run", "/var/lib", "/var/lib/docker", "/var/log",
    "/home", "/opt", "/mnt", "/media", "/DATA", "/snap",
}
FORBIDDEN_PREFIXES = ("/proc/", "/sys/", "/dev/", "/run/", "/var/run/", "/var/lib/docker/", "/var/lib/containerd/",
                      "/boot/", "/usr/", "/bin/", "/sbin/", "/lib/", "/etc/")
SCAN_HELPER_NAME = "appmanager-pro-data-scan"
SCAN_TIMEOUT = 600

# Script chạy trong container phụ: host "/" được mount chỉ đọc vào /host. Tìm file compose, bỏ qua thư mục
# hệ thống / dữ liệu lớn quen thuộc, giới hạn độ sâu. In JSON danh sách đường dẫn (theo host).
_SCAN_SCRIPT = r"""
import json, os, sys
ROOT = "/host"
NAMES = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
SKIP_TOP = {"proc", "sys", "dev", "run", "boot", "usr", "bin", "sbin", "lib", "lib32", "lib64", "libx32",
            "snap", "tmp", "lost+found", "etc"}
SKIP_ANY = {"node_modules", ".git", ".cache", "cache", "Cache", "__pycache__", "overlay2", "containerd",
            "Trash", ".Trash", ".recycle", "@eaDir", "#recycle", "Photos", "Movies", "Music", "Videos",
            "Downloads", "media", "Media", "thumbnails", "transcodes"}
SKIP_PATHS = {"/var/lib/docker", "/var/lib/containerd", "/var/log", "/var/cache", "/var/tmp", "/var/run"}
MAX_DEPTH = int(sys.argv[1]) if len(sys.argv) > 1 else 6
found = []
def walk(path, rel, depth):
    try:
        it = os.scandir(path)
    except Exception:
        return
    with it:
        for e in it:
            try:
                if e.is_symlink():
                    continue
                if e.is_file() and e.name in NAMES:
                    found.append(rel + "/" + e.name)
                elif e.is_dir() and depth < MAX_DEPTH:
                    r = rel + "/" + e.name
                    if (depth == 0 and e.name in SKIP_TOP) or e.name in SKIP_ANY or r in SKIP_PATHS:
                        continue
                    walk(e.path, r, depth + 1)
            except Exception:
                continue
walk(ROOT, "", 0)
print(json.dumps(found[:5000]))
"""

_scan_lock = threading.Lock()
_scan_state: dict[str, Any] = {"running": False, "started": 0, "finished": 0, "candidates": [], "error": ""}


# ---------------------------------------------------------------- tiện ích đường dẫn
def normalize_host_path(path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/") or "\x00" in p or len(p) > 400:
        return ""
    p = posixpath.normpath(p)
    if p.startswith("//"):
        p = "/" + p.lstrip("/")
    return p


def path_allowed(path: str) -> tuple[bool, str]:
    p = normalize_host_path(path)
    if not p:
        return False, "Enter an absolute host path, e.g. /DATA/AppData"
    if any(part in ("..",) for part in p.split("/")):
        return False, "The path must not contain '..'"
    # Ngoại lệ: thư mục stack của Portainer trong volume dữ liệu của nó (vd /var/lib/docker/volumes/portainer_data/_data/compose)
    if re.match(r"^/var/lib/docker/volumes/[A-Za-z0-9][A-Za-z0-9_.-]*/_data/compose(/.*)?$", p):
        return True, p
    if p in FORBIDDEN or any(p.startswith(x) for x in FORBIDDEN_PREFIXES):
        return False, f"{p} is a system folder or too broad; choose the folder that holds your apps' data"
    if "docker.sock" in p:
        return False, "This path cannot be mounted"
    return True, p


def _covers(parent: str, child: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def _own_container(client):
    import socket

    try:
        return client.containers.get(socket.gethostname())
    except Exception:
        return client.containers.get("appmanager-pro")


def _own_mount_paths(own) -> list[str]:
    """Các đường dẫn host được mount vào AppManager với CÙNG đường dẫn (cách AppManager đọc compose của app)."""
    out = []
    for m in own.attrs.get("Mounts") or []:
        src, dst = m.get("Source") or "", m.get("Destination") or ""
        if m.get("Type") == "bind" and src and src == dst:
            out.append(src)
    return out


def _compose_apps(client, own_id: str) -> list[dict[str, str]]:
    """Mọi container do Docker Compose tạo (trừ AppManager): tên, thư mục làm việc, file compose (đường dẫn host)."""
    apps = []
    containers = client.containers.list(all=True)
    proot = portainer_compose_root(containers)
    for c in containers:
        if c.id == own_id:
            continue
        labels = (c.attrs.get("Config") or {}).get("Labels") or {}
        wd = translate_portainer_path(labels.get("com.docker.compose.project.working_dir") or "", proot)
        cfg = translate_portainer_path((labels.get("com.docker.compose.project.config_files") or "").split(",")[0].strip(), proot)
        if not wd and not cfg:
            continue
        apps.append({"name": c.name, "working_dir": wd or str(Path(cfg).parent), "config": cfg})
    return apps


def _readable(app: dict[str, str]) -> bool:
    if app["config"] and Path(app["config"]).is_file():
        return True
    wd = Path(app["working_dir"])
    return any((wd / n).is_file() for n in COMPOSE_NAMES)


# ---------------------------------------------------------------- trạng thái
def data_status() -> dict[str, Any]:
    """App nào AppManager chưa đọc được compose (chưa mount thư mục Data) + AppManager có tự sửa compose được không."""
    try:
        client = get_docker_client()
        own = _own_container(client)
    except Exception as exc:
        return {"available": False, "needs_setup": False, "reason": f"Not running in Docker ({exc})"}
    labels = (own.attrs.get("Config") or {}).get("Labels") or {}
    own_cfg = (labels.get("com.docker.compose.project.config_files") or "").split(",")[0].strip()
    apps = _compose_apps(client, own.id)
    missing = [a for a in apps if not _readable(a)]
    folders = data_folders(own, apps)
    return {
        "available": True,
        "needs_setup": bool(missing),
        "mounted": [f["path"] for f in folders],
        "folders": folders,
        "missing_apps": [a["name"] for a in missing][:50],
        "missing_count": len(missing),
        "total_apps": len(apps),
        "own_compose": own_cfg,
        "can_apply": bool(own_cfg),
    }


def _is_data_mount(path: str) -> bool:
    """Thư mục dữ liệu = mount cùng đường dẫn, là thư mục (bỏ docker.sock, file lẻ) và không phải thư mục hệ thống."""
    if "docker.sock" in path or not Path(path).is_dir():
        return False
    return path_allowed(path)[0] or path.startswith("/var/lib/casaos")


def data_folders(own, apps: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Các thư mục dữ liệu đang mount vào AppManager + app (compose) nằm trong mỗi thư mục."""
    labels = (own.attrs.get("Config") or {}).get("Labels") or {}
    own_cfg = (labels.get("com.docker.compose.project.config_files") or "").split(",")[0].strip()
    out = []
    for p in _own_mount_paths(own):
        if not _is_data_mount(p):
            continue
        names = sorted({a["name"] for a in (apps or []) if _covers(p, a["working_dir"])})
        out.append({
            "path": p,
            "apps": names[:50],
            "app_count": len(names),
            "casaos": p.startswith("/var/lib/casaos"),
            "backup_root": _covers(p, str(APPDATA_DIR)) or _covers(str(APPDATA_DIR), p),
            "has_self": bool(own_cfg) and _covers(p, own_cfg),
        })
    return out


def _suggest_roots(compose_dirs: list[str], mounted: list[str]) -> list[dict[str, Any]]:
    """Gom thư mục chứa compose thành thư mục Data gốc: thư mục cha chung (vd /DATA/AppData) nếu hợp lệ."""
    groups: dict[str, set[str]] = {}
    for d in compose_dirs:
        d = normalize_host_path(d)
        if not d:
            continue
        parent = posixpath.dirname(d)
        root = parent if path_allowed(parent)[0] else d
        if re.match(r"^/var/lib/docker/volumes/[^/]+/_data/compose/", d + "/") and not d.endswith("/compose"):
            root = parent  # .../_data/compose/<id> -> .../_data/compose
        if not path_allowed(root)[0]:
            continue
        groups.setdefault(root, set()).add(d)
    roots = sorted(groups, key=len)
    out: list[dict[str, Any]] = []
    for r in roots:
        if any(_covers(o["path"], r) for o in out):
            parent = next(o for o in out if _covers(o["path"], r))
            parent["apps"] = sorted(set(parent["apps"]) | groups[r])
            continue
        out.append({"path": r, "apps": sorted(groups[r])})
    for o in out:
        o["mounted"] = any(_covers(m, o["path"]) for m in mounted)
        o["count"] = len(o["apps"])
        o["apps"] = [posixpath.basename(a) for a in o["apps"]][:12]
    return sorted(out, key=lambda o: (o["mounted"], -o["count"], o["path"]))


def quick_candidates() -> list[dict[str, Any]]:
    client = get_docker_client()
    own = _own_container(client)
    apps = _compose_apps(client, own.id)
    cands = _suggest_roots([a["working_dir"] for a in apps], _own_mount_paths(own))
    running = {posixpath.basename(a["working_dir"]) for a in apps}
    for c in cands:
        c["running"] = sum(1 for a in c["apps"] if a in running)
    return cands


# ---------------------------------------------------------------- quét sâu bằng container phụ
def _run_helper(script_args: list[str], timeout: int) -> str:
    client = get_docker_client()
    own = _own_container(client)
    try:
        client.containers.get(SCAN_HELPER_NAME).remove(force=True)
    except Exception:
        pass
    c = client.containers.run(
        image=own.image.id, command=["python", "-c", _SCAN_SCRIPT, *script_args], name=SCAN_HELPER_NAME,
        volumes={"/": {"bind": "/host", "mode": "ro"}}, network_mode="none", detach=True,
        labels={"appmanager-pro.helper": "data-scan"},
    )
    try:
        res = c.wait(timeout=timeout)
        out = c.logs(stdout=True, stderr=False).decode("utf-8", errors="replace").strip()
        if (res or {}).get("StatusCode", 1) != 0:
            err = c.logs(stdout=False, stderr=True).decode("utf-8", errors="replace").strip()
            raise RuntimeError(err[-300:] or "scan helper failed")
        return out
    finally:
        try:
            c.remove(force=True)
        except Exception:
            pass


def _deep_scan_worker() -> None:
    try:
        quick = quick_candidates()
        out = _run_helper(["6"], SCAN_TIMEOUT)
        files = json.loads(out.splitlines()[-1]) if out else []
        dirs = [posixpath.dirname(f) for f in files]
        client = get_docker_client()
        own = _own_container(client)
        mounted = _own_mount_paths(own)
        deep = _suggest_roots(dirs, mounted)
        running = {posixpath.basename(a["working_dir"]) for a in _compose_apps(client, own.id)}
        by_path = {c["path"]: c for c in quick}
        for d in deep:
            d["running"] = sum(1 for a in d["apps"] if a in running)
            if d["path"] in by_path:
                q = by_path[d["path"]]
                d["count"] = max(d["count"], q["count"])
                d["running"] = max(d["running"], q["running"])
        merged = {c["path"]: c for c in quick}
        for d in deep:
            merged[d["path"]] = d
        # bỏ ứng viên nằm trong ứng viên khác
        paths = sorted(merged, key=len)
        final = []
        for p in paths:
            if any(_covers(f["path"], p) for f in final):
                continue
            final.append(merged[p])
        final.sort(key=lambda o: (o["mounted"], -o.get("running", 0), -o["count"], o["path"]))
        _scan_state.update(candidates=final[:30], error="")
    except Exception as exc:
        logger.exception("Data folder scan failed")
        _scan_state.update(error=str(exc)[:300])
    finally:
        _scan_state.update(running=False, finished=int(time.time()))


def start_deep_scan() -> dict[str, Any]:
    with _scan_lock:
        if _scan_state["running"]:
            return scan_state()
        _scan_state.update(running=True, started=int(time.time()), finished=0, candidates=[], error="")
        threading.Thread(target=_deep_scan_worker, daemon=True, name="data-scan").start()
    return scan_state()


def scan_state() -> dict[str, Any]:
    st = dict(_scan_state)
    st["elapsed"] = int((st["finished"] or time.time()) - st["started"]) if st["started"] else 0
    return st


# ---------------------------------------------------------------- kiểm tra đường dẫn nhập tay
_CHECK_SCRIPT = r"""
import json, os, sys
p = "/host" + sys.argv[1]
res = {"exists": os.path.isdir(p), "compose": 0, "apps": []}
if res["exists"]:
    try:
        for e in sorted(os.scandir(p), key=lambda x: x.name)[:2000]:
            if e.is_dir(follow_symlinks=False):
                if any(os.path.isfile(os.path.join(e.path, n)) for n in
                       ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")):
                    res["compose"] += 1
                    res["apps"].append(e.name)
            elif e.name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                res["compose"] += 1
    except Exception:
        pass
res["apps"] = res["apps"][:12]
print(json.dumps(res))
"""


def check_path(path: str) -> dict[str, Any]:
    ok, p = path_allowed(path)
    if not ok:
        return {"ok": False, "error": p}
    client = get_docker_client()
    own = _own_container(client)
    try:
        client.containers.get(SCAN_HELPER_NAME).remove(force=True)
    except Exception:
        pass
    c = client.containers.run(
        image=own.image.id, command=["python", "-c", _CHECK_SCRIPT, p], name=SCAN_HELPER_NAME,
        volumes={"/": {"bind": "/host", "mode": "ro"}}, network_mode="none", detach=True,
        labels={"appmanager-pro.helper": "data-scan"},
    )
    try:
        c.wait(timeout=60)
        info = json.loads(c.logs(stdout=True, stderr=False).decode("utf-8", errors="replace").strip().splitlines()[-1])
    finally:
        try:
            c.remove(force=True)
        except Exception:
            pass
    if not info.get("exists"):
        return {"ok": False, "error": f"{p} does not exist on the host"}
    mounted = _own_mount_paths(own)
    covers = sorted({a["name"] for a in _compose_apps(client, own.id) if _covers(p, a["working_dir"])})
    return {"ok": True, "path": p, "count": info.get("compose", 0), "apps": info.get("apps", []),
            "mounted": any(_covers(m, p) for m in mounted), "covers_apps": covers}


# ---------------------------------------------------------------- thêm vào compose của AppManager
def apply_paths(paths: list[str]) -> dict[str, Any]:
    """Ghi việc cần làm cho container phụ: thêm volume <p>:<p> vào compose của AppManager rồi tạo lại."""
    from app.core.updater import _trigger_self_update_helper

    clean: list[str] = []
    for raw in paths or []:
        ok, p = path_allowed(raw)
        if not ok:
            raise ValueError(p)
        if p not in clean:
            clean.append(p)
    if not clean or len(clean) > 10:
        raise ValueError("Choose 1 to 10 folders")
    st = data_status()
    if not st.get("can_apply"):
        raise ValueError("AppManager was not started with Docker Compose; add the volume to its run command manually")
    mounted = st.get("mounted") or []
    new = [p for p in clean if not any(_covers(m, p) for m in mounted)]
    if not new:
        raise ValueError("These folders are already mounted")
    env: dict[str, str] = {}
    # Thư mục Data mặc định (/DATA/AppData) không có trên máy này -> dùng thư mục đầu tiên cho sao lưu app
    if not any(_covers(m, str(APPDATA_DIR)) for m in mounted) and not Path(str(APPDATA_DIR)).is_dir():
        env["APPDATA_DIR"] = new[0]
    _trigger_self_update_helper(
        st["own_compose"], mode="recreate", title="AppManager Pro", history_mode="data_setup",
        compose_original=None, extra_job={"add_volumes": new, "set_env": env},
    )
    return {"ok": True, "added": new, "env": env}


def update_paths(add: list[str], remove: list[str]) -> dict[str, Any]:
    """Sửa / gỡ thư mục dữ liệu đã thêm: bỏ volume <p>:<p> cũ, thêm volume mới, tạo lại AppManager (container phụ)."""
    from app.core.updater import _trigger_self_update_helper

    st = data_status()
    if not st.get("available"):
        raise ValueError(st.get("reason") or "AppManager is not running in Docker")
    if not st.get("can_apply"):
        raise ValueError("AppManager was not started with Docker Compose; change the volume in its run command manually")
    current = [f["path"] for f in st.get("folders") or []]
    rem: list[str] = []
    for raw in remove or []:
        p = normalize_host_path(raw)
        if p not in current:
            raise ValueError(f"{raw} is not a data folder of AppManager")
        if p not in rem:
            rem.append(p)
    new: list[str] = []
    for raw in add or []:
        ok, p = path_allowed(raw)
        if not ok:
            raise ValueError(p)
        if p not in new and p not in rem:
            new.append(p)
    keep = [p for p in current if p not in rem]
    new = [p for p in new if not any(_covers(m, p) for m in keep)]
    if not rem and not new:
        raise ValueError("Nothing to change")
    if len(new) > 10:
        raise ValueError("Choose 1 to 10 folders")
    # AppManager phải luôn đọc được docker-compose.yml của chính nó (để sửa / cập nhật / trả lại khi lỗi)
    own_cfg = st.get("own_compose") or ""
    if any(_covers(p, own_cfg) for p in rem) and not any(_covers(p, own_cfg) for p in keep + new):
        raise ValueError(f"AppManager's own docker-compose.yml ({own_cfg}) is in this folder; the new folder must still contain it")
    env: dict[str, str] = {}
    appdata = str(APPDATA_DIR)
    # Thư mục dùng cho sao lưu app (APPDATA_DIR) không còn được mount -> trỏ sang thư mục mới
    if any(_covers(p, appdata) for p in rem) and not any(_covers(p, appdata) for p in keep + new):
        target = new[0] if new else (keep[0] if keep else "")
        if target:
            env["APPDATA_DIR"] = target
    lost = sorted({a for f in st.get("folders") or [] if f["path"] in rem for a in f["apps"]})
    _trigger_self_update_helper(
        st["own_compose"], mode="recreate", title="AppManager Pro", history_mode="data_setup",
        compose_original=None, extra_job={"add_volumes": new, "remove_volumes": rem, "set_env": env},
    )
    return {"ok": True, "added": new, "removed": rem, "env": env, "apps": lost}


def dismissed_key() -> str:
    return "data_setup_dismissed"


def env_flag() -> bool:
    return os.getenv("DATA_SETUP_PROMPT", "true").lower() != "false"
