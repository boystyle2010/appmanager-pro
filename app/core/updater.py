import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ruamel.yaml import YAML

from app.core.database import (
    DATA_DIR,
    add_update_history,
    attach_update_log,
    get_last_update_history_id,
    get_setting,
)
from app.core.compose_snapshot import rollback_compose_text, save_good
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


def _diagnostics_sync(name: str, tail: int = 60) -> str:
    """Kết quả healthcheck gần nhất + log cuối của container — lưu lại trước khi rollback xoá mất nó."""
    client = get_docker_client()
    c = client.containers.get(name)
    c.reload()
    st = c.attrs.get("State", {}) or {}
    out = [
        f"--- Container state: status={st.get('Status')} exit_code={st.get('ExitCode')} "
        f"restarts={c.attrs.get('RestartCount', 0)} error={st.get('Error') or '-'}"
    ]
    for entry in ((st.get("Health") or {}).get("Log") or [])[-3:]:
        msg = str(entry.get("Output") or "").strip() or "(no output)"
        out.append(f"--- Healthcheck exit {entry.get('ExitCode')}: {msg[:500]}")
    try:
        logs = c.logs(tail=tail, timestamps=False).decode("utf-8", errors="replace").rstrip()
    except Exception as exc:
        logs = f"(cannot read logs: {exc})"
    out.append(f"--- Last {tail} log lines of {name}:")
    out.append(logs or "(empty)")
    return "\n".join(out) + "\n"


async def _send_diagnostics(name: str, send_log: LogCallback) -> None:
    try:
        text = await asyncio.to_thread(_diagnostics_sync, name)
    except Exception as exc:
        text = f"--- Cannot collect diagnostics: {exc}\n"
    await send_log("\n" + text)


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
    rollback_compose: str,
    send_log: LogCallback,
    window: int,
    data_backup: str = "",
) -> tuple[bool, str]:
    """
    Quay về bản trước cập nhật, đụng tới dữ liệu ÍT NHẤT có thể:
      1. Trả docker-compose.yml chạy tốt + image cũ, GIỮ NGUYÊN dữ liệu (cài đặt, log hiện tại) -> kiểm tra.
         Lỗi cập nhật gần như luôn nằm ở image / compose, dữ liệu vẫn còn nguyên.
      2. Chỉ khi bản cũ vẫn không chạy được (bản mới đã đổi dữ liệu) mới khôi phục cấu hình từ bản sao lưu
         trước cập nhật (log hiện tại được giữ) rồi kiểm tra lại.
    """
    await send_log("\n==> New version is unhealthy. Rolling back to the previous version (app data is kept)...\n")
    compose_changed = False
    try:
        if Path(compose_path).read_text(encoding="utf-8") != rollback_compose:
            await asyncio.to_thread(_write_text, compose_path, rollback_compose)
            compose_changed = True
            await send_log("==> docker-compose.yml restored to the previous working version.\n")
    except Exception as exc:
        await send_log(f"[ERROR] Cannot restore docker-compose.yml: {exc}\n")
    if old_image_id:
        try:
            err = await asyncio.to_thread(_retag_image_sync, old_image_id, image_ref)
        except Exception as exc:
            err = str(exc)
        if err:
            await send_log(f"[WARN] Cannot re-tag previous image: {err}\n")
            if not compose_changed and not data_backup:
                return False, f"Cannot restore previous image: {err}"
        else:
            await send_log(f"==> Previous image {old_image_id[:19]} re-tagged as {image_ref}\n")
    elif not compose_changed and not data_backup:
        return False, "Previous image is unknown"

    cmd = ["docker", "compose", "-f", compose_path, "up", "-d", "--force-recreate", "--no-deps"]
    if service:
        cmd.append(service)

    async def recreate_and_check() -> tuple[bool, str]:
        await send_log(f"$ {' '.join(cmd)}\n")
        rc = await _run_cmd_stream(cmd, compose_dir, send_log)
        if rc != 0:
            return False, f"Rollback up failed (exit {rc})"
        return await _wait_healthy(container_name, send_log, window)

    ok, reason = await recreate_and_check()
    if ok:
        await send_log("==> Previous version is running with the current app data (nothing was restored).\n")
        return ok, reason
    await send_log(f"==> Previous version does not start with the current data: {reason}\n")
    await _send_diagnostics(container_name, send_log)
    if not data_backup:
        return ok, reason

    # Bước 2: bản mới có thể đã đổi dữ liệu -> trả cấu hình về bản sao lưu ngay trước cập nhật
    from app.core.app_backup import restore_backup

    await send_log(f"==> Restoring the app configuration backed up before the update ({data_backup})...\n")
    try:
        res = await asyncio.to_thread(restore_backup, container_name, data_backup, start=False, restore_version=False)
    except Exception as exc:
        res = {"ok": False, "error": str(exc)}
    if not res.get("ok"):
        await send_log(f"[ERROR] Configuration restore failed: {res.get('error')}\n")
        return False, f"{reason}; configuration restore failed"
    await send_log(f"==> {res.get('message')}\n")
    ok, reason = await recreate_and_check()
    if not ok:
        await send_log(f"==> Previous version is not healthy either: {reason}\n")
        await _send_diagnostics(container_name, send_log)
    return ok, reason


