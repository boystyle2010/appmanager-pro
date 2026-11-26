import os
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import docker
from docker.errors import DockerException, NotFound
from ruamel.yaml import YAML

from app.core.database import get_all_app_prefs, get_all_update_cache

APP_VERSION = "0.18.3"
CASAOS_APPS_DIR = Path(os.getenv("CASAOS_APPS_DIR", "/var/lib/casaos/apps"))
APPDATA_DIR = Path(os.getenv("APPDATA_DIR", "/DATA/AppData"))
yaml_parser = YAML(typ="safe")


def get_docker_client() -> docker.DockerClient:
    return docker.from_env()


def _extract_localized_str(val: Any, fallback: str = "") -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return (
            val.get("en_US")
            or val.get("en_us")
            or val.get("vi_VN")
            or next(iter(val.values()), fallback)
        )
    return fallback


def _github_from_icon_or_meta(x_casaos: dict[str, Any]) -> str:
    for key in ("project_url", "source", "repository", "homepage"):
        val = str(x_casaos.get(key) or "").strip()
        if "github.com/" in val:
            return val
    icon_url = str(x_casaos.get("icon") or "")
    m = re.search(r"raw\.githubusercontent\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", icon_url)
    if m:
        return f"https://github.com/{m.group(1)}"
    return ""


def load_casaos_metadata() -> dict[str, dict[str, Any]]:
    apps_meta: dict[str, dict[str, Any]] = {}
    if not CASAOS_APPS_DIR.exists() or not CASAOS_APPS_DIR.is_dir():
        return apps_meta

    for app_dir in CASAOS_APPS_DIR.iterdir():
        if not app_dir.is_dir():
            continue

        compose_file = app_dir / "docker-compose.yml"
        if not compose_file.exists():
            compose_file = app_dir / "docker-compose.yaml"
        if not compose_file.exists():
            continue

        try:
            with compose_file.open("r", encoding="utf-8") as f:
                data = yaml_parser.load(f) or {}
        except Exception:
            continue

        x_casaos = data.get("x-casaos") or {}
        project_name = str(data.get("name") or app_dir.name).lower()
        services = list((data.get("services") or {}).keys())

        meta = {
            "app_id": app_dir.name,
            "project_name": project_name,
            "compose_path": str(compose_file),
            "title": _extract_localized_str(x_casaos.get("title"), app_dir.name),
            "icon": x_casaos.get("icon") or "",
            "source_hint": _github_from_icon_or_meta(x_casaos),
            "port_map": str(x_casaos.get("port_map") or ""),
            "scheme": str(x_casaos.get("scheme") or "http"),
            "index": str(x_casaos.get("index") or "/"),
            "category": str(x_casaos.get("category") or "Other"),
            "main_service": str(x_casaos.get("main") or (services[0] if services else "")),
            "services": services,
        }

        apps_meta[app_dir.name.lower()] = meta
        apps_meta[project_name] = meta
        apps_meta[str(app_dir.resolve())] = meta

    return apps_meta


# Image hệ điều hành gốc gắn nhãn phiên bản của CHÍNH NÓ (vd ubuntu: org.opencontainers.image.version=24.04).
# Image ứng dụng build "FROM ubuntu" thừa hưởng nhãn đó -> không được hiểu là phiên bản của ứng dụng.
BASE_DISTRO_REFS = {"ubuntu", "debian", "alpine", "fedora", "centos", "rockylinux", "almalinux", "archlinux", "opensuse"}
_UBUNTU_RELEASE_RE = re.compile(r"^(1[4-9]|[2-3]\d)\.(04|10)$")  # 22.04, 24.04... = bản Ubuntu, không phải app
_DISTRO_VERSION_RE = re.compile(r"^\d{1,2}(\.\d{1,2})?$")
GENERIC_VERSIONS = {"", "unknown", "none", "latest", "main", "master", "edge", "stable", "dev", "nightly", "beta"}


def version_from_labels(labels: dict[str, str]) -> str:
    """Phiên bản thật của ứng dụng từ nhãn image; "" nếu không có (hoặc chỉ là nhãn của hệ điều hành gốc)."""
    base_ref = str(labels.get("org.opencontainers.image.ref.name") or "").strip().lower()
    for key in ("org.opencontainers.image.version", "build_version", "org.label-schema.version", "io.hass.version", "version"):
        val = str(labels.get(key) or "").strip()
        if not val or val.lower() in GENERIC_VERSIONS:
            continue
        if key == "org.opencontainers.image.version" and (
            (base_ref in BASE_DISTRO_REFS and _DISTRO_VERSION_RE.match(val)) or _UBUNTU_RELEASE_RE.match(val)
        ):
            continue
        return val
    return ""


