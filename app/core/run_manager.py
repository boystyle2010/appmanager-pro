"""
Quản lý trực tiếp container tạo bằng `docker run` (không có file compose).

Container chính là nguồn cấu hình. Cập nhật / đổi phiên bản = tạo lại container với CÙNG cấu hình, chỉ khác image:
  1. đọc cấu hình (docker inspect) + lưu "bản cấu hình chạy tốt" vào <data>/run-snapshots/<tên>.json
  2. tải image mới
  3. dừng container cũ và đổi tên thành <tên>-amp-old (KHÔNG xoá)
  4. tạo container mới cùng tên, cùng cấu hình; nối lại các mạng phụ; chạy
  5. kiểm tra sức khoẻ -> ổn: xoá container cũ (giữ volume); hỏng: xoá container mới, trả tên + chạy lại container cũ

Chỉ giữ những gì người dùng tự đặt: biến môi trường / lệnh / nhãn / healthcheck... mặc định của image cũ được bỏ ra để
image mới dùng giá trị mặc định mới (vd biến VERSION của image không bị ghim ở bản cũ).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.core.database import DATA_DIR

logger = logging.getLogger(__name__)
LogCallback = Callable[[str], Awaitable[None]]

SNAPSHOT_DIR = DATA_DIR / "run-snapshots"
OLD_SUFFIX = "-amp-old"
_DEFAULT_NETWORKS = {"bridge", "host", "none", "default"}

# Container do công cụ khác quản lý: AppManager chỉ xem / chạy / dừng, không tự tạo lại (công cụ kia sẽ ghi đè)
_EXTERNAL_LABEL_PREFIXES = (
    "com.docker.swarm.", "io.kubernetes.", "io.portainer.agent", "net.unraid.docker.", "com.synology.",
    "io.balena.", "io.rancher.", "org.nomadproject.",
)
_HELPER_LABEL = "appmanager-pro.helper"


def manage_kind(labels: dict[str, str]) -> str:
    """"compose" | "run" | "external" | "helper" — cách AppManager quản lý container này."""
    labels = labels or {}
    if labels.get("com.docker.compose.project"):
        return "compose"
    if labels.get(_HELPER_LABEL):
        return "helper"
    if any(k.startswith(_EXTERNAL_LABEL_PREFIXES) for k in labels):
        return "external"
    return "run"


# ---------------------------------------------------------------- dựng cấu hình tạo container
def _user_list(values: Optional[list], image_values: Optional[list]) -> Optional[list]:
    """Giữ giá trị khi người dùng tự đặt (khác mặc định image cũ); None = để image mới dùng mặc định của nó."""
    if values and values != image_values:
        return list(values)
    return None


def build_create_config(attrs: dict[str, Any], old_image_cfg: dict[str, Any], image_ref: str) -> dict[str, Any]:
    """Body cho POST /containers/create từ kết quả docker inspect của container cũ."""
    cfg = attrs.get("Config") or {}
    host = copy.deepcopy(attrs.get("HostConfig") or {})
    cid = attrs.get("Id") or ""

    body: dict[str, Any] = {"Image": image_ref}
    # Hostname mặc định = 12 ký tự đầu của ID -> để Docker tự đặt lại; chỉ giữ khi người dùng đặt (--hostname)
    if cfg.get("Hostname") and not cid.startswith(cfg["Hostname"]):
        body["Hostname"] = cfg["Hostname"]
    for key in ("Domainname", "Tty", "OpenStdin", "StdinOnce", "StopTimeout"):
        if cfg.get(key):
            body[key] = cfg[key]
    for key in ("User", "WorkingDir", "StopSignal"):
        if cfg.get(key) and cfg.get(key) != old_image_cfg.get(key):
            body[key] = cfg[key]

    img_env = set(old_image_cfg.get("Env") or [])
    env = [e for e in (cfg.get("Env") or []) if e not in img_env]
    if env:
        body["Env"] = env
    for key in ("Cmd", "Entrypoint"):
        val = _user_list(cfg.get(key), old_image_cfg.get(key))
        if val is not None:
            body[key] = val
    if cfg.get("Healthcheck") and cfg.get("Healthcheck") != old_image_cfg.get("Healthcheck"):
        body["Healthcheck"] = cfg["Healthcheck"]

    img_labels = old_image_cfg.get("Labels") or {}
    labels = {k: v for k, v in (cfg.get("Labels") or {}).items() if img_labels.get(k) != v}
    if labels:
        body["Labels"] = labels
    img_ports = set((old_image_cfg.get("ExposedPorts") or {}).keys())
    exposed = {p: {} for p in (cfg.get("ExposedPorts") or {}) if p not in img_ports}
    exposed.update({p: {} for p in (host.get("PortBindings") or {})})
    if exposed:
        body["ExposedPorts"] = exposed

    # Volume ẩn danh (VOLUME trong image) không nằm trong Binds -> gắn lại theo tên để giữ dữ liệu
    binds = list(host.get("Binds") or [])
    bound = {b.split(":")[1] for b in binds if b.count(":") >= 1}
    bound |= {m.get("Target") for m in (host.get("Mounts") or [])}
    for m in attrs.get("Mounts") or []:
        if m.get("Type") == "volume" and m.get("Name") and m.get("Destination") not in bound:
            binds.append(f"{m['Name']}:{m['Destination']}" + ("" if m.get("RW", True) else ":ro"))
    host["Binds"] = binds or None
    body["HostConfig"] = host

    # Mạng chính đi kèm lúc tạo; mạng phụ nối sau (Docker chỉ nhận 1 endpoint khi tạo với API cũ)
    nets = ((attrs.get("NetworkSettings") or {}).get("Networks") or {})
    mode = host.get("NetworkMode") or "default"
    primary = mode if mode in nets else (next(iter(nets)) if nets and not mode.startswith("container:") else "")
    endpoints: dict[str, Any] = {}
    for name, ep in nets.items():
        endpoints[name] = _endpoint(ep, cid)
    if primary and not mode.startswith("container:") and mode not in ("host", "none"):
        body["NetworkingConfig"] = {"EndpointsConfig": {primary: endpoints[primary]}}
    extra = {n: e for n, e in endpoints.items() if n != primary and mode not in ("host", "none") and not mode.startswith("container:")}
    return {"body": body, "extra_networks": extra}


def _endpoint(ep: dict[str, Any], cid: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ep.get("IPAMConfig"):
        out["IPAMConfig"] = ep["IPAMConfig"]
    # Alias tự sinh = ID ngắn của container cũ -> bỏ
    aliases = [a for a in (ep.get("Aliases") or []) if a and not cid.startswith(a)]
    if aliases:
        out["Aliases"] = aliases
    if ep.get("Links"):
        out["Links"] = ep["Links"]
    if ep.get("DriverOpts"):
        out["DriverOpts"] = ep["DriverOpts"]
    if ep.get("MacAddress") and ep.get("IPAMConfig"):
        out["MacAddress"] = ep["MacAddress"]  # chỉ giữ MAC khi container dùng địa chỉ tĩnh (macvlan...)
    return out


def docker_run_command(attrs: dict[str, Any], old_image_cfg: dict[str, Any]) -> str:
    """Lệnh `docker run` tương đương (để xem / chép) — dựng từ cùng cấu hình dùng khi tạo lại."""
    import shlex

    built = build_create_config(attrs, old_image_cfg, (attrs.get("Config") or {}).get("Image") or "")["body"]
    host = built.get("HostConfig") or {}
    name = (attrs.get("Name") or "").lstrip("/")
    parts = ["docker", "run", "-d", "--name", name]
    rp = host.get("RestartPolicy") or {}
    if rp.get("Name") and rp["Name"] != "no":
        parts += ["--restart", rp["Name"] + (f":{rp['MaximumRetryCount']}" if rp.get("MaximumRetryCount") else "")]
    mode = host.get("NetworkMode") or ""
    if mode and mode not in ("default", "bridge"):
        parts += ["--network", mode]
    for cport, binds in sorted((host.get("PortBindings") or {}).items()):
        num, _, proto = cport.partition("/")
        for b in binds or []:
            hip = b.get("HostIp") or ""
            hp = b.get("HostPort") or ""
            spec = (f"{hip}:" if hip and hip not in ("0.0.0.0", "::") else "") + (f"{hp}:" if hp else "") + num
            parts += ["-p", spec + ("" if proto in ("", "tcp") else f"/{proto}")]
    for b in host.get("Binds") or []:
        parts += ["-v", b]
    for e in built.get("Env") or []:
        parts += ["-e", e]
    for d in host.get("Devices") or []:
        parts += ["--device", f"{d.get('PathOnHost')}:{d.get('PathInContainer')}"]
    if host.get("Privileged"):
        parts.append("--privileged")
    for c in host.get("CapAdd") or []:
        parts += ["--cap-add", c]
    for k, v in (built.get("Labels") or {}).items():
        parts += ["-l", f"{k}={v}"]
    if built.get("Hostname"):
        parts += ["--hostname", built["Hostname"]]
    if built.get("Entrypoint"):
        parts += ["--entrypoint", " ".join(built["Entrypoint"])]
    parts.append(built.get("Image") or "")
    parts += list(built.get("Cmd") or [])
    return " ".join(shlex.quote(p) for p in parts)


# ---------------------------------------------------------------- bản cấu hình chạy tốt
def save_snapshot(name: str, attrs: dict[str, Any], image_cfg: dict[str, Any]) -> None:
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        data = {"saved": int(time.time()), "attrs": attrs, "image_config": image_cfg}
        tmp = SNAPSHOT_DIR / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(SNAPSHOT_DIR / f"{name}.json")
    except Exception:
        logger.exception("Cannot save run snapshot of %s", name)


def load_snapshot(name: str) -> Optional[dict[str, Any]]:
    try:
        return json.loads((SNAPSHOT_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- tạo lại container
def _client():
    from app.core.docker_client import get_docker_client

    return get_docker_client()


def _create_sync(name: str, built: dict[str, Any]) -> str:
    client = _client()
    api = client.api
    res = api._result(api._post_json(api._url("/containers/create"), data=built["body"], params={"name": name}), True)
    cid = res["Id"]
    for net, ep in built["extra_networks"].items():
        api.connect_container_to_network(
            cid, net, aliases=ep.get("Aliases"), links=ep.get("Links"),
            ipv4_address=(ep.get("IPAMConfig") or {}).get("IPv4Address"),
            ipv6_address=(ep.get("IPAMConfig") or {}).get("IPv6Address"),
            driver_opt=ep.get("DriverOpts"),
        )
    return cid


async def _stream(cmd: list[str], send_log: LogCallback) -> int:
    await send_log("$ " + " ".join(cmd) + "\n")
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        await send_log(line.decode("utf-8", errors="replace"))
    return await proc.wait()


def _dependents_sync(name: str, cid: str) -> list[tuple[str, str]]:
    """Container dùng chung mạng với container này (--network container:<tên|id>): [(tên, kiểu quản lý)]."""
    out = []
    for c in _client().containers.list(all=True):
        mode = ((c.attrs.get("HostConfig") or {}).get("NetworkMode") or "")
        if mode in (f"container:{cid}", f"container:{name}") and c.name != name:
            out.append((c.name, manage_kind((c.attrs.get("Config") or {}).get("Labels") or {})))
    return out


async def recreate_stream(
    name: str, image_ref: str, send_log: LogCallback, *, window: int = 25, pull: bool = True,
    force: bool = False, auto_rollback: bool = True, network_mode: str = "",
) -> dict[str, Any]:
    """
    Tạo lại container `name` bằng image `image_ref` (cùng cấu hình). Trả về
    {"ok", "changed", "rolled_back", "reason", "old_image_id", "new_image_id"}.
    """
    from app.core.updater import _diagnostics_sync, _wait_healthy

    client = _client()
    try:
        old = await asyncio.to_thread(client.containers.get, name)
    except Exception as exc:
        return {"ok": False, "reason": f"Container not found ({exc})"}
    attrs = old.attrs or {}
    if manage_kind((attrs.get("Config") or {}).get("Labels") or {}) != "run":
        return {"ok": False, "reason": "This container is not a docker run container managed by AppManager"}
    old_image_id = attrs.get("Image") or ""
    try:
        old_image_cfg = (await asyncio.to_thread(client.images.get, old_image_id)).attrs.get("Config") or {}
    except Exception:
        old_image_cfg = {}
    await asyncio.to_thread(save_snapshot, name, attrs, old_image_cfg)

    if pull:
        rc = await _stream(["docker", "pull", image_ref], send_log)
        if rc != 0:
            return {"ok": False, "reason": f"docker pull failed (exit {rc}); nothing was changed"}
    try:
        new_image = await asyncio.to_thread(client.images.get, image_ref)
    except Exception as exc:
        return {"ok": False, "reason": f"Image {image_ref} is not available ({exc}); nothing was changed"}
    if new_image.id == old_image_id and not force:
        await send_log("==> The container already runs this image; nothing to do.\n")
        return {"ok": True, "changed": False, "old_image_id": old_image_id, "new_image_id": new_image.id}

    built = build_create_config(attrs, old_image_cfg, image_ref)
    if network_mode:  # container phụ dùng chung mạng: trỏ sang container chính MỚI
        built["body"]["HostConfig"]["NetworkMode"] = network_mode
    if (built["body"]["HostConfig"].get("NetworkMode") or "").startswith("container:"):
        # Dùng chung mạng của container khác: Docker không cho đặt hostname / cổng / DNS riêng
        for k in ("Hostname", "Domainname", "ExposedPorts", "NetworkingConfig"):
            built["body"].pop(k, None)
        for k in ("PortBindings", "Dns", "DnsOptions", "DnsSearch", "ExtraHosts", "PublishAllPorts", "Links"):
            built["body"]["HostConfig"].pop(k, None)
        built["extra_networks"] = {}
    dependents = await asyncio.to_thread(_dependents_sync, name, attrs.get("Id") or "")
    was_running = (attrs.get("State") or {}).get("Running", False)
    backup_name = f"{name}{OLD_SUFFIX}"
    try:  # còn sót container -amp-old của lần trước (vd mất điện giữa chừng) -> xoá trước
        stale = await asyncio.to_thread(client.containers.get, backup_name)
        await asyncio.to_thread(stale.remove, force=True)
    except Exception:
        pass

    stop_timeout = int((attrs.get("Config") or {}).get("StopTimeout") or 20)
    await send_log(f"==> Stopping {name} and keeping it as {backup_name} until the new container works\n")
    try:
        if was_running:
            await asyncio.to_thread(old.stop, timeout=stop_timeout)
        await asyncio.to_thread(old.rename, backup_name)
    except Exception as exc:
        if was_running:
            try:
                await asyncio.to_thread(old.start)
            except Exception:
                pass
        return {"ok": False, "reason": f"Cannot stop / rename the container: {exc}"}

    new_id = ""
    try:
        await send_log(f"==> Creating {name} from {image_ref} with the same settings\n")
        new_id = await asyncio.to_thread(_create_sync, name, built)
        if was_running:
            await asyncio.to_thread(client.api.start, new_id)
        healthy, reason = (True, "Container created (it was stopped before, so it is left stopped)")
        if was_running:
            await send_log(f"==> Checking the new container for {window}s...\n")
            healthy, reason = await _wait_healthy(name, send_log, window, None)
    except Exception as exc:
        healthy, reason = False, f"Cannot create/start the new container: {str(exc)[:300]}"
    await send_log(f"==> {reason}\n")

    if healthy:
        try:
            await asyncio.to_thread(old.remove, v=False)
            await send_log(f"==> Removed {backup_name} (volumes and data kept)\n")
        except Exception as exc:
            await send_log(f"[WARN] Could not remove {backup_name}: {exc}\n")
        try:
            new_c = await asyncio.to_thread(client.containers.get, name)
            await asyncio.to_thread(save_snapshot, name, new_c.attrs, new_image.attrs.get("Config") or {})
        except Exception:
            pass
        # Container dùng chung mạng (--network container:<tên>) vẫn trỏ vào container CŨ -> tạo lại để nối vào container mới
        for dep, kind in dependents:
            if kind != "run":
                await send_log(f"[WARN] {dep} shares this container's network but is managed by {kind}; recreate it so it "
                               "joins the new container\n")
                continue
            await send_log(f"==> {dep} shares this container's network; recreating it to join the new container\n")
            try:
                dep_img = (await asyncio.to_thread(client.containers.get, dep)).attrs["Config"]["Image"]
                d = await recreate_stream(dep, dep_img, send_log, window=min(window, 15), pull=False, force=True,
                                          auto_rollback=auto_rollback, network_mode=f"container:{name}")
                await send_log(f"==> {dep}: {'ok' if d.get('ok') else d.get('reason')}\n")
            except Exception as exc:
                await send_log(f"[WARN] Could not recreate {dep}: {exc}\n")
        return {"ok": True, "changed": True, "reason": reason, "old_image_id": old_image_id, "new_image_id": new_image.id}

    if new_id:
        try:
            await send_log(await asyncio.to_thread(_diagnostics_sync, name, 40))
        except Exception:
            pass
    if not auto_rollback:
        await send_log("==> Automatic rollback is disabled; the previous container is kept as "
                       f"{backup_name} (stopped).\n")
        return {"ok": False, "rolled_back": False, "reason": reason, "old_image_id": old_image_id}
    await send_log("==> Rolling back to the previous container...\n")
    try:
        if new_id:
            await asyncio.to_thread(client.api.remove_container, new_id, force=True)
        await asyncio.to_thread(old.rename, name)
        if was_running:
            await asyncio.to_thread(old.start)
            ok, why = await _wait_healthy(name, send_log, window, None)
            await send_log(f"==> Previous container: {why}\n")
            if not ok:
                return {"ok": False, "rolled_back": False, "reason": f"{reason}; previous container: {why}"}
        return {"ok": False, "rolled_back": True, "reason": reason, "old_image_id": old_image_id}
    except Exception as exc:
        return {"ok": False, "rolled_back": False, "reason": f"{reason}; rollback failed: {exc}"}


def image_ref_with_tag(image_ref: str, tag: str) -> str:
    if not tag:
        return image_ref
    base = image_ref.split("@", 1)[0]
    last = base.rsplit("/", 1)[-1]
    repo = base.rsplit(":", 1)[0] if ":" in last else base
    return f"{repo}:{tag}"
