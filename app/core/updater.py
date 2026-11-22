import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ruamel.yaml import YAML

from app.core.database import add_update_history, get_setting
from app.core.docker_client import get_app_by_name, get_docker_client, list_all_apps
from app.core.registry_checker import check_one_app_by_name

LogCallback = Callable[[str], Awaitable[None]]
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def _run_cmd_stream(
    cmd: list[str], cwd: str, send_log: LogCallback
) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
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


def _prune_old_image_sync(old_image_id: str, new_image_id: str) -> str:
    if not old_image_id or old_image_id == new_image_id:
        return ""
    try:
        client = get_docker_client()
        client.images.remove(image=old_image_id, force=False)
        return f"Removed unused old image {old_image_id[:19]}"
    except Exception:
        return ""


def _split_image_ref(ref: str) -> tuple[str, str]:
    """'ghcr.io/a/b:tag' -> ('ghcr.io/a/b', 'tag'); không có tag -> 'latest'. Digest (@sha256) -> ('', '')."""
    if not ref or "@" in ref:
        return "", ""
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = ref.rsplit(":", 1)
        return repo, tag
    return ref, "latest"


def _probe_container_sync(name: str) -> dict[str, Any]:
    client = get_docker_client()
    c = client.containers.get(name)
    c.reload()
    st = c.attrs.get("State", {}) or {}
    health = ((st.get("Health") or {}).get("Status")) or ""
    return {
        "id": c.id,
        "status": st.get("Status", ""),
        "restarting": bool(st.get("Restarting")),
        "exit_code": st.get("ExitCode", 0),
        "restart_count": c.attrs.get("RestartCount", 0) or 0,
        "health": health,
    }


async def _wait_healthy(
    name: str, send_log: LogCallback, window: int, baseline: Optional[dict] = None
) -> tuple[bool, str]:
    """
    Theo dõi container mới trong `window` giây. Coi là hỏng nếu: thoát với mã lỗi, đang restart liên tục,
    RestartCount tăng, hoặc healthcheck báo unhealthy. Có healthcheck 'healthy' thì kết luận ngay.
    """
    waited = 0
    last = ""
    while waited <= window:
        try:
            info = await asyncio.to_thread(_probe_container_sync, name)
        except Exception as exc:
            return False, f"Container not found after update ({exc})"
        last = info["status"]
        if info["health"] == "unhealthy":
            return False, "Healthcheck reports unhealthy"
        # Chỉ tính các lần restart xảy ra SAU khi cập nhật (container cũ có thể đã từng restart từ trước)
        base_count = baseline["restart_count"] if baseline and baseline.get("id") == info["id"] else 0
        if info["restarting"] or info["restart_count"] > base_count:
            return False, f"Container keeps restarting (count={info['restart_count']})"
        if info["status"] in ("exited", "dead"):
            if info["exit_code"] == 0:
                return True, "Container finished with exit code 0"
            return False, f"Container exited with code {info['exit_code']}"
        if info["health"] == "healthy":
            return True, "Healthcheck is healthy"
        await asyncio.sleep(3)
        waited += 3
    return (last == "running"), (f"Status after {window}s: {last}")


def _retag_image_sync(old_image_id: str, image_ref: str) -> str:
    repo, tag = _split_image_ref(image_ref)
    if not repo:
        return "Image is pinned by digest; cannot retag"
    client = get_docker_client()
    img = client.images.get(old_image_id)
    img.tag(repo, tag=tag)
    return ""


async def _rollback_to_previous(
    *,
    compose_path: str,
    compose_dir: str,
    service: str,
    container_name: str,
    image_ref: str,
    old_image_id: str,
    bumped: bool,
    backup_path: str,
    send_log: LogCallback,
    window: int,
) -> tuple[bool, str]:
    await send_log("\n==> New version is unhealthy. Rolling back to the previous version...\n")
    if bumped and backup_path:
        await asyncio.to_thread(_restore_compose_backup, compose_path, backup_path)
        await send_log("==> Restored docker-compose.yml from backup.\n")
    elif old_image_id:
        try:
            err = await asyncio.to_thread(_retag_image_sync, old_image_id, image_ref)
        except Exception as exc:
            err = str(exc)
        if err:
            await send_log(f"[ERROR] Cannot restore previous image: {err}\n")
            return False, err
        await send_log(f"==> Previous image {old_image_id[:19]} re-tagged as {image_ref}\n")
    else:
        return False, "Previous image is unknown"

    cmd = ["docker", "compose", "-f", compose_path, "up", "-d", "--force-recreate", "--no-deps"]
    if service:
        cmd.append(service)
    await send_log(f"$ {' '.join(cmd)}\n")
    rc = await _run_cmd_stream(cmd, compose_dir, send_log)
    if rc != 0:
        return False, f"Rollback up failed (exit {rc})"
    ok, reason = await _wait_healthy(container_name, send_log, window)
    return ok, reason