def _parse_channels(raw: Any) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw) if raw else []
        return data if isinstance(data, list) else []
    except Exception:
        return []


def detect_real_version(image_tags: list[str], labels: dict[str, str], image_labels: dict[str, str]) -> str:
    val = version_from_labels({**image_labels, **labels})
    if val:
        return val
    if image_tags:
        return image_tags[0].split(":")[-1]
    return "latest"


def _extract_first_host_port(ports_dict: dict[str, Any]) -> str:
    if not ports_dict:
        return ""
    for bindings in ports_dict.values():
        if bindings and isinstance(bindings, list):
            host_port = bindings[0].get("HostPort")
            if host_port:
                return str(host_port)
    return ""


def _detect_appdata_path(mounts: list[dict[str, Any]], project: str, cname: str) -> str:
    try:
        base = APPDATA_DIR.resolve()
    except Exception:
        return ""

    for m in mounts or []:
        src = m.get("Source") or ""
        if not src:
            continue
        try:
            p = Path(src).resolve()
            if base in p.parents:
                rel = p.relative_to(base)
                top = base / rel.parts[0]
                if top.exists() and top.is_dir():
                    return str(top)
        except Exception:
            continue

    for cand in (project, cname):
        if cand:
            p = APPDATA_DIR / cand
            if p.exists() and p.is_dir():
                return str(p)
    return ""


def _parse_uptime(started_at: str, status: str) -> str:
    if status != "running" or not started_at or started_at.startswith("0001-01-01"):
        return ""
    try:
        clean = started_at.split(".")[0].replace("Z", "")
        dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h {mins % 60}m"
        days = hours // 24
        return f"{days}d {hours % 24}h"
    except Exception:
        return ""


def _extract_local_digests(container, image=None) -> list[str]:
    digests: list[str] = []
    try:
        repo_digests = (image or container.image).attrs.get("RepoDigests") or []
        for rd in repo_digests:
            if "@sha256:" in rd:
                digests.append("sha256:" + rd.split("@sha256:", 1)[1])
    except Exception:
        pass
    return digests


# ---------------- Portainer stacks ----------------
# Portainer lưu stack trong volume dữ liệu của nó (/data/compose/<id>/docker-compose.yml, đường dẫn BÊN TRONG
# container Portainer). Đổi sang đường dẫn trên host; AppManager đọc được khi thư mục đó được mount cùng đường dẫn.
PORTAINER_PREFIX = "/data/compose/"
# file compose (đường dẫn host) -> tên project thật: thư mục <id> khác tên stack nên luôn phải truyền -p
COMPOSE_PROJECTS: dict[str, str] = {}


def portainer_compose_root(containers) -> str:
    for c in containers:
        try:
            img = ((c.attrs.get("Config") or {}).get("Image") or "").lower()
            if "portainer/portainer" not in img and "portainer-ce" not in img and "portainer-ee" not in img:
                continue
            for m in c.attrs.get("Mounts") or []:
                if m.get("Destination") == "/data" and m.get("Source"):
                    return m["Source"].rstrip("/") + "/compose"
        except Exception:
            continue
    return ""


def translate_portainer_path(path: str, root: str) -> str:
    if root and path and (path + "/").startswith(PORTAINER_PREFIX):
        return root + "/" + path[len(PORTAINER_PREFIX):].strip("/")
    return path


def compose_cmd(compose_path: str) -> list[str]:
    """Lệnh docker compose cho một file; stack Portainer cần đúng tên project (-p) và file biến stack.env."""
    cmd = ["docker", "compose"]
    project = COMPOSE_PROJECTS.get(str(compose_path))
    if project:
        cmd += ["-p", project]
        env_file = Path(compose_path).parent / "stack.env"
        if env_file.is_file():
            cmd += ["--env-file", str(env_file)]
    return cmd + ["-f", str(compose_path)]