SELF_HELPER_NAME = "appmanager-pro-self-updater"
SELF_JOB_FILE = DATA_DIR / "self-update-job.json"
SELF_RESULT_FILE = DATA_DIR / "self-update-result.json"


def _own_container(client):
    import socket

    try:
        return client.containers.get(socket.gethostname())
    except Exception:
        return client.containers.get("appmanager-pro")


def _trigger_self_update_helper(
    compose_path: str,
    *,
    mode: str = "update",
    title: str = "AppManager Pro",
    from_version: str = "",
    to_version: str = "",
    compose_original: Optional[str] = None,
    history_mode: str = "manual",
) -> None:
    """
    Chạy container phụ (bằng image hiện tại — bản đang chạy ổn) để cập nhật / tạo lại AppManager Pro,
    kiểm tra sức khoẻ bản mới và tự rollback nếu hỏng. Kết quả được ghi vào Lịch sử khi AppManager chạy lại.
    mode: "update" (pull + tạo lại) hoặc "recreate" (sau khi sửa compose).
    compose_original: nội dung compose trước khi đổi (để trả lại khi rollback); None = compose không đổi.
    """
    compose_dir = str(Path(compose_path).parent)
    client = get_docker_client()
    try:
        client.containers.get(SELF_HELPER_NAME).remove(force=True)
    except Exception:
        pass
    collect_self_update_result()  # kết quả cũ chưa đọc (nếu có) -> ghi lại trước khi ghi đè

    own = _own_container(client)
    labels = (own.attrs.get("Config") or {}).get("Labels") or {}
    data_volume: dict[str, dict[str, str]] = {}
    for m in own.attrs.get("Mounts") or []:
        if m.get("Destination") == str(DATA_DIR):
            key = m.get("Name") if m.get("Type") == "volume" else m.get("Source")
            if key:
                data_volume = {key: {"bind": str(DATA_DIR), "mode": "rw"}}
    if not data_volume:
        raise RuntimeError(f"{DATA_DIR} is not mounted from the host; cannot run a safe self-update")

    try:
        window = max(90, min(300, int(get_setting("health_wait_seconds", "25")) * 4))
    except Exception:
        window = 120
    job = {
        "container": own.name,
        "service": labels.get("com.docker.compose.service") or "",
        "compose_path": compose_path,
        "compose_original": compose_original,
        "old_image_id": own.image.id,
        "image_ref": (own.attrs.get("Config") or {}).get("Image") or "",
        "mode": mode,
        "history_mode": history_mode,
        "title": title,
        "from_version": from_version,
        "to_version": to_version,
        "window": window,
        "prune_old_image": get_setting("prune_old_images", "true").lower() == "true",
        "started": int(time.time()),
    }
    # Sao lưu database (cài đặt, tài khoản, lịch sử) — bản mới có thể đổi cấu trúc; rollback sẽ trả lại.
    import sqlite3

    from app.core.database import DB_PATH

    db_bak = DATA_DIR / "self-update-db.bak"
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(db_bak))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    job["db_backup"] = db_bak.name
    job["db_name"] = DB_PATH.name
    SELF_JOB_FILE.write_text(json.dumps(job), encoding="utf-8")
    try:
        client.containers.run(
            image=own.image.id,  # image hiện tại: có Docker CLI + Compose + chính script phụ này
            command=["python", "-m", "app.self_update_helper"],
            working_dir="/app",
            environment={"APP_DATA_DIR": str(DATA_DIR)},
            remove=True,
            detach=True,
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                compose_dir: {"bind": compose_dir, "mode": "rw"},
                **data_volume,
            },
            name=SELF_HELPER_NAME,
        )
    except Exception:
        SELF_JOB_FILE.unlink(missing_ok=True)
        raise