def _trigger_self_update_helper(compose_path: str) -> None:
    compose_dir = str(Path(compose_path).parent)
    client = get_docker_client()
    try:
        old = client.containers.get("appmanager-pro-self-updater")
        old.remove(force=True)
    except Exception:
        pass
    client.containers.run(
        image="docker:27-cli",
        command=[
            "sh",
            "-c",
            f"sleep 2 && docker compose -f '{compose_path}' pull && docker compose -f '{compose_path}' up -d",
        ],
        remove=True,
        detach=True,
        volumes={
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            compose_dir: {"bind": compose_dir, "mode": "rw"},
        },
        name="appmanager-pro-self-updater",
    )


def _bump_compose_image_tag(
    compose_path: str,
    service_name: str,
    container_name: str,
    old_image: str,
    new_tag: str,
) -> tuple[bool, str, str, str]:
    """
    Nâng tag mới vào docker-compose.yml bằng ruamel.yaml (bảo toàn comment & x-casaos).
    Trả về: (đã_đổi, image_mới, đường_dẫn_backup, thông_báo_lỗi)
    """
    path = Path(compose_path)
    backup_path = path.with_name(path.name + ".bak")
    original_text = path.read_text(encoding="utf-8")

    ryaml = YAML()
    ryaml.preserve_quotes = True
    data = ryaml.load(original_text) or {}
    services = data.get("services") or {}

    target_svc = None
    if service_name and service_name in services:
        target_svc = services[service_name]
    else:
        for svc_cfg in services.values():
            if isinstance(svc_cfg, dict) and (
                svc_cfg.get("container_name") == container_name
                or svc_cfg.get("image") == old_image
            ):
                target_svc = svc_cfg
                break

    if not isinstance(target_svc, dict) or "image" not in target_svc:
        return False, "", "", "Could not locate service image in docker-compose.yml"

    cur_img = str(target_svc["image"]).strip()
    if "$" in cur_img:
        return False, cur_img, "", "Image tag uses an env variable; please edit compose manually."

    base_img = cur_img.split("@sha256:", 1)[0]
    last_slash = base_img.rfind("/")
    last_colon = base_img.rfind(":")
    repo_part = base_img[:last_colon] if last_colon > last_slash else base_img
    new_img = f"{repo_part}:{new_tag}"

    if new_img == cur_img:
        return False, cur_img, "", ""

    backup_path.write_text(original_text, encoding="utf-8")
    target_svc["image"] = new_img
    with path.open("w", encoding="utf-8") as f:
        ryaml.dump(data, f)

    return True, new_img, str(backup_path), ""


def _restore_compose_backup(compose_path: str, backup_path: str) -> None:
    if backup_path and Path(backup_path).exists():
        Path(compose_path).write_text(
            Path(backup_path).read_text(encoding="utf-8"), encoding="utf-8"
        )


_UPDATE_LOCKS: dict[str, asyncio.Lock] = {}


async def update_app_stream(
    container_name: str,
    send_log: LogCallback,
    mode: str = "manual",
) -> dict:
    """Mỗi app chỉ được cập nhật 1 tiến trình tại một thời điểm (tay / tự động / Update All)."""
    lock = _UPDATE_LOCKS.setdefault(container_name, asyncio.Lock())
    if lock.locked():
        msg = "This app is already being updated. Please wait for it to finish."
        await send_log(f"[ERROR] {msg}\n")
        return {"ok": False, "error": msg}
    async with lock:
        return await _update_app_stream_impl(container_name, send_log, mode)