def compose_hint(working_dir: str, config_files: str, portainer_root: str) -> dict[str, str]:
    """Vì sao không dùng được compose của container + thư mục nên mount (để hiện trên thẻ app)."""
    if not working_dir and not config_files:
        return {"compose_issue": "not_compose", "compose_expected": "", "compose_mount": ""}
    expected = (config_files.split(",")[0].strip() if config_files else "") or working_dir
    if (expected + "/").startswith(PORTAINER_PREFIX):
        if not portainer_root:
            return {"compose_issue": "portainer", "compose_expected": expected, "compose_mount": ""}
        expected = translate_portainer_path(expected, portainer_root)
        return {"compose_issue": "not_mounted", "compose_expected": expected, "compose_mount": portainer_root}
    folder = working_dir or str(Path(expected).parent)
    parent = str(Path(folder).parent)
    mount = parent if parent.count("/") >= 2 else folder
    return {"compose_issue": "not_mounted", "compose_expected": expected, "compose_mount": mount}


def list_all_apps(include_cache: bool = True) -> dict[str, Any]:
    client = get_docker_client()
    casaos_meta_map = load_casaos_metadata()
    is_casaos_env = CASAOS_APPS_DIR.exists()
    cache_map = get_all_update_cache() if include_cache else {}
    prefs_map = get_all_app_prefs() if include_cache else {}
    own_hostname = socket.gethostname()

    containers = client.containers.list(all=True)
    items: list[dict[str, Any]] = []
    portainer_root = portainer_compose_root(containers)
    image_cache: dict[str, Any] = {}

    for c in containers:
        attrs = c.attrs or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        network_settings = attrs.get("NetworkSettings") or {}
        labels = config.get("Labels") or {}

        image_tags: list[str] = []
        image_labels: dict[str, str] = {}
        image_id = ""
        # Mỗi lần đọc c.image là một lần gọi API -> đọc mỗi image MỘT lần cho cả danh sách (nhiều container dùng chung)
        img_obj = image_cache.get(attrs.get("Image") or "")
        if img_obj is None and attrs.get("Image"):
            try:
                img_obj = client.images.get(attrs["Image"])
            except Exception:
                img_obj = False
            image_cache[attrs["Image"]] = img_obj
        if img_obj:
            image_tags = img_obj.tags or []
            image_labels = (img_obj.attrs.get("Config") or {}).get("Labels") or {}
            image_id = img_obj.id or ""

        image_ref = config.get("Image") or (image_tags[0] if image_tags else (img_obj.short_id if img_obj else ""))
        project = (labels.get("com.docker.compose.project") or "").lower()
        working_dir = labels.get("com.docker.compose.project.working_dir") or ""
        config_files = labels.get("com.docker.compose.project.config_files") or ""
        service = labels.get("com.docker.compose.service") or ""

        # Chỉ container do Docker Compose tạo mới được ghép với app CasaOS. Container docker run trùng tên với một app
        # CasaOS cũ (file còn sót trong /var/lib/casaos/apps) KHÔNG được coi là app compose đó (sẽ chạy nhầm file cũ).
        meta: Optional[dict[str, Any]] = (
            casaos_meta_map.get(working_dir)
            or casaos_meta_map.get(project)
            or casaos_meta_map.get(c.name.lower())
        ) if project else None

        is_self = (
            c.id.startswith(own_hostname)
            or c.short_id == own_hostname
            or c.name.lower() == "appmanager-pro"
        )

        source = "casaos" if meta else "docker"
        is_main = True if not meta else (not service or service == meta.get("main_service"))

        title = meta["title"] if (meta and is_main) else (
            f"{meta['title']} ({service})" if meta else c.name
        )
        icon = meta["icon"] if meta else ""

        if is_self:
            if not icon:
                icon = "/assets/icon.png"
            if title.lower() == "appmanager-pro":
                title = "AppManager Pro"

        port_map = (meta["port_map"] if (meta and is_main) else "") or _extract_first_host_port(
            network_settings.get("Ports") or {}
        )
        scheme = meta["scheme"] if meta else "http"
        index_path = meta["index"] if meta else "/"

        # Ưu tiên ĐÚNG file compose đã tạo ra container (nhãn của Docker Compose). Bản trong
        # /var/lib/casaos/apps chỉ dùng khi không đọc được file đó: một app chạy lại bằng terminal từ
        # thư mục khác (vd /DATA/AppData/<app>) vẫn trùng tên project với bản CasaOS cũ; dùng nhầm bản cũ
        # sẽ tạo lại container sai cấu hình (volume ./data trỏ chỗ khác, mật khẩu/biến cũ...) -> unhealthy.
        if portainer_root and ((working_dir + "/").startswith(PORTAINER_PREFIX) or config_files.startswith(PORTAINER_PREFIX)):
            working_dir = translate_portainer_path(working_dir, portainer_root)
            config_files = ",".join(translate_portainer_path(x.strip(), portainer_root) for x in config_files.split(",") if x.strip())
            portainer_stack = True
        else:
            portainer_stack = False
        compose_path = ""
        if config_files:
            first_cfg = config_files.split(",")[0].strip()
            if first_cfg and Path(first_cfg).is_file():
                compose_path = first_cfg
        if not compose_path and working_dir:
            for candidate in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                p = Path(working_dir) / candidate
                if p.is_file():
                    compose_path = str(p)
                    break
        if not compose_path and meta:
            compose_path = meta["compose_path"]
        if compose_path and portainer_stack and project:
            COMPOSE_PROJECTS[compose_path] = labels.get("com.docker.compose.project") or project
        from app.core.run_manager import manage_kind

        manage = manage_kind(labels)
        if manage == "helper" or c.name.endswith("-amp-old"):
            continue  # container phụ của AppManager / container cũ đang giữ tạm khi cập nhật: không hiện
        hint = {"compose_issue": "", "compose_expected": "", "compose_mount": ""}
        has_compose = bool(compose_path and Path(compose_path).exists())
        from app.core.run_manager import is_auto_remove

        if manage == "run" and not has_compose and is_auto_remove(attrs):
            manage = "external"  # --rm: Docker xoá container khi dừng -> không tạo lại an toàn được
            hint = {"compose_issue": "autoremove", "compose_expected": "", "compose_mount": ""}
        elif manage == "run" and not has_compose:
            pass  # quản lý trực tiếp (tạo lại container), không cần compose
        elif manage == "external":
            hint = {"compose_issue": "external", "compose_expected": "", "compose_mount": ""}
        elif not has_compose:
            hint = compose_hint(labels.get("com.docker.compose.project.working_dir") or "",
                                labels.get("com.docker.compose.project.config_files") or "", portainer_root)

        source_url = (
            image_labels.get("org.opencontainers.image.source")
            or image_labels.get("org.opencontainers.image.url")
            or labels.get("org.opencontainers.image.source")
            or (meta.get("source_hint") if meta else "")
            or ""
        )

        local_digests = _extract_local_digests(c, img_obj) if img_obj else []
        version = detect_real_version(image_tags, labels, image_labels)
        if is_self and version in ("latest", ""):
            version = f"v{APP_VERSION}"

        cached = cache_map.get(c.name, {})
        pref = prefs_map.get(c.name, {})
        # Tag chung (latest...): dùng phiên bản thật đã tra được trên registry cho ĐÚNG image đang chạy
        cached_ver = str(cached.get("current_version") or "")
        if (
            version.lower() in GENERIC_VERSIONS
            and cached_ver.lower() not in GENERIC_VERSIONS
            and not _UBUNTU_RELEASE_RE.match(cached_ver)  # giá trị cũ sai (nhãn Ubuntu) còn trong cache
            and local_digests
            and cached.get("local_digest") in local_digests
        ):
            version = cached_ver

        remote_digest = cached.get("remote_digest") or ""
        target_tag = cached.get("target_tag") or ""
        skip_token = remote_digest or target_tag
        cached_local_digest = cached.get("local_digest") or ""
        current_local_digest = local_digests[0] if local_digests else ""
        already_updated = bool(
            (remote_digest and remote_digest in local_digests)
            or (cached_local_digest and current_local_digest and cached_local_digest != current_local_digest)
        )
        raw_has_update = bool(cached.get("has_update")) and not already_updated
        is_skipped = bool(raw_has_update and skip_token and pref.get("skipped_digest") == skip_token)
        has_update = raw_has_update and not is_skipped

        appdata_path = _detect_appdata_path(attrs.get("Mounts") or [], project, c.name)
        status_str = state.get("Status") or c.status or "unknown"

        items.append(
            {
                "id": c.short_id,
                "full_id": c.id,
                "name": c.name,
                "title": title,
                "icon": icon,
                "source": source,
                "category": meta["category"] if meta else "Docker",
                "status": status_str,
                "uptime": _parse_uptime(state.get("StartedAt", ""), status_str),
                "image": image_ref,
                "image_id": image_id,
                "version": version,
                "local_digests": local_digests,
                "port_map": port_map,
                "scheme": scheme,
                "index": index_path,
                "compose_path": compose_path,
                "appdata_path": appdata_path,
                # compose: cần đọc được file; docker run: tạo lại trực tiếp (trừ AppManager — đợt sau)
                "can_update": has_compose or manage == "run",
                "can_edit": has_compose or manage == "run",
                "manage": "compose" if has_compose else manage,
                **hint,
                "portainer_stack": portainer_stack,
                "project": project,
                "service": service,
                "source_url": pref.get("custom_repo") or cached.get("source_url") or source_url,
                "custom_repo": pref.get("custom_repo") or "",
                "auto_update": bool(pref.get("auto_update", 0)),
                "is_self": is_self,
                "has_update": has_update,
                "raw_has_update": raw_has_update,
                "is_skipped": is_skipped,
                "skip_token": skip_token,
                "remote_version": cached.get("remote_version") or "",
                "channels": _parse_channels(cached.get("channels")),
                "image_tag": image_ref.rsplit("/", 1)[-1].split(":", 1)[1] if ":" in image_ref.rsplit("/", 1)[-1] else "latest",
                "target_tag": target_tag,
                "remote_digest": remote_digest,
                "local_digest": local_digests[0] if local_digests else (cached.get("local_digest") or ""),
                "checked_at": cached.get("checked_at") or "",
                "update_error": cached.get("error") or "",
                "release_tag": cached.get("release_tag") or "",
                "release_url": cached.get("release_url") or "",
                "published_at": cached.get("published_at") or "",
                "has_changelog": bool(cached.get("changelog")),
            }
        )

    items.sort(
        key=lambda x: (
            not x["has_update"],
            x["status"] != "running",
            x["source"] != "casaos",
            x["title"].lower(),
        )
    )

    last_checked = max((i["checked_at"] for i in items if i["checked_at"]), default="")

    return {
        "environment": "casaos" if is_casaos_env else "docker",
        "last_checked": last_checked,
        "summary": {
            "total": len(items),
            "running": sum(1 for i in items if i["status"] == "running"),
            "stopped": sum(1 for i in items if i["status"] != "running"),
            "casaos": sum(1 for i in items if i["source"] == "casaos"),
            "docker": sum(1 for i in items if i["source"] == "docker"),
            "updates": sum(1 for i in items if i["has_update"]),
        },
        "apps": items,
    }