def collect_self_update_result() -> None:
    """Ghi kết quả tự cập nhật (do container phụ để lại) vào Lịch sử. Gọi lúc khởi động và mỗi phút."""
    try:
        if SELF_RESULT_FILE.exists():
            res = json.loads(SELF_RESULT_FILE.read_text(encoding="utf-8"))
            before = get_last_update_history_id()
            add_update_history(
                res.get("container") or "appmanager-pro", res.get("title") or "AppManager Pro",
                res.get("from_version") or "", res.get("to_version") or "",
                res.get("history_mode") or "manual", res.get("status") or "failed", (res.get("message") or "")[:300],
            )
            attach_update_log(res.get("container") or "appmanager-pro", before, res.get("log") or "")
            SELF_RESULT_FILE.unlink(missing_ok=True)
            return
        if SELF_JOB_FILE.exists():
            job = json.loads(SELF_JOB_FILE.read_text(encoding="utf-8"))
            if time.time() - int(job.get("started") or 0) < 20 * 60:
                return  # container phụ có thể vẫn đang chạy
            try:
                get_docker_client().containers.get(SELF_HELPER_NAME)
                return
            except Exception:
                pass
            add_update_history(
                job.get("container") or "appmanager-pro", job.get("title") or "AppManager Pro",
                job.get("from_version") or "", job.get("to_version") or "", job.get("history_mode") or "manual",
                "failed", "Self-update helper stopped without reporting a result",
            )
            SELF_JOB_FILE.unlink(missing_ok=True)
    except Exception:
        logger.exception("Cannot collect self-update result")


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