async def _update_app_stream_impl(
    container_name: str,
    send_log: LogCallback,
    mode: str = "manual",
) -> dict:
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        await send_log(f"[ERROR] Container '{container_name}' not found.\n")
        return {"ok": False, "error": "Container not found"}

    compose_path = app_info.get("compose_path") or ""
    if not compose_path or not Path(compose_path).exists():
        msg = "No accessible docker-compose.yml found for this container."
        await send_log(f"[ERROR] {msg}\n")
        return {"ok": False, "error": msg}

    title = app_info["title"]
    from_ver = app_info.get("version") or ""
    target_tag = app_info.get("target_tag") or ""
    target_ver = app_info.get("remote_version") or target_tag or "latest"
    old_image_id = app_info.get("image_id") or ""
    compose_dir = str(Path(compose_path).parent)
    service = app_info.get("service") or ""

    # Nếu app đang ghim cứng tag -> sao lưu .bak và nâng tag trong docker-compose.yml
    bumped = False
    backup_path = ""
    if target_tag:
        bumped, new_img, backup_path, bump_err = await asyncio.to_thread(
            _bump_compose_image_tag,
            compose_path,
            service,
            container_name,
            app_info["image"],
            target_tag,
        )
        if bump_err:
            await send_log(f"[ERROR] {bump_err}\n")
            return {"ok": False, "error": bump_err}
        if bumped:
            await send_log(f"==> Backup created: {backup_path}\n")
            await send_log(f"==> Updated compose image: {app_info['image']} -> {new_img}\n\n")

    # Xử lý riêng nếu đang tự cập nhật chính AppManager Pro
    if app_info.get("is_self"):
        await send_log(f"==> Detected self-update for {title}.\n")
        await send_log("==> Launching detached helper container to pull & recreate...\n")
        try:
            await asyncio.to_thread(_trigger_self_update_helper, compose_path)
            add_update_history(
                container_name, title, from_ver, target_ver, mode, "success", "Self-update triggered"
            )
            await send_log("==> Helper launched! AppManager Pro will restart in ~10 seconds.\n")
            await send_log("__SELF_UPDATE_RELOAD__\n")
            return {"ok": True, "self_update": True, "to_version": target_ver}
        except Exception as exc:
            if bumped and backup_path:
                await asyncio.to_thread(_restore_compose_backup, compose_path, backup_path)
                await send_log("==> Rolled back docker-compose.yml from backup.\n")
            await send_log(f"[ERROR] Self-update failed: {exc}\n")
            add_update_history(
                container_name, title, from_ver, target_ver, mode, "failed", str(exc)
            )
            return {"ok": False, "error": str(exc)}

    await send_log(f"==> Updating {title} ({container_name})\n")
    await send_log(f"==> Compose file: {compose_path}\n\n")

    # Sao lưu dữ liệu app trước khi cập nhật (tuỳ chọn trong Settings)
    backup_name = ""
    if get_setting("backup_before_update", "false").lower() == "true" and app_info.get("appdata_path"):
        from app.core.app_backup import create_backup

        await send_log(f"==> Backing up app data: {app_info['appdata_path']} ...\n")
        try:
            max_mb = int(get_setting("backup_max_mb", "2048") or 2048)
            keep = int(get_setting("backup_keep", "3") or 3)
        except ValueError:
            max_mb, keep = 2048, 3
        bres = await asyncio.to_thread(
            create_backup, container_name, app_info["appdata_path"], from_ver, max_mb, keep
        )
        if bres.get("ok"):
            backup_name = bres["file"]
            await send_log(f"==> {bres['message']} ({bres.get('size', '')})\n\n")
        else:
            await send_log(f"==> [WARN] {bres.get('message')} — continuing without data backup.\n\n")

    # Ghi nhận trạng thái container trước khi cập nhật (để kiểm tra sức khoẻ chính xác)
    try:
        baseline = await asyncio.to_thread(_probe_container_sync, container_name)
    except Exception:
        baseline = None

    # Bước 1: docker compose pull
    pull_cmd = ["docker", "compose", "-f", compose_path, "pull"]
    if service:
        pull_cmd.append(service)
    await send_log(f"$ {' '.join(pull_cmd)}\n")
    rc = await _run_cmd_stream(pull_cmd, compose_dir, send_log)
    if rc != 0:
        if bumped and backup_path:
            await asyncio.to_thread(_restore_compose_backup, compose_path, backup_path)
            await send_log("==> Rolled back docker-compose.yml from backup.\n")
        await send_log(f"\n[ERROR] docker compose pull failed (exit {rc}).\n")
        add_update_history(
            container_name, title, from_ver, target_ver, mode, "failed", f"Pull exit {rc}"
        )
        return {"ok": False, "error": f"Pull failed (exit {rc})"}

    # Bước 2: docker compose up -d
    up_cmd = ["docker", "compose", "-f", compose_path, "up", "-d", "--remove-orphans"]
    if service:
        up_cmd.append(service)
    await send_log(f"\n$ {' '.join(up_cmd)}\n")
    rc2 = await _run_cmd_stream(up_cmd, compose_dir, send_log)
    if rc2 != 0:
        if bumped and backup_path:
            await asyncio.to_thread(_restore_compose_backup, compose_path, backup_path)
            await send_log("==> Rolled back docker-compose.yml from backup.\n")
        await send_log(f"\n[ERROR] docker compose up failed (exit {rc2}).\n")
        add_update_history(
            container_name, title, from_ver, target_ver, mode, "failed", f"Up exit {rc2}"
        )
        return {"ok": False, "error": f"Recreate failed (exit {rc2})"}

    # Bước 3: Kiểm tra sức khoẻ container mới; hỏng thì tự quay về bản cũ
    try:
        window = max(10, min(120, int(get_setting("health_wait_seconds", "25"))))
    except Exception:
        window = 25
    await send_log(f"\n==> Checking the new container for {window}s...\n")
    healthy, reason = await _wait_healthy(container_name, send_log, window, baseline)
    await send_log(f"==> {reason}\n")

    rolled_back = False
    if not healthy and get_setting("auto_rollback", "true").lower() == "true":
        rb_ok, rb_reason = await _rollback_to_previous(
            compose_path=compose_path, compose_dir=compose_dir, service=service,
            container_name=container_name, image_ref=app_info["image"],
            old_image_id=old_image_id, bumped=bumped, backup_path=backup_path,
            send_log=send_log, window=window,
        )
        if rb_ok:
            rolled_back = True
            await send_log("\n↩️ Rolled back: the previous version is running again.\n")
            if backup_name:
                await send_log(
                    f"==> A data backup from before this update is available ({backup_name}). "
                    "Restore it from Settings → Storage → App data backups if the new version changed your data.\n"
                )
            add_update_history(
                container_name, title, from_ver, target_ver, mode, "rolled_back",
                f"Update failed ({reason}); previous version restored",
            )
            await check_one_app_by_name(container_name)
            return {"ok": False, "error": f"Update failed ({reason}); rolled back to {from_ver or 'previous version'}"}
        await send_log(f"\n[ERROR] Rollback failed: {rb_reason}\n")

    refreshed = await asyncio.to_thread(get_app_by_name, container_name)
    new_ver = refreshed["version"] if refreshed else target_ver
    new_image_id = refreshed["image_id"] if refreshed else ""
    new_status = refreshed["status"] if refreshed else "unknown"

    # Chỉ xoá image cũ khi bản mới đã chạy ổn (để còn đường quay về)
    if healthy and get_setting("prune_old_images", "true").lower() == "true":
        prune_msg = await asyncio.to_thread(_prune_old_image_sync, old_image_id, new_image_id)
        if prune_msg:
            await send_log(f"\n==> {prune_msg}\n")

    # Bước 4: Cập nhật lại cache digest
    await send_log("==> Refreshing update status...\n")
    await check_one_app_by_name(container_name)

    final_status = "success" if (healthy and new_status in ("running", "exited")) else "failed"
    add_update_history(
        container_name,
        title,
        from_ver,
        new_ver,
        mode,
        final_status,
        f"Container status: {new_status}",
    )

    if final_status == "success":
        await send_log(f"\n✅ {title} updated successfully ({from_ver} -> {new_ver})!\n")
        return {"ok": True, "from_version": from_ver, "to_version": new_ver}
    else:
        await send_log(f"\n⚠️ Container status after update: {new_status}. Check Live Logs.\n")
        return {"ok": False, "error": f"Status is {new_status}"}


