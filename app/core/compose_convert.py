"""
Chuyển container tạo bằng `docker run` sang Docker Compose để AppManager quản lý như app bình thường.

Sinh docker-compose.yml từ cấu hình thật của container (docker inspect), chỉ giữ những gì khác mặc định của
image. Volume có tên / ẩn danh được khai báo `external` để container mới dùng ĐÚNG dữ liệu cũ (không tạo volume
mới mang tiền tố project). Khi chuyển: đổi tên container cũ và dừng nó (không xoá) -> `docker compose up -d` ->
kiểm tra sức khoẻ -> ổn thì xoá container cũ (giữ volume), hỏng thì gỡ container mới và chạy lại container cũ.
"""
from __future__ import annotations

import asyncio
import io
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from ruamel.yaml import YAML

from app.core.docker_client import APPDATA_DIR, get_docker_client

LogCallback = Callable[[str], Awaitable[None]]
_DEFAULT_NETWORKS = {"bridge", "default", ""}


def _yaml() -> YAML:
    y = YAML()
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    y.default_flow_style = False
    return y


def _ports(host_cfg: dict) -> list[str]:
    out: list[str] = []
    for cport, binds in sorted((host_cfg.get("PortBindings") or {}).items()):
        num, _, proto = cport.partition("/")
        suffix = "" if proto in ("", "tcp") else f"/{proto}"
        for b in binds or []:
            hp, hip = (b.get("HostPort") or ""), (b.get("HostIp") or "")
            if not hp:
                out.append(f"{num}{suffix}")
            elif hip and hip not in ("0.0.0.0", "::"):
                out.append(f"{hip}:{hp}:{num}{suffix}")
            else:
                out.append(f"{hp}:{num}{suffix}")
    return list(dict.fromkeys(out))


def generate_compose(container_name: str) -> dict[str, Any]:
    """Trả về {"yaml": nội dung, "service": tên service, "notes": [ghi chú những gì không chuyển được]}."""
    client = get_docker_client()
    c = client.containers.get(container_name)
    a = c.attrs or {}
    cfg, host = a.get("Config") or {}, a.get("HostConfig") or {}
    labels = cfg.get("Labels") or {}
    if labels.get("com.docker.compose.project"):
        raise ValueError("This container is already managed by Docker Compose")
    try:
        img_cfg = c.image.attrs.get("Config") or {}
    except Exception:
        img_cfg = {}
    name = c.name
    service = re.sub(r"[^a-z0-9_-]", "-", name.lower()).strip("-") or "app"
    notes: list[str] = []
    svc: dict[str, Any] = {"image": cfg.get("Image"), "container_name": name}

    rp = host.get("RestartPolicy") or {}
    if rp.get("Name") and rp["Name"] != "no":
        svc["restart"] = rp["Name"] + (f":{rp['MaximumRetryCount']}" if rp["Name"] == "on-failure" and rp.get("MaximumRetryCount") else "")

    if cfg.get("Hostname") and not c.id.startswith(cfg["Hostname"]):
        svc["hostname"] = cfg["Hostname"]
    if cfg.get("User") and cfg.get("User") != img_cfg.get("User"):
        svc["user"] = cfg["User"]
    if cfg.get("WorkingDir") and cfg.get("WorkingDir") != img_cfg.get("WorkingDir"):
        svc["working_dir"] = cfg["WorkingDir"]
    if cfg.get("Entrypoint") and cfg.get("Entrypoint") != img_cfg.get("Entrypoint"):
        svc["entrypoint"] = list(cfg["Entrypoint"])
    if cfg.get("Cmd") and cfg.get("Cmd") != img_cfg.get("Cmd"):
        svc["command"] = list(cfg["Cmd"])
    if cfg.get("Tty"):
        svc["tty"] = True
    if cfg.get("OpenStdin"):
        svc["stdin_open"] = True

    img_env = set(img_cfg.get("Env") or [])
    env = [e for e in (cfg.get("Env") or []) if e not in img_env]
    if env:
        svc["environment"] = env

    net_mode = host.get("NetworkMode") or ""
    networks = list(((a.get("NetworkSettings") or {}).get("Networks") or {}).keys())
    ext_networks: list[str] = []
    if net_mode in ("host", "none") or net_mode.startswith("container:"):
        if net_mode.startswith("container:"):
            notes.append("network_mode uses another container; check that it still exists")
        svc["network_mode"] = net_mode
    else:
        ports = _ports(host)
        if ports:
            svc["ports"] = ports
        custom = [n for n in networks if n not in _DEFAULT_NETWORKS]
        if custom:
            svc["networks"] = custom
            ext_networks = custom

    vols: list[str] = []
    ext_volumes: list[str] = []
    for m in a.get("Mounts") or []:
        dst = m.get("Destination") or ""
        ro = "" if m.get("RW", True) else ":ro"
        if m.get("Type") == "bind":
            vols.append(f"{m.get('Source')}:{dst}{ro}")
        elif m.get("Type") == "volume" and m.get("Name"):
            vols.append(f"{m['Name']}:{dst}{ro}")
            ext_volumes.append(m["Name"])
        elif m.get("Type") == "tmpfs":
            svc.setdefault("tmpfs", []).append(dst)
    if vols:
        svc["volumes"] = vols

    for key, src in (("privileged", "Privileged"), ("read_only", "ReadonlyRootfs"), ("init", "Init")):
        if host.get(src):
            svc[key] = True
    for key, src in (("cap_add", "CapAdd"), ("cap_drop", "CapDrop"), ("dns", "Dns"), ("dns_search", "DnsSearch"),
                     ("extra_hosts", "ExtraHosts"), ("security_opt", "SecurityOpt"), ("group_add", "GroupAdd")):
        if host.get(src):
            svc[key] = list(host[src])
    if host.get("Devices"):
        svc["devices"] = [
            f"{d['PathOnHost']}:{d['PathInContainer']}" + (f":{d['CgroupPermissions']}" if d.get("CgroupPermissions") not in ("", "rwm") else "")
            for d in host["Devices"]
        ]
    if host.get("DeviceRequests"):
        notes.append("GPU / device requests were not converted; add a deploy.resources section if needed")
    if host.get("Sysctls"):
        svc["sysctls"] = dict(host["Sysctls"])
    if host.get("ShmSize") and host["ShmSize"] != 67108864:
        svc["shm_size"] = str(host["ShmSize"])
    if host.get("Memory"):
        svc["mem_limit"] = str(host["Memory"])
    if host.get("NanoCpus"):
        svc["cpus"] = round(host["NanoCpus"] / 1e9, 2)
    for key, src in (("pid", "PidMode"), ("ipc", "IpcMode")):
        if host.get(src) in ("host",):
            svc[key] = host[src]
    log_cfg = host.get("LogConfig") or {}
    if log_cfg.get("Type") and (log_cfg.get("Type") != "json-file" or log_cfg.get("Config")):
        svc["logging"] = {"driver": log_cfg["Type"], **({"options": dict(log_cfg["Config"])} if log_cfg.get("Config") else {})}

    img_labels = img_cfg.get("Labels") or {}
    own_labels = {k: v for k, v in labels.items() if img_labels.get(k) != v and not k.startswith("com.docker.")}
    if own_labels:
        svc["labels"] = own_labels

    doc: dict[str, Any] = {"name": service, "services": {service: svc}}
    if ext_volumes:
        doc["volumes"] = {v: {"external": True} for v in dict.fromkeys(ext_volumes)}
    if ext_networks:
        doc["networks"] = {n: {"external": True} for n in ext_networks}
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return {"yaml": buf.getvalue(), "service": service, "notes": notes,
            "folder": str(APPDATA_DIR / service), "name": name}