def _write_text(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def _container_attrs_sync(name: str) -> dict[str, Any]:
    try:
        return get_docker_client().containers.get(name).attrs or {}
    except Exception:
        return {}


def _restore_compose_backup(compose_path: str, backup_path: str) -> None:
    if backup_path and Path(backup_path).exists():
        Path(compose_path).write_text(
            Path(backup_path).read_text(encoding="utf-8"), encoding="utf-8"
        )


logger = logging.getLogger("appmanager.updater")
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
        chunks: list[str] = []

        async def tee_log(text: str) -> None:
            chunks.append(text)
            await send_log(text)

        try:
            before_id = await asyncio.to_thread(get_last_update_history_id)
        except Exception:
            before_id = None
        try:
            return await _update_app_stream_impl(container_name, tee_log, mode)
        except Exception as exc:  # không để một app lỗi làm dừng cả Update All / cập nhật tự động
            logger.exception("Update of %s crashed", container_name)
            msg = f"Unexpected error: {exc}"
            try:
                await send_log(f"\n[ERROR] {msg}\n")
            except Exception:
                pass
            chunks.append(f"\n[ERROR] {msg}\n")
            try:
                add_update_history(container_name, container_name, "", "", mode, "failed", msg[:300])
            except Exception:
                pass
            return {"ok": False, "error": msg}
        finally:
            if before_id is not None:
                try:
                    await asyncio.to_thread(attach_update_log, container_name, before_id, "".join(chunks))
                except Exception:
                    logger.exception("Cannot save update log of %s", container_name)


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

    # Bản compose để quay về nếu hỏng: file hiện tại, hoặc bản chạy tốt gần nhất nếu file đã bị sửa
    # sau lúc tạo container (chỗ sửa đó chưa từng chạy -> có thể chính nó gây lỗi).
    pre_compose = Path(compose_path).read_text(encoding="utf-8")
    attrs = await asyncio.to_thread(_container_attrs_sync, container_name)
    rollback_compose, drift_note = rollback_compose_text(container_name, compose_path, pre_compose, attrs)
    if drift_note:
        await send_log(f"==> [NOTE] {drift_note}.\n")

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
            await asyncio.to_thread(
                lambda: _trigger_self_update_helper(
                    compose_path, mode="update", title=title, from_version=from_ver, to_version=target_ver,
                    compose_original=rollback_compose, history_mode=mode,
                )
            )
            await send_log(
                "==> Helper launched! AppManager Pro restarts in a few seconds. The new version is checked and "
                "rolled back automatically if it does not start; the result appears in Settings → History.\n"
            )
            await send_log("__SELF_UPDATE_RELOAD__\n")
            return {"ok": True, "self_update": True, "to_version": target_ver}
        except Exception as exc:
            await asyncio.to_thread(_write_text, compose_path, pre_compose)
            await send_log(f"[ERROR] Self-update failed: {exc}\n")
            add_update_history(
                container_name, title, from_ver, target_ver, mode, "failed", str(exc)
            )
            return {"ok": False, "error": str(exc)}

    await send_log(f"==> Updating {title} ({container_name})\n")
    await send_log(f"==> Compose file: {compose_path}\n\n")

    # Sao lưu dữ liệu app trước khi cập nhật (tuỳ chọn trong Settings)
    backup_name = ""
    if get_setting("backup_before_update", "true").lower() == "true" and app_info.get("appdata_path"):
        from app.core.app_backup import create_backup

        await send_log(f"==> Backing up app configuration in {app_info['appdata_path']} (settings files only)...\n")
        try:
            max_mb = int(get_setting("backup_max_mb", "2048") or 2048)
            keep = int(get_setting("backup_keep", "3") or 3)
            file_max_mb = int(get_setting("backup_file_max_mb", "50") or 50)
        except ValueError:
            max_mb, keep, file_max_mb = 2048, 3, 50
        bres = await asyncio.to_thread(
            create_backup, container_name, app_info["appdata_path"], from_ver, max_mb, keep,
            mounts=attrs.get("Mounts") or [], file_max_mb=file_max_mb, image_id=old_image_id, image_ref=app_info["image"], compose_path=compose_path, service=service,
            compose_text=rollback_compose,
        )
        if bres.get("ok"):
            backup_name = bres["file"]
            await send_log(f"==> {bres['message']} — archive {bres.get('size', '')}\n")
            await send_log(f"    Included: {', '.join(bres.get('roots') or [])}\n")
            for sm in bres.get("skipped_mounts") or []:
                await send_log(f"    Skipped mount: {sm}\n")
            skipped = bres.get("skipped") or []
            for item in skipped[:15]:
                await send_log(f"    Skipped: {item}\n")
            if len(skipped) > 15:
                await send_log(f"    ... and {len(skipped) - 15} more skipped item(s)\n")
            await send_log("\n")
        else:
            await send_log(
                f"==> [WARN] {bres.get('message')} — continuing without data backup "
                "(a failed update still restores docker-compose.yml and the previous image).\n\n"
            )

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
        if bumped:
            await asyncio.to_thread(_write_text, compose_path, pre_compose)
            await send_log("==> docker-compose.yml restored (nothing else was changed).\n")
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

    # Bước 3: Kiểm tra sức khoẻ container mới; hỏng (kể cả "up" lỗi) thì tự quay về bản cũ
    try:
        window = max(10, min(120, int(get_setting("health_wait_seconds", "25"))))
    except Exception:
        window = 25
    if rc2 != 0:
        healthy, reason = False, f"docker compose up failed (exit {rc2})"
        await send_log(f"\n[ERROR] {reason}\n")
    else:
        await send_log(f"\n==> Checking the new container for {window}s...\n")
        healthy, reason = await _wait_healthy(container_name, send_log, window, baseline)
        await send_log(f"==> {reason}\n")
    if not healthy:
        await _send_diagnostics(container_name, send_log)

    rolled_back = False
    if not healthy and get_setting("auto_rollback", "true").lower() == "true":
        rb_ok, rb_reason = await _rollback_to_previous(
            compose_path=compose_path, compose_dir=compose_dir, service=service,
            container_name=container_name, image_ref=app_info["image"],
            old_image_id=old_image_id, rollback_compose=rollback_compose,
            send_log=send_log, window=window, data_backup=backup_name,
        )
        if rb_ok:
            rolled_back = True
            await send_log("\n↩️ Rolled back: the previous version is running again.\n")
            add_update_history(
                container_name, title, from_ver, target_ver, mode, "rolled_back",
                f"Update failed ({reason}); previous version restored",
            )
            await check_one_app_by_name(container_name)
            return {"ok": False, "error": f"Update failed ({reason}); rolled back to {from_ver or 'previous version'}"}
        await send_log(f"\n[ERROR] Rollback failed: {rb_reason}\n")
        reason = f"{reason}; rollback failed: {rb_reason}"

    refreshed = await asyncio.to_thread(get_app_by_name, container_name)
    new_ver = refreshed["version"] if refreshed else target_ver
    new_image_id = refreshed["image_id"] if refreshed else ""
    new_status = refreshed["status"] if refreshed else "unknown"

    if healthy:
        await asyncio.to_thread(save_good, container_name, compose_path)

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
        f"Container status: {new_status}" if final_status == "success" else f"{reason} (status: {new_status})"[:300],
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