async def update_all_apps_stream(send_event: EventCallback) -> None:
    """Cập nhật tuần tự toàn bộ app có bản mới; luôn đẩy self-update xuống cuối cùng."""
    data = await asyncio.to_thread(list_all_apps, True)
    candidates = [a for a in data["apps"] if a["has_update"] and a["can_update"]]

    regular = [a for a in candidates if not a["is_self"]]
    self_apps = [a for a in candidates if a["is_self"]]
    ordered = regular + self_apps

    await send_event(
        {
            "type": "init",
            "apps": [
                {
                    "name": a["name"],
                    "title": a["title"],
                    "icon": a["icon"],
                    "from_version": a["version"],
                    "to_version": a["remote_version"] or "latest",
                    "is_self": a["is_self"],
                    "status": "pending",
                }
                for a in ordered
            ],
        }
    )

    if not ordered:
        await send_event({"type": "complete", "succeeded": 0, "failed": 0, "self_update": False})
        return

    succeeded = 0
    failed = 0
    self_triggered = False

    async def forward_log(text: str) -> None:
        await send_event({"type": "log", "text": text})

    for idx, app_item in enumerate(ordered):
        await send_event({"type": "app_start", "index": idx, "name": app_item["name"]})
        await send_event(
            {
                "type": "log",
                "text": f"\n========== [{idx + 1}/{len(ordered)}] {app_item['title']} ==========\n",
            }
        )
        res = await update_app_stream(app_item["name"], forward_log, mode="batch")
        ok = bool(res.get("ok"))
        if ok:
            succeeded += 1
        else:
            failed += 1
        if res.get("self_update"):
            self_triggered = True

        await send_event(
            {
                "type": "app_done",
                "index": idx,
                "name": app_item["name"],
                "ok": ok,
                "to_version": res.get("to_version") or app_item["remote_version"],
                "error": res.get("error") or "",
            }
        )

    await send_event(
        {
            "type": "complete",
            "succeeded": succeeded,
            "failed": failed,
            "self_update": self_triggered,
        }
    )