def get_app_by_name(container_name: str) -> Optional[dict[str, Any]]:
    data = list_all_apps(include_cache=True)
    for app in data["apps"]:
        if app["name"] == container_name or app["id"] == container_name:
            return app
    return None


def container_action(container_id: str, action: str) -> dict[str, Any]:
    client = get_docker_client()
    try:
        c = client.containers.get(container_id)
        if action == "start":
            c.start()
        elif action == "stop":
            c.stop(timeout=15)
        elif action == "restart":
            c.restart(timeout=15)
        elif action == "kill":
            c.kill()
        else:
            raise ValueError(f"Unsupported action: {action}")
        c.reload()
        return {"ok": True, "id": c.short_id, "status": c.status}
    except NotFound:
        raise KeyError("Container not found")
    except DockerException as e:
        raise RuntimeError(str(e))


def image_users_sync(image_id: str, exclude: str = "") -> list[dict[str, Any]]:
    """Container (trừ `exclude`) đang dùng image này: [{name, status, project, is_self}] — để báo vì sao không xoá được."""
    if not image_id:
        return []
    client = get_docker_client()
    own = socket.gethostname()
    out = []
    for c in client.containers.list(all=True):
        if c.name == exclude or (c.attrs.get("Image") or "") != image_id:
            continue
        labels = (c.attrs.get("Config") or {}).get("Labels") or {}
        out.append({"name": c.name, "status": c.status, "project": labels.get("com.docker.compose.project") or "",
                    "is_self": c.id.startswith(own) or c.name == "appmanager-pro"})
    return out


def mount_users_sync(path: str, exclude: str = "") -> list[str]:
    """Container khác đang mount thư mục `path` (hoặc thư mục con / cha của nó)."""
    if not path:
        return []
    p = path.rstrip("/")
    out = []
    for c in get_docker_client().containers.list(all=True):
        if c.name == exclude:
            continue
        for m in c.attrs.get("Mounts") or []:
            src = (m.get("Source") or "").rstrip("/")
            if src and (src == p or src.startswith(p + "/") or p.startswith(src + "/")) and m.get("Type") == "bind":
                out.append(c.name)
                break
    return out