def _default_ok(folder: str) -> tuple[bool, str]:
    p = Path(folder)
    if not folder.startswith("/") or ".." in p.parts:
        return False, "Enter an absolute folder path"
    if not p.parent.is_dir():
        return False, f"{p.parent} is not accessible inside AppManager (mount it first)"
    return True, ""


async def convert_stream(container_name: str, folder: str, yaml_text: str, send_log: LogCallback) -> dict[str, Any]:
    from app.core.updater import _diagnostics_sync, _wait_healthy  # tránh import vòng

    ok, msg = _default_ok(folder)
    if not ok:
        await send_log(f"[ERROR] {msg}\n")
        return {"ok": False, "error": msg}
    target = Path(folder) / "docker-compose.yml"
    if target.exists():
        msg = f"{target} already exists; choose another folder"
        await send_log(f"[ERROR] {msg}\n")
        return {"ok": False, "error": msg}
    client = get_docker_client()
    try:
        old = await asyncio.to_thread(client.containers.get, container_name)
    except Exception as exc:
        await send_log(f"[ERROR] Container not found: {exc}\n")
        return {"ok": False, "error": "Container not found"}
    if ((old.attrs.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.project"):
        return {"ok": False, "error": "Already managed by Docker Compose"}
    was_running = old.status == "running"

    Path(folder).mkdir(parents=True, exist_ok=True)
    target.write_text(yaml_text, encoding="utf-8")
    await send_log(f"==> Wrote {target}\n")

    async def run(cmd: list[str]) -> int:
        await send_log("$ " + " ".join(cmd) + "\n")
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=folder, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await send_log(line.decode("utf-8", errors="replace"))
        return await proc.wait()

    if await run(["docker", "compose", "-f", str(target), "config", "-q"]) != 0:
        target.rename(target.with_suffix(".yml.failed"))
        return {"ok": False, "error": "The generated docker-compose.yml is not valid"}

    backup_name = f"{container_name}-pre-compose-{int(time.time())}"
    await send_log(f"==> Stopping the old container and keeping it as {backup_name}\n")
    try:
        await asyncio.to_thread(old.stop, timeout=20)
        await asyncio.to_thread(old.rename, backup_name)
    except Exception as exc:
        await send_log(f"[ERROR] {exc}\n")
        target.rename(target.with_suffix(".yml.failed"))
        if was_running:
            await asyncio.to_thread(old.start)
        return {"ok": False, "error": str(exc)}

    rc = await run(["docker", "compose", "-f", str(target), "up", "-d"])
    healthy, reason = (False, f"docker compose up failed (exit {rc})")
    if rc == 0:
        await send_log("==> Checking the new container...\n")
        healthy, reason = await _wait_healthy(container_name, send_log, 30)
    await send_log(f"==> {reason}\n")

    if healthy:
        try:
            await asyncio.to_thread(old.remove, v=False)
            await send_log(f"==> Removed the old container {backup_name} (volumes and data kept)\n")
        except Exception as exc:
            await send_log(f"[WARN] Could not remove {backup_name}: {exc}\n")
        await send_log(f"\n✅ {container_name} is now managed by {target}\n")
        return {"ok": True, "compose_path": str(target)}

    await send_log(await asyncio.to_thread(_diagnostics_sync, container_name, 40))
    await send_log("==> Rolling back to the original container...\n")
    await run(["docker", "compose", "-f", str(target), "down"])
    try:
        await asyncio.to_thread(old.rename, container_name)
        if was_running:
            await asyncio.to_thread(old.start)
        await send_log("==> Original container restored\n")
    except Exception as exc:
        await send_log(f"[ERROR] Could not restore the original container: {exc}\n")
    target.rename(target.with_suffix(".yml.failed"))
    return {"ok": False, "error": reason}
