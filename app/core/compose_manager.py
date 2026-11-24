import asyncio
import io
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ruamel.yaml import YAML

from app.core.database import DATA_DIR, get_setting, set_setting
from app.core.docker_client import (
    compose_cmd,
    APPDATA_DIR,
    CASAOS_APPS_DIR,
    get_app_by_name,
    get_docker_client,
)
from app.core.compose_snapshot import compose_changed_since_created, get_good, rollback_compose_text, save_good
from app.core.updater import (
    _container_attrs_sync,
    _diagnostics_sync,
    _probe_container_sync,
    _trigger_self_update_helper,
    _wait_healthy,
)

BACKUPS_ROOT = DATA_DIR / "backups"
SECRET_KEY_WORDS = ("PASS", "SECRET", "TOKEN", "API_KEY", "APIKEY", "AUTH_KEY", "PRIVATE_KEY")
LogCallback = Callable[[str], Awaitable[None]]


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

    return {
        "selected_service": selected,
        "services": service_names,
        "service": {
            "image": str(svc.get("image") or ""),
            "container_name": str(svc.get("container_name") or ""),
            "restart": str(svc.get("restart") or "unless-stopped"),
            "network_mode": str(svc.get("network_mode") or ""),
            "privileged": bool(svc.get("privileged", False)),
            "ports": [_parse_port_entry(p) for p in (svc.get("ports") or [])],
            "volumes": [_parse_volume_entry(v) for v in (svc.get("volumes") or [])],
            "environment": _parse_env_entries(svc.get("environment"), x_envs_desc),
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


def _pop_matching_long(entries: list[Any], key: str, value: Any) -> Optional[dict[str, Any]]:
    """Lấy (và bỏ khỏi danh sách) mục dạng dài đầu tiên có entries[i][key] == value, để giữ các khoá phụ."""
    for i, e in enumerate(entries):
        if isinstance(e, dict) and str(e.get(key)) == str(value):
            return entries.pop(i)
    return None


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

    orig_ports = list(svc.get("ports") or [])
    use_long_ports = bool(data.get("x-casaos")) or any(isinstance(p, dict) for p in orig_ports)
    clean_ports = []
    for p in s_ui.get("ports") or []:
        c_port = str(p.get("container") or "").strip()
        h_port = str(p.get("host") or "").strip()
        proto = str(p.get("protocol") or "tcp").strip().lower() or "tcp"
        if not c_port:
            continue
        if use_long_ports and ":" not in h_port and c_port.isdigit():
            # Giữ nguyên các khoá khác của mục cũ (mode, host_ip, name, app_protocol...)
            entry = _pop_matching_long(orig_ports, "target", int(c_port)) or {}
            entry["target"] = int(c_port)
            entry["protocol"] = proto
            if h_port:
                entry["published"] = h_port
            elif "published" in entry:
                del entry["published"]
            clean_ports.append(entry)
        else:
            base = f"{h_port}:{c_port}" if h_port else c_port
            clean_ports.append(f"{base}/{proto}" if proto != "tcp" else base)

    if clean_ports:
        svc["ports"] = clean_ports
    elif "ports" in svc:
        del svc["ports"]

    orig_vols = list(svc.get("volumes") or [])
    use_long_vols = any(isinstance(v, dict) for v in orig_vols)
    clean_vols = []
    for v in s_ui.get("volumes") or []:
        src = str(v.get("source") or "").strip()
        dst = str(v.get("target") or "").strip()
        ro = bool(v.get("read_only", False))
        if not dst:
            continue
        if use_long_vols and src:
            # Giữ nguyên các khoá khác của mục cũ (bind.create_host_path, propagation, volume.nocopy...);
            # mục mới tự tạo thư mục trên máy chủ như dạng ngắn "src:dst" (dạng dài mặc định KHÔNG tạo -> lỗi).
            ventry = _pop_matching_long(orig_vols, "target", dst)
            if ventry is None:
                ventry = {"type": "bind" if src.startswith(("/", ".", "~")) else "volume"}
                if ventry["type"] == "bind":
                    ventry["bind"] = {"create_host_path": True}
            ventry["source"] = src
            ventry["target"] = dst
            if ro:
                ventry["read_only"] = True
            elif "read_only" in ventry:
                del ventry["read_only"]
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
        # Không ghi giá trị rỗng cho khoá vốn không có (tránh làm bẩn compose / CasaOS hiển thị sai)
        for key in ("icon", "port_map"):
            if key in c_ui:
                val = str(c_ui[key] or "").strip()
                if val or key in x_root:
                    x_root[key] = val
        if c_ui.get("scheme"):
            x_root["scheme"] = c_ui["scheme"].strip()
        if "index" in c_ui:
            x_root["index"] = c_ui["index"].strip() or "/"
        if c_ui.get("category"):
            x_root["category"] = c_ui["category"].strip()

    buf = io.StringIO()
    ryaml.dump(data, buf)
    return buf.getvalue()


def sanitize_app_id(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", (raw or "").strip().lower()).strip("-_")
    return slug


def generate_deploy_yaml(form: dict[str, Any]) -> str:
    """Sinh docker-compose.yml chuẩn CasaOS từ Visual Form của + Deploy App."""
    app_id = sanitize_app_id(form.get("app_id") or form.get("title") or "my-app") or "my-app"
    title = (form.get("title") or app_id).strip()
    image = (form.get("image") or "").strip()
    if not image:
        raise ValueError("Docker image is required (e.g. nginx:latest)")

    service_cfg: dict[str, Any] = {
        "image": image,
        "container_name": app_id,
        "restart": (form.get("restart") or "unless-stopped").strip(),
    }

    net_mode = (form.get("network_mode") or "").strip()
    if net_mode:
        service_cfg["network_mode"] = net_mode
    if form.get("privileged"):
        service_cfg["privileged"] = True

    ports = []
    first_host_port = ""
    for p in form.get("ports") or []:
        c_port = str(p.get("container") or "").strip()
        h_port = str(p.get("host") or "").strip()
        proto = str(p.get("protocol") or "tcp").strip().lower() or "tcp"
        if not c_port:
            continue
        if not first_host_port and h_port:
            first_host_port = h_port
        if c_port.isdigit() and ":" not in h_port:
            item: dict[str, Any] = {"target": int(c_port), "protocol": proto}
            if h_port:
                item["published"] = h_port
            ports.append(item)
        else:
            base = f"{h_port}:{c_port}" if h_port else c_port
            ports.append(f"{base}/{proto}" if proto != "tcp" else base)
    if ports:
        service_cfg["ports"] = ports

    volumes = []
    for v in form.get("volumes") or []:
        src = str(v.get("source") or "").strip()
        dst = str(v.get("target") or "").strip()
        if not dst:
            continue
        val = f"{src}:{dst}" if src else dst
        if v.get("read_only"):
            val += ":ro"
        volumes.append(val)
    if volumes:
        service_cfg["volumes"] = volumes

    envs = []
    for e in form.get("environment") or []:
        k = str(e.get("key") or "").strip()
        if not k:
            continue
        v = str(e.get("value") or "")
        envs.append(f"{k}={v}")
    if envs:
        service_cfg["environment"] = envs

    compose: dict[str, Any] = {
        "name": app_id,
        "services": {app_id: service_cfg},
        "x-casaos": {
            "architectures": ["amd64", "arm64"],
            "main": app_id,
            "category": (form.get("category") or "Utilities").strip(),
            "icon": (form.get("icon") or "").strip(),
            "index": "/",
            "port_map": str(form.get("port_map") or first_host_port or "").strip(),
            "scheme": "http",
            "title": {"en_US": title},
        },
    }

    ryaml = _make_yaml()
    buf = io.StringIO()
    ryaml.dump(compose, buf)
    return buf.getvalue()


async def validate_compose_yaml(yaml_text: str, compose_dir: str) -> tuple[bool, str]:
    try:
        ryaml = _make_yaml()
        parsed = ryaml.load(yaml_text)
        if not isinstance(parsed, dict) or "services" not in parsed:
            return False, "YAML must define a 'services' section."
    except Exception as exc:
        return False, f"YAML syntax error: {exc}"

    Path(compose_dir).mkdir(parents=True, exist_ok=True)
    tmp_file = Path(compose_dir) / ".appmanager-validate.tmp.yml"
    try:
        tmp_file.write_text(yaml_text, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", str(tmp_file), "config", "-q",
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


async def deploy_new_app_stream(
    app_id_raw: str,
    raw_yaml: str,
    send_log: LogCallback,
) -> dict[str, Any]:
    """Lưu docker-compose.yml mới chuẩn CasaOS/Docker và kéo image khởi chạy live."""
    try:
        ryaml = _make_yaml()
        parsed = ryaml.load(raw_yaml) or {}
        if not isinstance(parsed, dict) or not parsed.get("services"):
            await send_log("[ERROR] YAML must include a valid 'services' block.\n")
            return {"ok": False, "error": "Invalid YAML"}
    except Exception as exc:
        await send_log(f"[ERROR] YAML syntax error: {exc}\n")
        return {"ok": False, "error": str(exc)}

    inferred_name = app_id_raw or str(parsed.get("name") or next(iter(parsed["services"].keys())))
    app_id = sanitize_app_id(inferred_name)
    if not app_id or len(app_id) < 2:
        await send_log("[ERROR] Invalid App ID. Use lowercase letters, numbers, or hyphens.\n")
        return {"ok": False, "error": "Invalid App ID"}

    # Tự chọn thư mục chuẩn theo môi trường (CasaOS -> /var/lib/casaos/apps/<id>)
    if CASAOS_APPS_DIR.exists():
        root_dir = CASAOS_APPS_DIR
    elif APPDATA_DIR.exists():
        root_dir = APPDATA_DIR
    else:
        # Thư mục trong container KHÔNG khớp đường dẫn trên máy thật -> bind mount tương đối sẽ sai chỗ
        msg = (f"No host app folder is mounted. Mount {APPDATA_DIR} (or {CASAOS_APPS_DIR}) into the "
               "AppManager Pro container with the same path on the host, then deploy again.")
        await send_log(f"[ERROR] {msg}\n")
        return {"ok": False, "error": msg}

    target_dir = root_dir / app_id
    compose_path = target_dir / "docker-compose.yml"
    if compose_path.exists():
        msg = f"App folder already exists: {target_dir}"
        await send_log(f"[ERROR] {msg}\n")
        return {"ok": False, "error": msg}

    # Validate cú pháp trước khi tạo thư mục thật
    ok_valid, valid_msg = await validate_compose_yaml(raw_yaml, str(DATA_DIR))
    if not ok_valid:
        await send_log(f"[ERROR] Compose validation failed:\n{valid_msg}\n")
        return {"ok": False, "error": valid_msg}

    created_dir = not target_dir.exists()
    target_dir.mkdir(parents=True, exist_ok=True)
    compose_path.write_text(raw_yaml, encoding="utf-8")
    await send_log(f"==> Saved compose file: {compose_path}\n\n")

    async def _stream_cmd(cmd: list[str]) -> int:
        await send_log(f"$ {' '.join(cmd)}\n")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(target_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await send_log(line.decode("utf-8", errors="replace"))
        return await proc.wait()

    rc_pull = await _stream_cmd(["docker", "compose", "-f", str(compose_path), "pull"])
    if rc_pull != 0:
        if created_dir:
            shutil.rmtree(target_dir, ignore_errors=True)
        else:
            compose_path.unlink(missing_ok=True)
        await send_log(f"\n[ERROR] Pull failed (exit {rc_pull}). Cleaned up compose file.\n")
        return {"ok": False, "error": f"Pull failed (exit {rc_pull})"}

    await send_log("\n")
    rc_up = await _stream_cmd(["docker", "compose", "-f", str(compose_path), "up", "-d"])
    if rc_up != 0:
        if created_dir:
            shutil.rmtree(target_dir, ignore_errors=True)
        else:
            compose_path.unlink(missing_ok=True)
        await send_log(f"\n[ERROR] Deploy failed (exit {rc_up}). Cleaned up compose file.\n")
        return {"ok": False, "error": f"Up failed (exit {rc_up})"}

    await send_log(f"\n✅ App '{app_id}' deployed successfully!\n")
    return {"ok": True, "app_id": app_id, "compose_path": str(compose_path)}


def find_other_compose_files(compose_path: str, names: list[str]) -> list[str]:
    """
    Các file compose KHÁC NỘI DUNG cho cùng app ở chỗ quen thuộc (CasaOS / AppData). Hai bản lệch nhau rất dễ
    gây sập app: CasaOS hoặc Terminal tạo lại container từ bản này trong khi người dùng chỉ sửa bản kia.
    """
    try:
        current = Path(compose_path).resolve()
        current_text = current.read_text(encoding="utf-8")
    except Exception:
        return []
    found: list[str] = []
    for base in (CASAOS_APPS_DIR, APPDATA_DIR):
        for name in dict.fromkeys(n for n in names if n and re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", n)):
            for fname in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                p = base / name / fname
                try:
                    if not p.is_file() or p.resolve() == current:
                        continue
                    if p.read_text(encoding="utf-8") != current_text:
                        found.append(str(p))
                except Exception:
                    continue
    return found


def _dup_skip_key(container_name: str) -> str:
    return f"compose_dup_skip:{container_name}"


def _dup_fingerprint(compose_path: str, others: list[str]) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in [compose_path, *sorted(others)]:
        try:
            h.update(p.encode() + b"\0" + Path(p).read_bytes() + b"\0")
        except Exception:
            pass
    return h.hexdigest()[:32]


def visible_duplicate_files(container_name: str, compose_path: str, names: list[str]) -> list[str]:
    """Các file compose trùng khác nội dung — trừ khi người dùng đã bấm Skip cho đúng trạng thái hiện tại."""
    others = find_other_compose_files(compose_path, names)
    if others and get_setting(_dup_skip_key(container_name), "") == _dup_fingerprint(compose_path, others):
        return []
    return others


def duplicate_compose_state(container_name: str, compose_path: str, names: list[str]) -> tuple[int, bool]:
    """(số file compose khác nội dung, người dùng đã bấm Skip cho đúng trạng thái hiện tại chưa).
    Biểu tượng trên thẻ app chỉ mất khi không còn file nào khác nội dung (đã Merge); Skip chỉ ẩn cảnh báo bên trong."""
    others = find_other_compose_files(compose_path, names)
    if not others:
        return 0, False
    return len(others), get_setting(_dup_skip_key(container_name), "") == _dup_fingerprint(compose_path, others)


def _merge_compose_text(active_text: str, other_text: str) -> str:
    """
    Gộp: giữ NGUYÊN cấu hình đang chạy (services, volumes, env...) của file đang chạy; chỉ lấy thêm từ file kia
    các khối mở rộng x-* (vd x-casaos: tiêu đề, icon, cổng cho CasaOS) mà file đang chạy chưa có.
    """
    ry = _make_yaml()
    active = ry.load(active_text) or {}
    other = ry.load(other_text) or {}
    if not isinstance(active, dict) or not isinstance(other, dict):
        return active_text
    for key, val in other.items():
        if str(key).startswith("x-") and key not in active:
            active[key] = val
    a_svcs = active.get("services") or {}
    o_svcs = other.get("services") or {}
    if isinstance(a_svcs, dict) and isinstance(o_svcs, dict):
        for name, o_svc in o_svcs.items():
            a_svc = a_svcs.get(name)
            if isinstance(a_svc, dict) and isinstance(o_svc, dict):
                for key, val in o_svc.items():
                    if str(key).startswith("x-") and key not in a_svc:
                        a_svc[key] = val
    buf = io.StringIO()
    ry.dump(active, buf)
    return buf.getvalue()


async def resolve_duplicate_compose(container_name: str, action: str) -> dict[str, Any]:
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        return {"ok": False, "error": "Container not found"}
    compose_path = app_info.get("compose_path") or ""
    if not compose_path or not Path(compose_path).is_file():
        return {"ok": False, "error": "No docker-compose.yml found"}
    names = [app_info.get("project") or "", container_name, Path(compose_path).parent.name]
    others = await asyncio.to_thread(find_other_compose_files, compose_path, names)
    if not others:
        return {"ok": True, "message": "No other compose file differs from the running one."}

    if action == "skip":
        set_setting(_dup_skip_key(container_name), _dup_fingerprint(compose_path, others))
        return {"ok": True, "message": "Warning hidden until one of these files changes."}
    if action != "merge":
        return {"ok": False, "error": "Unknown action"}

    # Chỉ gộp khi bản đang chạy thật sự chạy tốt -> không bao giờ nhân bản một cấu hình lỗi
    try:
        st = await asyncio.to_thread(_probe_container_sync, container_name)
    except Exception as exc:
        return {"ok": False, "error": f"Cannot inspect the container: {exc}"}
    if st.get("status") != "running" or st.get("restarting") or st.get("health") == "unhealthy":
        return {"ok": False, "error": (
            f"The container is not running correctly (status: {st.get('status')}"
            f"{', unhealthy' if st.get('health') == 'unhealthy' else ''}). Merge is only allowed from a working configuration."
        )}
    attrs = await asyncio.to_thread(_container_attrs_sync, container_name)
    active_text = Path(compose_path).read_text(encoding="utf-8")
    if compose_changed_since_created(compose_path, attrs):
        good = get_good(container_name, compose_path)
        if good is None or good != active_text:
            return {"ok": False, "error": (
                "docker-compose.yml was edited after the container was created and has not been applied yet. "
                "Apply it (Save & Apply) or revert it first, then merge."
            )}

    merged = active_text
    for other in others:
        merged = _merge_compose_text(merged, Path(other).read_text(encoding="utf-8"))
    ok_valid, valid_msg = await validate_compose_yaml(merged, str(Path(compose_path).parent))
    if not ok_valid:
        return {"ok": False, "error": f"Merged file is not valid: {valid_msg}"}

    written: list[str] = []
    for path in [compose_path, *others]:
        p = Path(path)
        current = p.read_text(encoding="utf-8")
        if current == merged:
            continue
        p.with_name(p.name + ".bak").write_text(current, encoding="utf-8")
        if path == compose_path:
            _create_backup(container_name, current)
        p.write_text(merged, encoding="utf-8")
        written.append(path)
    # File đang chạy chỉ thêm khối x-* (không ảnh hưởng container) -> ghi nhận là bản chạy tốt
    save_good(container_name, compose_path, merged)
    set_setting(_dup_skip_key(container_name), "")
    return {"ok": True, "message": f"Merged into {len(written)} file(s); previous versions saved as .bak.", "written": written}


async def get_compose_state(container_name: str, service: Optional[str] = None) -> dict[str, Any]:
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        raise FileNotFoundError("Container not found")
    compose_path = app_info.get("compose_path") or ""
    if app_info.get("manage") == "run":
        # docker run: cấu hình hiện tại của container dưới dạng YAML (không ghi file); áp dụng = tạo lại container
        from app.core.compose_convert import generate_compose

        gen = await asyncio.to_thread(generate_compose, container_name)
        return {
            "app": app_info, "compose_path": "", "run_mode": True, "raw_yaml": gen["yaml"],
            "ui": parse_yaml_to_ui(gen["yaml"]), "backups": [], "other_compose_files": [], "skipped_compose_files": [],
        }
    if not compose_path or not Path(compose_path).exists():
        raise FileNotFoundError("No docker-compose.yml found for this container")

    raw_yaml = Path(compose_path).read_text(encoding="utf-8")
    ui = parse_yaml_to_ui(raw_yaml, preferred_service=service or app_info.get("service") or None)
    dup_names = [app_info.get("project") or "", container_name, Path(compose_path).parent.name]
    visible = await asyncio.to_thread(visible_duplicate_files, container_name, compose_path, dup_names)
    # Đã bấm Skip: cảnh báo vàng ẩn, nhưng vẫn trả danh sách để người dùng có thể Gộp sau này
    skipped = [] if visible else await asyncio.to_thread(find_other_compose_files, compose_path, dup_names)
    return {
        "app": app_info,
        "compose_path": compose_path,
        "raw_yaml": raw_yaml,
        "ui": ui,
        "backups": list_backups(container_name),
        "other_compose_files": visible,
        "skipped_compose_files": skipped,
    }


def _container_name_after_edit(raw_yaml: str, app_info: dict[str, Any]) -> str:
    """Tên container sau khi áp dụng compose mới (người dùng có thể đổi container_name)."""
    try:
        data = _make_yaml().load(raw_yaml) or {}
        svc = (data.get("services") or {}).get(app_info.get("service") or "") or {}
        name = str(svc.get("container_name") or "").strip()
        if name:
            return name
    except Exception:
        pass
    return app_info["name"]


async def _compose_up(compose_path: str, compose_dir: str, extra: Optional[list[str]] = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *compose_cmd(compose_path), "up", "-d", "--remove-orphans", *(extra or []),
        cwd=compose_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", errors="replace").strip()


async def save_and_apply_compose(container_name: str, raw_yaml: str) -> dict[str, Any]:
    """
    Lưu & áp dụng compose, rồi KIỂM TRA app có chạy ổn không. Hỏng (up lỗi, thoát, restart liên tục,
    unhealthy) -> trả docker-compose.yml về bản chạy tốt trước đó và tạo lại app.
    """
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        return {"ok": False, "error": "Container not found"}
    if app_info.get("manage") == "run":
        return await apply_run_config(app_info, raw_yaml)

    compose_path = app_info.get("compose_path") or ""
    if not compose_path or not Path(compose_path).exists():
        return {"ok": False, "error": "No docker-compose.yml found"}

    path = Path(compose_path)
    compose_dir = str(path.parent)

    ok_valid, valid_msg = await validate_compose_yaml(raw_yaml, compose_dir)
    if not ok_valid:
        return {"ok": False, "error": valid_msg}

    original_text = path.read_text(encoding="utf-8")
    attrs = await asyncio.to_thread(_container_attrs_sync, container_name)
    rollback_text, _note = rollback_compose_text(container_name, compose_path, original_text, attrs)
    backup_file = _create_backup(container_name, original_text)
    path.write_text(raw_yaml, encoding="utf-8")

    if app_info.get("is_self"):
        try:
            await asyncio.to_thread(
                lambda: _trigger_self_update_helper(
                    compose_path, mode="recreate", title=app_info.get("title") or "AppManager Pro",
                    from_version=app_info.get("version") or "", to_version="compose edit",
                    compose_original=rollback_text,
                )
            )
            return {
                "ok": True,
                "self_update": True,
                "backup": backup_file,
                "logs": f"Saved backup {backup_file}. Recreating AppManager Pro via helper "
                        "(it is checked and rolled back automatically if it does not start)...",
            }
        except Exception as exc:
            path.write_text(original_text, encoding="utf-8")
            return {"ok": False, "error": f"Self-recreate failed: {exc}"}

    lines: list[str] = []

    async def collect(text: str) -> None:
        lines.append(text.rstrip("\n"))

    try:
        baseline = await asyncio.to_thread(_probe_container_sync, container_name)
    except Exception:
        baseline = None
    try:
        window = max(10, min(120, int(get_setting("health_wait_seconds", "25"))))
    except Exception:
        window = 25

    rc, up_logs = await _compose_up(compose_path, compose_dir)
    lines.append(up_logs)
    new_name = _container_name_after_edit(raw_yaml, app_info)
    if rc == 0:
        lines.append(f"==> Checking the app for {window}s...")
        healthy, reason = await _wait_healthy(new_name, collect, window, baseline)
    else:
        healthy, reason = False, f"docker compose up failed (exit {rc})"
    lines.append(f"==> {reason}")

    if healthy:
        await asyncio.to_thread(save_good, new_name, compose_path, raw_yaml)
        return {
            "ok": True,
            "backup": backup_file,
            "logs": "\n".join(x for x in lines if x) or "Container recreated successfully.",
            "backups": list_backups(container_name),
        }

    # ---- Hỏng: lưu chẩn đoán, trả compose về bản chạy tốt, tạo lại app ----
    if rc == 0:
        try:
            lines.append(await asyncio.to_thread(_diagnostics_sync, new_name))
        except Exception:
            pass
    path.write_text(rollback_text, encoding="utf-8")
    lines.append("==> The app did not start correctly with the new compose. Restoring the previous docker-compose.yml...")
    rb_rc, rb_logs = await _compose_up(compose_path, compose_dir, ["--force-recreate"])
    lines.append(rb_logs)
    if rb_rc == 0:
        rb_ok, rb_reason = await _wait_healthy(container_name, collect, window)
    else:
        rb_ok, rb_reason = False, f"docker compose up failed (exit {rb_rc})"
    lines.append(f"==> Previous compose: {rb_reason}")
    return {
        "ok": False,
        "error": (f"The app did not start with the new compose ({reason}). The previous docker-compose.yml "
                  "was restored and the app is running again.")
        if rb_ok
        else (f"The app did not start with the new compose ({reason}). The previous docker-compose.yml was "
              f"restored, but the app still does not start ({rb_reason}). Check the logs."),
        "logs": "\n".join(x for x in lines if x),
        "backup": backup_file,
        "backups": list_backups(container_name),
    }


async def apply_run_config(app_info: dict[str, Any], raw_yaml: str) -> dict[str, Any]:
    """docker run: tạo lại container theo cấu hình đã sửa; hỏng -> chạy lại container cũ. AppManager: qua container phụ.
    Dùng chung khoá với cập nhật: không sửa cấu hình khi app đang được cập nhật (và ngược lại)."""
    from app.core.updater import _UPDATE_LOCKS

    name = app_info["name"]
    lock = _UPDATE_LOCKS.setdefault(name, asyncio.Lock())
    if lock.locked():
        return {"ok": False, "error": "This app is being updated or changed right now. Please wait for it to finish."}
    async with lock:
        return await _apply_run_config_locked(app_info, raw_yaml)


async def _apply_run_config_locked(app_info: dict[str, Any], raw_yaml: str) -> dict[str, Any]:
    from app.core.database import add_update_history, get_setting
    from app.core.run_manager import recreate_stream

    name = app_info["name"]
    if app_info.get("is_self"):
        from app.core.updater import trigger_self_run

        try:
            await asyncio.to_thread(trigger_self_run, mode="recreate", yaml_text=raw_yaml, from_version=app_info.get("version") or "",
                                    to_version=app_info.get("version") or "")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "self_update": True}
    chunks: list[str] = []

    async def log(t: str) -> None:
        chunks.append(t)

    try:
        window = max(10, min(120, int(get_setting("health_wait_seconds", "25"))))
    except Exception:
        window = 25
    res = await recreate_stream(name, app_info["image"], log, window=window, yaml_text=raw_yaml,
                                auto_rollback=get_setting("auto_rollback", "true").lower() == "true")
    logs = "".join(chunks)
    if res.get("ok"):
        add_update_history(name, app_info["title"], app_info.get("version") or "", app_info.get("version") or "",
                           "config", "success", "Container settings changed (docker run)")
        return {"ok": True, "logs": logs}
    if res.get("rolled_back"):
        add_update_history(name, app_info["title"], app_info.get("version") or "", app_info.get("version") or "",
                           "config", "rolled_back", f"New settings failed ({res.get('reason')}); previous container restored"[:300])
        return {"ok": False, "error": f"The new settings did not work ({res.get('reason')}); the previous container is running again.", "logs": logs}
    return {"ok": False, "error": res.get("reason") or "Apply failed", "logs": logs}


async def rollback_compose(container_name: str, backup_filename: str) -> dict[str, Any]:
    bdir = _get_backup_dir(container_name)
    target = (bdir / backup_filename).resolve()
    if not target.exists() or target.parent != bdir.resolve():
        return {"ok": False, "error": "Backup file not found"}
    backup_yaml = target.read_text(encoding="utf-8")
    return await save_and_apply_compose(container_name, backup_yaml)


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

    # App nằm trong một stack nhiều service (vd: immich + redis)? -> chỉ gỡ đúng service này
    project = app_info.get("project") or ""
    service = app_info.get("service") or ""

    def _other_services() -> int:
        if not project:
            return 0
        client = get_docker_client()
        others = client.containers.list(all=True, filters={"label": f"com.docker.compose.project={project}"})
        return len([c for c in others if c.name != container_name])

    shared_stack = bool(compose_path and service) and (await asyncio.to_thread(_other_services)) > 0

    if shared_stack and Path(compose_path).exists():
        proc = await asyncio.create_subprocess_exec(
            *compose_cmd(compose_path), "rm", "-s", "-f", service,
            cwd=str(Path(compose_path).parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        logs.append(out.decode("utf-8", errors="replace").strip())
        if proc.returncode != 0:
            return {"ok": False, "error": "docker compose rm failed", "logs": "\n".join(logs)}
        logs.append(f"Removed service '{service}' only — other services of '{project}' keep running.")
        if remove_images and image_id:
            def _rm_img():
                try:
                    get_docker_client().images.remove(image=image_id, force=False)
                    return "Removed image."
                except Exception as exc:
                    return f"Image kept (still in use or error: {exc})"
            logs.append(await asyncio.to_thread(_rm_img))
        remove_compose = False  # không xoá thư mục compose của cả stack
        logs.append("Kept the compose folder because other services still use it.")
        if remove_appdata:
            remove_appdata = False
            logs.append("Kept the AppData folder because it may be shared by the other services.")
    elif compose_path and Path(compose_path).exists():
        cmd = [*compose_cmd(compose_path), "down", "--remove-orphans"]
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
        if _is_safe_subpath(cdir, CASAOS_APPS_DIR):
            await asyncio.to_thread(shutil.rmtree, cdir, True)
            logs.append(f"Removed CasaOS app folder: {cdir}")
        else:
            logs.append(f"Skipped compose folder removal (outside CasaOS apps dir): {cdir}")

    if remove_appdata and appdata_path:
        adir = Path(appdata_path)
        if _is_safe_subpath(adir, APPDATA_DIR) and adir.exists():
            await asyncio.to_thread(shutil.rmtree, adir, True)
            logs.append(f"Deleted AppData folder: {adir}")
        else:
            logs.append(f"Skipped AppData deletion (unsafe or missing path): {adir}")

    return {"ok": True, "logs": "\n".join(x for x in logs if x)}
