import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import docker
from docker.errors import DockerException, NotFound
from ruamel.yaml import YAML

CASAOS_APPS_DIR = Path(os.getenv("CASAOS_APPS_DIR", "/var/lib/casaos/apps"))
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


def load_casaos_metadata() -> dict[str, dict[str, Any]]:
    """
    Quét thư mục /var/lib/casaos/apps để lấy metadata x-casaos (icon, title, port_map, scheme, index).
    Trả về dict map theo tên thư mục app và tên compose project.
    """
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


def _detect_real_version(image_tags: list[str], labels: dict[str, str], image_labels: dict[str, str]) -> str:
    merged = {**image_labels, **labels}
    for key in (
        "org.opencontainers.image.version",
        "build_version",
        "org.label-schema.version",
        "version",
    ):
        val = merged.get(key)
        if val and val.lower() not in ("unknown", "none"):
            return str(val).strip()

    if image_tags:
        tag = image_tags[0].split(":")[-1]
        return tag
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


def list_all_apps() -> dict[str, Any]:
    client = get_docker_client()
    casaos_meta_map = load_casaos_metadata()
    is_casaos_env = CASAOS_APPS_DIR.exists()

    containers = client.containers.list(all=True)
    items: list[dict[str, Any]] = []

    for c in containers:
        attrs = c.attrs or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        network_settings = attrs.get("NetworkSettings") or {}
        labels = config.get("Labels") or {}

        image_tags: list[str] = []
        image_labels: dict[str, str] = {}
        try:
            image_tags = c.image.tags or []
            image_labels = (c.image.attrs.get("Config") or {}).get("Labels") or {}
        except Exception:
            pass

        image_ref = config.get("Image") or (image_tags[0] if image_tags else c.image.short_id)
        project = (labels.get("com.docker.compose.project") or "").lower()
        working_dir = labels.get("com.docker.compose.project.working_dir") or ""
        service = labels.get("com.docker.compose.service") or ""

        # Khớp với CasaOS metadata nếu có
        meta: Optional[dict[str, Any]] = (
            casaos_meta_map.get(working_dir)
            or casaos_meta_map.get(project)
            or casaos_meta_map.get(c.name.lower())
        )

        source = "casaos" if meta else "docker"
        is_main = True if not meta else (not service or service == meta.get("main_service"))

        title = meta["title"] if (meta and is_main) else (
            f"{meta['title']} ({service})" if meta else c.name
        )
        icon = meta["icon"] if meta else ""
        port_map = (meta["port_map"] if (meta and is_main) else "") or _extract_first_host_port(
            network_settings.get("Ports") or {}
        )
        scheme = meta["scheme"] if meta else "http"
        index_path = meta["index"] if meta else "/"
        compose_path = meta["compose_path"] if meta else (
            f"{working_dir}/docker-compose.yml" if working_dir else ""
        )

        # Lấy nguồn GitHub từ OCI label (sẵn sàng cho Phase 2 Changelog)
        source_url = (
            image_labels.get("org.opencontainers.image.source")
            or labels.get("org.opencontainers.image.source")
            or ""
        )

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
                "version": _detect_real_version(image_tags, labels, image_labels),
                "port_map": port_map,
                "scheme": scheme,
                "index": index_path,
                "compose_path": compose_path,
                "project": project,
                "source_url": source_url,
            }
        )

    # Sắp xếp: Đang chạy trước -> CasaOS trước -> Theo tên A-Z
    items.sort(key=lambda x: (x["status"] != "running", x["source"] != "casaos", x["title"].lower()))

    return {
        "environment": "casaos" if is_casaos_env else "docker",
        "summary": {
            "total": len(items),
            "running": sum(1 for i in items if i["status"] == "running"),
            "stopped": sum(1 for i in items if i["status"] != "running"),
            "casaos": sum(1 for i in items if i["source"] == "casaos"),
            "docker": sum(1 for i in items if i["source"] == "docker"),
        },
        "apps": items,
    }


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
        else:
            raise ValueError(f"Unsupported action: {action}")
        c.reload()
        return {"ok": True, "id": c.short_id, "status": c.status}
    except NotFound:
        raise KeyError("Container not found")
    except DockerException as e:
        raise RuntimeError(str(e))
