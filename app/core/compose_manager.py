import asyncio
import io
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ruamel.yaml import YAML

from app.core.database import DATA_DIR
from app.core.docker_client import (
    APPDATA_DIR,
    CASAOS_APPS_DIR,
    get_app_by_name,
    get_docker_client,
)
from app.core.updater import _trigger_self_update_helper

BACKUPS_ROOT = DATA_DIR / "backups"
SECRET_KEY_WORDS = ("PASS", "SECRET", "TOKEN", "API_KEY", "APIKEY", "AUTH_KEY", "PRIVATE_KEY")
APP_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

DeployEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _get_backup_dir(container_name: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in container_name)
    d = BACKUPS_ROOT / safe_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_backups(container_name: str) -> list[dict[str, Any]]:
    bdir = _get_backup_dir(container_name)
    items: list[dict[str, Any]] = []
    for f in sorted(bdir.glob("*.yml"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        items.append(
            {
                "filename": f.name,
                "size": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
            }
        )
    return items[:20]


def _create_backup(container_name: str, content: str) -> str:
    bdir = _get_backup_dir(container_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"compose_{ts}.yml"
    (bdir / fname).write_text(content, encoding="utf-8")
    old_files = sorted(bdir.glob("*.yml"), key=lambda p: p.stat().st_mtime, reverse=True)[20:]
    for old in old_files:
        try:
            old.unlink()
        except Exception:
            pass
    return fname


def _extract_localized(val: Any, fallback: str = "") -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("en_US") or val.get("en_us") or next(iter(val.values()), fallback)
    return fallback


def _parse_port_entry(entry: Any) -> dict[str, str]:
    if isinstance(entry, dict):
        return {
            "host": str(entry.get("published") or ""),
            "container": str(entry.get("target") or ""),
            "protocol": str(entry.get("protocol") or "tcp").lower(),
        }
    s = str(entry).strip()
    proto = "tcp"
    if "/" in s:
        s, proto = s.rsplit("/", 1)
    parts = s.split(":")
    if len(parts) == 1:
        return {"host": "", "container": parts[0], "protocol": proto.lower()}
    if len(parts) == 2:
        return {"host": parts[0], "container": parts[1], "protocol": proto.lower()}
    return {"host": f"{parts[0]}:{parts[1]}", "container": parts[2], "protocol": proto.lower()}


def _parse_volume_entry(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return {
            "source": str(entry.get("source") or ""),
            "target": str(entry.get("target") or ""),
            "read_only": bool(entry.get("read_only", False)),
        }
    s = str(entry).strip()
    parts = s.split(":")
    if len(parts) == 1:
        return {"source": "", "target": parts[0], "read_only": False}
    if len(parts) == 2:
        return {"source": parts[0], "target": parts[1], "read_only": False}
    mode = parts[2].lower()
    return {"source": parts[0], "target": parts[1], "read_only": "ro" in mode}


def _parse_env_entries(env_raw: Any, x_envs_desc: dict[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(env_raw, dict):
        pairs = [(str(k), "" if v is None else str(v)) for k, v in env_raw.items()]
    elif isinstance(env_raw, list):
        pairs = []
        for entry in env_raw:
            s = str(entry)
            if "=" in s:
                k, v = s.split("=", 1)
                pairs.append((k.strip(), v))
            else:
                pairs.append((s.strip(), ""))
    else:
        pairs = []

    for k, v in pairs:
        if not k:
            continue
        low = v.strip().lower()
        is_bool = low in ("true", "false")
        ku = k.upper()
        is_secret = (not is_bool) and any(w in ku for w in SECRET_KEY_WORDS)
        items.append(
            {
                "key": k,
                "value": v,
                "is_bool": is_bool,
                "bool_val": low == "true",
                "is_secret": is_secret,
                "reveal": False,
                "description": x_envs_desc.get(k, ""),
            }
        )
    return items


def parse_yaml_to_ui(raw_yaml: str, preferred_service: Optional[str] = None) -> dict[str, Any]:
    ryaml = _make_yaml()
    data = ryaml.load(raw_yaml) or {}
    if not isinstance(data, dict):
        raise ValueError("Invalid YAML root: expected a mapping")

    services_map = data.get("services") or {}
    if not isinstance(services_map, dict) or not services_map:
        raise ValueError("No 'services' section found in docker-compose.yml")

    service_names = list(services_map.keys())
    x_root = data.get("x-casaos") if isinstance(data.get("x-casaos"), dict) else {}

    selected = preferred_service if preferred_service in services_map else None
    if not selected:
        main_svc = x_root.get("main")
        selected = main_svc if main_svc in services_map else service_names[0]

    svc = services_map.get(selected) or {}
    x_svc = svc.get("x-casaos") if isinstance(svc.get("x-casaos"), dict) else {}

    x_envs_desc: dict[str, str] = {}
    for e in x_svc.get("envs") or []:
        if isinstance(e, dict) and e.get("container"):
            x_envs_desc[str(e["container"])] = _extract_localized(e.get("description"), "")

    ports = [_parse_port_entry(p) for p in (svc.get("ports") or [])]
    volumes = [_parse_volume_entry(v) for v in (svc.get("volumes") or [])]
    environment = _parse_env_entries(svc.get("environment"), x_envs_desc)

    return {
        "selected_service": selected,
        "services": service_names,
        "service": {
            "image": str(svc.get("image") or ""),
            "container_name": str(svc.get("container_name") or ""),
            "restart": str(svc.get("restart") or "unless-stopped"),
            "network_mode": str(svc.get("network_mode") or ""),
            "privileged": bool(svc.get("privileged", False)),
            "ports": ports,
            "volumes": volumes,
            "environment": environment,
        },
        "casaos": {
            "has_block": bool(x_root),
            "title": _extract_localized(x_root.get("title"), ""),
            "icon": str(x_root.get("icon") or ""),
            "port_map": str(x_root.get("port_map") or ""),
            "scheme": str(x_root.get("scheme") or "http"),
            "index": str(x_root.get("index") or "/"),
            "category": str(x_root.get("category") or "Utilities"),
        },
    }


def merge_ui_into_yaml(base_yaml: str, ui_data: dict[str, Any]) -> str:
    ryaml = _make_yaml()
    data = ryaml.load(base_yaml) or {}
    services_map = data.setdefault("services", {})

    selected = ui_data.get("selected_service")
    if not selected or selected not in services_map:
        selected = next(iter(services_map.keys()))

    svc = services_map[selected]
    s_ui = ui_data.get("service") or {}

    if s_ui.get("image", "").strip():
        svc["image"] = s_ui["image"].strip()

    cname = (s_ui.get("container_name") or "").strip()
    if cname:
        svc["container_name"] = cname
    elif "container_name" in svc:
        del svc["container_name"]

    restart = (s_ui.get("restart") or "").strip()
    if restart:
        svc["restart"] = restart
    elif "restart" in svc:
        del svc["restart"]

    net_mode = (s_ui.get("network_mode") or "").strip()
    if net_mode:
        svc["network_mode"] = net_mode
    elif "network_mode" in svc:
        del svc["network_mode"]

    if s_ui.get("privileged"):
        svc["privileged"] = True
    elif "privileged" in svc:
        del svc["privileged"]

    orig_ports = svc.get("ports") or []
    use_long_ports = bool(data.get("x-casaos")) or any(isinstance(p, dict) for p in orig_ports)
    clean_ports = []
    for p in s_ui.get("ports") or []:
        c_port = str(p.get("container") or "").strip()
        h_port = str(p.get("host") or "").strip()
        proto = str(p.get("protocol") or "tcp").strip().lower() or "tcp"
        if not c_port:
            continue
        if use_long_ports and ":" not in h_port and c_port.isdigit():
            entry: dict[str, Any] = {"target": int(c_port), "protocol": proto}
            if h_port:
                entry["published"] = h_port
            clean_ports.append(entry)
        else:
            base = f"{h_port}:{c_port}" if h_port else c_port
            clean_ports.append(f"{base}/{proto}" if proto != "tcp" else base)

    if clean_ports:
        svc["ports"] = clean_ports
    elif "ports" in svc:
        del svc["ports"]

    orig_vols = svc.get("volumes") or []
    use_long_vols = any(isinstance(v, dict) for v in orig_vols)
    clean_vols = []
    for v in s_ui.get("volumes") or []:
        src = str(v.get("source") or "").strip()
        dst = str(v.get("target") or "").strip()
        ro = bool(v.get("read_only", False))
        if not dst:
            continue
        if use_long_vols and src:
            ventry: dict[str, Any] = {"type": "bind", "source": src, "target": dst}
            if ro:
                ventry["read_only"] = True
            clean_vols.append(ventry)
        else:
            s_val = f"{src}:{dst}" if src else dst
            if ro:
                s_val += ":ro"
            clean_vols.append(s_val)

    if clean_vols:
        svc["volumes"] = clean_vols
    elif "volumes" in svc:
        del svc["volumes"]

    orig_env = svc.get("environment")
    env_list = s_ui.get("environment") or []
    if isinstance(orig_env, dict):
        new_env_dict = {}
        for e in env_list:
            k = str(e.get("key") or "").strip()
            if not k:
                continue
            val = ("true" if e.get("bool_val") else "false") if e.get("is_bool") else str(e.get("value") or "")
            new_env_dict[k] = val
        if new_env_dict:
            svc["environment"] = new_env_dict
        elif "environment" in svc:
            del svc["environment"]
    else:
        new_env_list = []
        for e in env_list:
            k = str(e.get("key") or "").strip()
            if not k:
                continue
            val = ("true" if e.get("bool_val") else "false") if e.get("is_bool") else str(e.get("value") or "")
            new_env_list.append(f"{k}={val}")
        if new_env_list:
            svc["environment"] = new_env_list
        elif "environment" in svc:
            del svc["environment"]

    c_ui = ui_data.get("casaos") or {}
    if c_ui.get("has_block") or c_ui.get("title") or c_ui.get("icon"):
        x_root = data.setdefault("x-casaos", {})
        if c_ui.get("title", "").strip():
            if isinstance(x_root.get("title"), dict):
                x_root["title"]["en_US"] = c_ui["title"].strip()
            else:
                x_root["title"] = {"en_US": c_ui["title"].strip()}
        if "icon" in c_ui:
            x_root["icon"] = c_ui["icon"].strip()
        if "port_map" in c_ui:
            x_root["port_map"] = str(c_ui["port_map"]).strip()
        if c_ui.get("scheme"):
            x_root["scheme"] = c_ui["scheme"].strip()
        if "index" in c_ui:
            x_root["index"] = c_ui["index"].strip() or "/"
        if c_ui.get("category"):
            x_root["category"] = c_ui["category"].strip()

    buf = io.StringIO()
    ryaml.dump(data, buf)
    return buf.getvalue()


async def validate_compose_yaml(yaml_text: str, compose_dir: str) -> tuple[bool, str]:
    try:
        ryaml = _make_yaml()
        parsed = ryaml.load(yaml_text)
        if not isinstance(parsed, dict) or "services" not in parsed:
            return False, "YAML must define a 'services' section."
    except Exception as exc:
        return False, f"YAML syntax error: {exc}"

    tmp_file = Path(compose_dir) / ".appmanager-validate.tmp.yml"
    try:
        tmp_file.write_text(yaml_text, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "-f",
            str(tmp_file),
            "config",
            "-q",
            cwd=compose_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return False, out.decode("utf-8", errors="replace").strip() or "Compose validation failed"
        return True, "Valid Docker Compose configuration ✓"
    finally:
        try:
            tmp_file.unlink(missing_ok=True)
        except Exception:
            pass


async def get_compose_state(container_name: str, service: Optional[str] = None) -> dict[str, Any]:
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        raise FileNotFoundError("Container not found")
    compose_path = app_info.get("compose_path") or ""
    if not compose_path or not Path(compose_path).exists():
        raise FileNotFoundError("No docker-compose.yml found for this container")

    raw_yaml = Path(compose_path).read_text(encoding="utf-8")
    ui = parse_yaml_to_ui(raw_yaml, preferred_service=service or app_info.get("service") or None)
    return {
        "app": app_info,
        "compose_path": compose_path,
        "raw_yaml": raw_yaml,
        "ui": ui,
        "backups": list_backups(container_name),
    }


async def save_and_apply_compose(container_name: str, raw_yaml: str) -> dict[str, Any]:
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        return {"ok": False, "error": "Container not found"}

    compose_path = app_info.get("compose_path") or ""
    if not compose_path or not Path(compose_path).exists():
        return {"ok": False, "error": "No docker-compose.yml found"}

    path = Path(compose_path)
    compose_dir = str(path.parent)

    ok_valid, valid_msg = await validate_compose_yaml(raw_yaml, compose_dir)
    if not ok_valid:
        return {"ok": False, "error": valid_msg}

    original_text = path.read_text(encoding="utf-8")
    backup_file = _create_backup(container_name, original_text)
    path.write_text(raw_yaml, encoding="utf-8")

    if app_info.get("is_self"):
        try:
            await asyncio.to_thread(_trigger_self_update_helper, compose_path)
            return {
                "ok": True,
                "self_update": True,
                "backup": backup_file,
                "logs": f"Saved backup {backup_file}. Recreating AppManager Pro via helper...",
            }
        except Exception as exc:
            path.write_text(original_text, encoding="utf-8")
            return {"ok": False, "error": f"Self-recreate failed: {exc}"}

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "-f",
        compose_path,
        "up",
        "-d",
        "--remove-orphans",
        cwd=compose_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    logs = out.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        path.write_text(original_text, encoding="utf-8")
        return {
            "ok": False,
            "error": "docker compose up failed — rolled back automatically.",
            "logs": logs,
            "backup": backup_file,
        }

    return {
        "ok": True,
        "backup": backup_file,
        "logs": logs or "Container recreated successfully.",
        "backups": list_backups(container_name),
    }


async def rollback_compose(container_name: str, backup_filename: str) -> dict[str, Any]:
    bdir = _get_backup_dir(container_name)
    target = (bdir / backup_filename).resolve()
    if not target.exists() or target.parent != bdir.resolve():
        return {"ok": False, "error": "Backup file not found"}
    backup_yaml = target.read_text(encoding="utf-8")
    return await save_and_apply_compose(container_name, backup_yaml)


# ---------------- + Deploy New App ----------------

def _slugify_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-_")
    return s[:62]


def _resolve_deploy_base_dir() -> Path:
    if CASAOS_APPS_DIR.exists() and CASAOS_APPS_DIR.is_dir():
        return CASAOS_APPS_DIR
    stacks = APPDATA_DIR / "stacks"
    stacks.mkdir(parents=True, exist_ok=True)
    return stacks


def generate_deploy_yaml(form: dict[str, Any]) -> tuple[str, str]:
    """Sinh docker-compose.yml chuẩn CasaOS từ biểu mẫu tạo nhanh."""
    raw_name = (form.get("app_name") or form.get("title") or "").strip()
    slug = _slugify_name(raw_name)
    if not slug or not APP_SLUG_RE.match(slug):
        raise ValueError("App ID must start with a letter/number and contain only a-z, 0-9, -, _.")

    image = (form.get("image") or "").strip()
    if not image:
        raise ValueError("Docker image is required (e.g. nginx:latest).")

    title = (form.get("title") or slug).strip()
    restart = (form.get("restart") or "unless-stopped").strip()
    network_mode = (form.get("network_mode") or "").strip()
    icon = (form.get("icon") or "").strip()
    scheme = (form.get("scheme") or "http").strip()
    index_path = (form.get("index") or "/").strip() or "/"
    category = (form.get("category") or "Utilities").strip()

    svc: dict[str, Any] = {
        "image": image,
        "container_name": slug,
        "restart": restart,
    }
    if network_mode:
        svc["network_mode"] = network_mode
    if form.get("privileged"):
        svc["privileged"] = True

    ports = []
    first_host_port = ""
    for p in form.get("ports") or []:
        h = str(p.get("host") or "").strip()
        c = str(p.get("container") or "").strip()
        proto = str(p.get("protocol") or "tcp").strip().lower() or "tcp"
        if not c:
            continue
        if not first_host_port and h:
            first_host_port = h
        if c.isdigit() and ":" not in h:
            entry: dict[str, Any] = {"target": int(c), "protocol": proto}
            if h:
                entry["published"] = h
            ports.append(entry)
        else:
            base = f"{h}:{c}" if h else c
            ports.append(f"{base}/{proto}" if proto != "tcp" else base)
    if ports:
        svc["ports"] = ports

    envs = []
    for e in form.get("environment") or []:
        k = str(e.get("key") or "").strip()
        if not k:
            continue
        v = str(e.get("value") or "")
        envs.append(f"{k}={v}")
    if envs:
        svc["environment"] = envs

    vols = []
    for v in form.get("volumes") or []:
        src = str(v.get("source") or "").strip()
        dst = str(v.get("target") or "").strip()
        if not dst:
            continue
        line = f"{src}:{dst}" if src else dst
        if v.get("read_only"):
            line += ":ro"
        vols.append(line)
    if vols:
        svc["volumes"] = vols

    port_map = str(form.get("port_map") or first_host_port).strip()

    compose_obj: dict[str, Any] = {
        "name": slug,
        "services": {slug: svc},
        "x-casaos": {
            "architectures": ["amd64", "arm64"],
            "main": slug,
            "category": category,
            "icon": icon,
            "index": index_path,
            "port_map": port_map,
            "scheme": scheme,
            "store_app_id": slug,
            "title": {"en_US": title},
        },
    }

    ryaml = _make_yaml()
    buf = io.StringIO()
    ryaml.dump(compose_obj, buf)
    return slug, buf.getvalue()


def _infer_slug_from_yaml(raw_yaml: str, provided_name: str) -> str:
    if provided_name.strip():
        return _slugify_name(provided_name)
    ryaml = _make_yaml()
    data = ryaml.load(raw_yaml) or {}
    if isinstance(data, dict):
        if data.get("name"):
            return _slugify_name(str(data["name"]))
        svcs = data.get("services") or {}
        if isinstance(svcs, dict) and svcs:
            return _slugify_name(next(iter(svcs.keys())))
    return ""


async def validate_new_deploy(app_name: str, raw_yaml: str) -> tuple[bool, str, str]:
    slug = _infer_slug_from_yaml(raw_yaml, app_name)
    if not slug or not APP_SLUG_RE.match(slug):
        return False, "Please provide a valid App ID (lowercase letters, numbers, - or _).", ""

    base_dir = _resolve_deploy_base_dir()
    app_dir = base_dir / slug
    if app_dir.exists():
        return False, f"App folder '{app_dir}' already exists. Choose a different App ID.", slug

    tmp_dir = DATA_DIR / ".deploy-validate"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ok, msg = await validate_compose_yaml(raw_yaml, str(tmp_dir))
    return ok, msg, slug


async def deploy_app_stream(
    app_name: str,
    raw_yaml: str,
    send_event: DeployEventCallback,
) -> None:
    ok, msg, slug = await validate_new_deploy(app_name, raw_yaml)
    if not ok:
        await send_event({"type": "log", "text": f"[ERROR] {msg}\n"})
        await send_event({"type": "done", "ok": False, "error": msg})
        return

    base_dir = _resolve_deploy_base_dir()
    app_dir = base_dir / slug
    compose_file = app_dir / "docker-compose.yml"
    created_dir = False

    try:
        app_dir.mkdir(parents=True, exist_ok=False)
        created_dir = True
        compose_file.write_text(raw_yaml, encoding="utf-8")
        await send_event({"type": "log", "text": f"==> Created {compose_file}\n"})

        # Tự tạo sẵn các thư mục mount nằm trong APPDATA_DIR để tránh Docker tạo quyền root rỗng
        try:
            ryaml = _make_yaml()
            parsed = ryaml.load(raw_yaml) or {}
            base_appdata = APPDATA_DIR.resolve()
            for svc in (parsed.get("services") or {}).values():
                if not isinstance(svc, dict):
                    continue
                for v in svc.get("volumes") or []:
                    pv = _parse_volume_entry(v)
                    src = pv.get("source") or ""
                    if src.startswith(str(base_appdata)) and not Path(src).exists():
                        # Chỉ tạo nếu không giống tên file có phần mở rộng
                        if "." not in Path(src).name:
                            Path(src).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        async def _stream_cmd(cmd: list[str]) -> int:
            await send_event({"type": "log", "text": f"\n$ {' '.join(cmd)}\n"})
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(app_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await send_event({"type": "log", "text": line.decode("utf-8", errors="replace")})
            return await proc.wait()

        rc_pull = await _stream_cmd(["docker", "compose", "-f", str(compose_file), "pull"])
        if rc_pull != 0:
            raise RuntimeError(f"docker compose pull failed (exit {rc_pull})")

        rc_up = await _stream_cmd(["docker", "compose", "-f", str(compose_file), "up", "-d"])
        if rc_up != 0:
            raise RuntimeError(f"docker compose up failed (exit {rc_up})")

        await send_event({"type": "log", "text": f"\n✅ Deployed '{slug}' successfully!\n"})
        await send_event({"type": "done", "ok": True, "app_name": slug})

    except Exception as exc:
        if created_dir and app_dir.exists():
            shutil.rmtree(app_dir, ignore_errors=True)
            await send_event({"type": "log", "text": f"\n==> Cleaned up failed deployment folder {app_dir}\n"})
        await send_event({"type": "log", "text": f"[ERROR] {exc}\n"})
        await send_event({"type": "done", "ok": False, "error": str(exc)})


# ---------------- Smart Uninstall ----------------

def _is_safe_subpath(target: Path, parent: Path) -> bool:
    try:
        t = target.resolve()
        p = parent.resolve()
        return t != p and p in t.parents
    except Exception:
        return False


async def uninstall_app(
    container_name: str,
    remove_compose: bool = True,
    remove_images: bool = False,
    remove_appdata: bool = False,
    confirm_name: str = "",
) -> dict[str, Any]:
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        return {"ok": False, "error": "Container not found"}
    if app_info.get("is_self"):
        return {"ok": False, "error": "Cannot uninstall AppManager Pro from inside itself."}

    if remove_appdata and confirm_name.strip().lower() != app_info["name"].lower():
        return {"ok": False, "error": f"Please type '{app_info['name']}' to confirm AppData deletion."}

    logs: list[str] = []
    compose_path = app_info.get("compose_path") or ""
    image_id = app_info.get("image_id") or ""
    appdata_path = app_info.get("appdata_path") or ""

    if compose_path and Path(compose_path).exists():
        cmd = ["docker", "compose", "-f", compose_path, "down", "--remove-orphans"]
        if remove_images:
            cmd.extend(["--rmi", "all"])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path(compose_path).parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        logs.append(out.decode("utf-8", errors="replace").strip())
        if proc.returncode != 0:
            return {"ok": False, "error": "docker compose down failed", "logs": "\n".join(logs)}
    else:
        def _rm_standalone():
            client = get_docker_client()
            c = client.containers.get(container_name)
            c.stop(timeout=15)
            c.remove(force=True)
            if remove_images and image_id:
                try:
                    client.images.remove(image=image_id, force=False)
                except Exception:
                    pass
        await asyncio.to_thread(_rm_standalone)
        logs.append(f"Stopped & removed container {container_name}.")

    if remove_compose and compose_path:
        cdir = Path(compose_path).parent
        if _is_safe_subpath(cdir, CASAOS_APPS_DIR) or _is_safe_subpath(cdir, APPDATA_DIR / "stacks"):
            await asyncio.to_thread(shutil.rmtree, cdir, True)
            logs.append(f"Removed app compose folder: {cdir}")

    if remove_appdata and appdata_path:
        adir = Path(appdata_path)
        if _is_safe_subpath(adir, APPDATA_DIR) and adir.exists():
            await asyncio.to_thread(shutil.rmtree, adir, True)
            logs.append(f"Deleted AppData folder: {adir}")

    return {"ok": True, "logs": "\n".join(x for x in logs if x)}
