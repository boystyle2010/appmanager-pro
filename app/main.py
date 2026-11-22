import asyncio
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.app_backup import delete_backup, list_backups, restore_backup
from app.core.auth import (
    check_second_factor,
    clear_failed_attempts,
    clear_session_cookie,
    get_client_ip,
    get_current_user_optional,
    hash_password,
    is_ip_locked,
    new_backup_codes,
    new_totp_secret,
    origin_allowed,
    record_failed_attempt,
    require_user,
    set_session_cookie,
    setup_first_admin,
    totp_qr_svg,
    totp_uri,
    validate_new_password,
    verify_password,
    verify_totp,
    verify_websocket_user,
)
from app.core.compose_manager import (
    deploy_new_app_stream,
    generate_deploy_yaml,
    get_compose_state,
    merge_ui_into_yaml,
    parse_yaml_to_ui,
    rollback_compose,
    sanitize_app_id,
    save_and_apply_compose,
    uninstall_app,
    validate_compose_yaml,
)
from app.core.database import (
    DATA_DIR,
    add_audit,
    get_app_pref,
    get_audit_log,
    get_resource_samples,
    get_resource_totals,
    rotate_session_secret,
    update_user_fields,
    get_public_settings,
    get_update_cache_item,
    get_update_history,
    get_user_by_username,
    has_admin_user,
    init_db,
    save_app_pref,
    set_setting,
)
from app.core.docker_client import (
    APP_VERSION,
    container_action,
    get_app_by_name,
    get_docker_client,
    list_all_apps,
)
from app.core.registry_checker import (
    check_all_updates,
    check_one_app_by_name,
    is_check_running,
)
from app.core.scheduler import configure_jobs, get_auto_prune_next_run, start_scheduler, stop_scheduler
from app.core.system_monitor import collect_task_manager_snapshot
from app.core.system_prune import get_docker_disk_usage, prune_docker_resources
from app.core.updater import update_all_apps_stream, update_app_stream

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR.parent / "assets"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="AppManager Pro", version=APP_VERSION, lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ---------------- Security headers ----------------
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src * data: blob:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
        if not origin_allowed(request.headers):
            return JSONResponse(status_code=403, content={"detail": "Cross-site request blocked"})
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if response.headers.get("content-type", "").startswith("text/html"):
        h.setdefault("Content-Security-Policy", _CSP)
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    return response


def audit(request, user: str, action: str, target: str = "", detail: str = "", ok: bool = True) -> None:
    try:
        add_audit(action, user or "", get_client_ip(request), target, detail, ok)
    except Exception:
        pass


class SetupPayload(BaseModel):
    username: str
    password: str
    confirm_password: str


class LoginPayload(BaseModel):
    username: str
    password: str
    remember: bool = True
    otp: Optional[str] = None


class TwoFactorCodePayload(BaseModel):
    code: str


class TwoFactorDisablePayload(BaseModel):
    password: str
    code: str


class PasswordChangePayload(BaseModel):
    current_password: str
    new_password: str


class BackupActionPayload(BaseModel):
    app: str
    file: str


class AppPrefPayload(BaseModel):
    auto_update: Optional[bool] = None
    custom_repo: Optional[str] = None
    skipped_digest: Optional[str] = None


class SettingsPayload(BaseModel):
    check_interval_hours: int = 6
    auto_update_enabled: bool = False
    auto_update_time: str = "03:30"
    prune_old_images: bool = True
    auto_rollback: bool = True
    health_wait_seconds: int = 25
    auto_prune_enabled: bool = False
    auto_prune_freq: str = "weekly"
    auto_prune_weekday: int = 6
    auto_prune_time: str = "04:00"
    auto_prune_images: str = "dangling"
    auto_prune_cache: bool = True
    backup_before_update: bool = False
    backup_max_mb: int = 2048
    backup_keep: int = 3
    github_token: Optional[str] = None


class ComposeToYamlPayload(BaseModel):
    base_yaml: str
    ui: dict[str, Any]


class ComposeToUiPayload(BaseModel):
    raw_yaml: str
    selected_service: Optional[str] = None


class ComposeYamlPayload(BaseModel):
    raw_yaml: str


class RollbackPayload(BaseModel):
    filename: str


class UninstallPayload(BaseModel):
    remove_compose: bool = True
    remove_images: bool = False
    remove_appdata: bool = False
    confirm_name: str = ""


class PrunePayload(BaseModel):
    prune_images: bool = True
    all_unused_images: bool = False
    prune_build_cache: bool = True
    prune_containers: bool = False
    prune_volumes: bool = False


class DeployValidatePayload(BaseModel):
    raw_yaml: str


class DeployFormPayload(BaseModel):
    app_id: str = ""
    title: str = ""
    image: str
    restart: str = "unless-stopped"
    network_mode: str = ""
    privileged: bool = False
    icon: str = ""
    port_map: str = ""
    category: str = "Utilities"
    ports: list[dict[str, Any]] = []
    volumes: list[dict[str, Any]] = []
    environment: list[dict[str, Any]] = []


# ---------------- PWA Manifest & Pages ----------------

@app.get("/manifest.json")
async def pwa_manifest():
    return JSONResponse(
        content={
            "name": "AppManager Pro",
            "short_name": "AppManager",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#090f1d",
            "theme_color": "#090f1d",
            "icons": [
                {"src": "/assets/icon.png", "sizes": "512x512", "type": "image/png"}
            ],
        }
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if not has_admin_user() or not get_current_user_optional(request):
        return RedirectResponse(url="/login", status_code=302)
    # Cú pháp mới (request đứng đầu): bắt buộc từ Starlette 1.0, vẫn chạy với bản cũ
    return templates.TemplateResponse(request, "index.html", {"version": app.version})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    is_setup = not has_admin_user()
    if not is_setup and get_current_user_optional(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "auth.html", {"is_setup": is_setup, "version": app.version})


# ---------------- Auth APIs ----------------

@app.post("/api/auth/setup")
async def api_setup(payload: SetupPayload, request: Request, response: Response):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    setup_first_admin(payload.username, payload.password)
    set_session_cookie(response, request, payload.username.strip(), remember=True)
    audit(request, payload.username.strip(), "setup", detail="Admin account created")
    return {"ok": True}


@app.post("/api/auth/login")
async def api_login(payload: LoginPayload, request: Request, response: Response):
    ip = get_client_ip(request)
    lock_remaining = is_ip_locked(ip)
    if lock_remaining > 0:
        mins = (lock_remaining + 59) // 60
        audit(request, payload.username.strip(), "login_blocked", detail="IP locked out", ok=False)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {mins} minute(s).",
        )

    user = get_user_by_username(payload.username.strip())
    if not user or not await asyncio.to_thread(verify_password, user["password_hash"], payload.password):
        record_failed_attempt(ip)
        audit(request, payload.username.strip(), "login_failed", detail="Wrong username or password", ok=False)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user["totp_enabled"]:
        if not (payload.otp or "").strip():
            return {"ok": False, "otp_required": True}
        if not check_second_factor(user, payload.otp or ""):
            record_failed_attempt(ip)
            audit(request, user["username"], "login_failed", detail="Wrong 2FA code", ok=False)
            raise HTTPException(status_code=401, detail="Invalid two-factor code")

    clear_failed_attempts(ip)
    set_session_cookie(response, request, user["username"], remember=payload.remember)
    audit(request, user["username"], "login", detail="2FA" if user["totp_enabled"] else "")
    return {"ok": True, "username": user["username"]}


@app.post("/api/auth/logout")
async def api_logout(request: Request, response: Response):
    audit(request, get_current_user_optional(request) or "", "logout")
    clear_session_cookie(response)
    return {"ok": True}


# ---------------- Account security: 2FA & password ----------------

@app.get("/api/auth/security")
async def api_security_status(user: str = Depends(require_user)):
    u = get_user_by_username(user)
    import json as _json

    try:
        remaining = len(_json.loads(u["backup_codes"] or "[]"))
    except Exception:
        remaining = 0
    return {"username": user, "totp_enabled": bool(u["totp_enabled"]), "backup_codes_left": remaining}


@app.post("/api/auth/2fa/setup")
async def api_2fa_setup(user: str = Depends(require_user)):
    u = get_user_by_username(user)
    if u["totp_enabled"]:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled")
    secret = new_totp_secret()
    update_user_fields(user, totp_pending=secret)
    uri = totp_uri(secret, user)
    return {"secret": secret, "uri": uri, "qr_svg": totp_qr_svg(uri)}


@app.post("/api/auth/2fa/enable")
async def api_2fa_enable(payload: TwoFactorCodePayload, request: Request, user: str = Depends(require_user)):
    u = get_user_by_username(user)
    secret = u["totp_pending"] or ""
    if not secret:
        raise HTTPException(status_code=400, detail="Start the 2FA setup first")
    step = verify_totp(secret, payload.code)
    if not step:
        raise HTTPException(status_code=400, detail="Invalid code — check the time on your phone and try again")
    codes, hashed = new_backup_codes()
    update_user_fields(user, totp_secret=secret, totp_enabled=1, totp_last_step=step, totp_pending="", backup_codes=hashed)
    audit(request, user, "2fa_enabled")
    return {"ok": True, "backup_codes": codes}


@app.post("/api/auth/2fa/disable")
async def api_2fa_disable(payload: TwoFactorDisablePayload, request: Request, user: str = Depends(require_user)):
    u = get_user_by_username(user)
    if not await asyncio.to_thread(verify_password, u["password_hash"], payload.password) or not check_second_factor(u, payload.code):
        audit(request, user, "2fa_disable_failed", ok=False)
        raise HTTPException(status_code=400, detail="Wrong password or code")
    update_user_fields(user, totp_secret="", totp_enabled=0, totp_last_step=0, backup_codes="[]", totp_pending="")
    audit(request, user, "2fa_disabled")
    return {"ok": True}


@app.post("/api/auth/2fa/backup-codes")
async def api_2fa_new_codes(payload: TwoFactorCodePayload, request: Request, user: str = Depends(require_user)):
    u = get_user_by_username(user)
    if not u["totp_enabled"] or not check_second_factor(u, payload.code):
        raise HTTPException(status_code=400, detail="Invalid code")
    codes, hashed = new_backup_codes()
    update_user_fields(user, backup_codes=hashed)
    audit(request, user, "2fa_backup_codes_regenerated")
    return {"ok": True, "backup_codes": codes}


@app.post("/api/auth/password")
async def api_change_password(payload: PasswordChangePayload, request: Request, response: Response, user: str = Depends(require_user)):
    u = get_user_by_username(user)
    if not await asyncio.to_thread(verify_password, u["password_hash"], payload.current_password):
        audit(request, user, "password_change_failed", ok=False)
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    validate_new_password(payload.new_password)
    update_user_fields(user, password_hash=await asyncio.to_thread(hash_password, payload.new_password))
    rotate_session_secret()  # đăng xuất mọi thiết bị khác
    set_session_cookie(response, request, user, remember=True)
    audit(request, user, "password_changed")
    return {"ok": True}


@app.get("/api/audit")
async def api_audit(limit: int = 200, _: str = Depends(require_user)):
    return {"items": get_audit_log(max(1, min(1000, limit)))}


# ---------------- Docker & Update APIs ----------------

@app.get("/api/apps")
async def api_list_apps(_: str = Depends(require_user)):
    try:
        data = await asyncio.to_thread(list_all_apps, True)
        data["checking_updates"] = is_check_running()
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker socket error: {e}")


@app.post("/api/updates/check")
async def api_check_updates(_: str = Depends(require_user)):
    result = await check_all_updates()
    return JSONResponse(content=result)


@app.get("/api/apps/{container_name}/details")
async def api_app_details(
    container_name: str, refresh: bool = False, _: str = Depends(require_user)
):
    if refresh:
        await check_one_app_by_name(container_name)
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        raise HTTPException(status_code=404, detail="App not found")

    cache = get_update_cache_item(container_name)
    if not cache or not cache.get("checked_at"):
        cache = await check_one_app_by_name(container_name) or {}
        app_info = await asyncio.to_thread(get_app_by_name, container_name) or app_info

    pref = get_app_pref(container_name)
    return {
        "app": app_info,
        "changelog": cache.get("changelog") or "",
        "changelog_error": cache.get("error") or "",
        "release_tag": cache.get("release_tag") or "",
        "release_url": cache.get("release_url") or "",
        "published_at": cache.get("published_at") or "",
        "pref": pref,
    }


@app.post("/api/apps/{container_name}/prefs")
async def api_save_app_prefs(
    container_name: str, payload: AppPrefPayload, _: str = Depends(require_user)
):
    pref = save_app_pref(
        container_name,
        auto_update=payload.auto_update,
        custom_repo=payload.custom_repo,
        skipped_digest=payload.skipped_digest,
    )
    if payload.custom_repo is not None:
        await check_one_app_by_name(container_name)
    return {"ok": True, "pref": pref}


# ---------------- Deploy App, Storage & Prune APIs ----------------

@app.post("/api/deploy/generate")
async def api_deploy_generate(payload: DeployFormPayload, _: str = Depends(require_user)):
    try:
        yaml_text = generate_deploy_yaml(payload.model_dump())
        app_id = sanitize_app_id(payload.app_id or payload.title or "my-app") or "my-app"
        return {"ok": True, "raw_yaml": yaml_text, "app_id": app_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/deploy/validate")
async def api_deploy_validate(payload: DeployValidatePayload, _: str = Depends(require_user)):
    ok, msg = await validate_compose_yaml(payload.raw_yaml, str(DATA_DIR))
    return {"ok": ok, "message": msg}


@app.get("/api/system/storage")
async def api_system_storage(_: str = Depends(require_user)):
    try:
        return await asyncio.to_thread(get_docker_disk_usage)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage inspect failed: {e}")


@app.post("/api/system/prune")
async def api_system_prune(payload: PrunePayload, request: Request, user: str = Depends(require_user)):
    try:
        res = await asyncio.to_thread(
            prune_docker_resources,
            prune_images=payload.prune_images,
            all_unused_images=payload.all_unused_images,
            prune_build_cache=payload.prune_build_cache,
            prune_containers=payload.prune_containers,
            prune_volumes=payload.prune_volumes,
        )
        audit(request, user, "prune", detail=f"Freed {res.get('freed_display', '')}")
        return res
    except Exception as e:
        audit(request, user, "prune", detail=str(e)[:200], ok=False)
        raise HTTPException(status_code=500, detail=f"Prune failed: {e}")


# ---------------- Compose Visual UI / YAML Editor & Rollback ----------------

@app.get("/api/apps/{container_name}/compose")
async def api_get_compose(
    container_name: str, service: Optional[str] = None, _: str = Depends(require_user)
):
    try:
        return await get_compose_state(container_name, service=service)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/apps/{container_name}/compose/to-yaml")
async def api_compose_to_yaml(
    container_name: str, payload: ComposeToYamlPayload, _: str = Depends(require_user)
):
    try:
        merged = merge_ui_into_yaml(payload.base_yaml, payload.ui)
        return {"ok": True, "raw_yaml": merged}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/apps/{container_name}/compose/to-ui")
async def api_compose_to_ui(
    container_name: str, payload: ComposeToUiPayload, _: str = Depends(require_user)
):
    try:
        ui = parse_yaml_to_ui(payload.raw_yaml, preferred_service=payload.selected_service)
        return {"ok": True, "ui": ui}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/apps/{container_name}/compose/validate")
async def api_validate_compose(
    container_name: str, payload: ComposeYamlPayload, _: str = Depends(require_user)
):
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info or not app_info.get("compose_path"):
        raise HTTPException(status_code=404, detail="Compose file not found")
    compose_dir = str(Path(app_info["compose_path"]).parent)
    ok, msg = await validate_compose_yaml(payload.raw_yaml, compose_dir)
    return {"ok": ok, "message": msg}


@app.post("/api/apps/{container_name}/compose/apply")
async def api_apply_compose(
    container_name: str, payload: ComposeYamlPayload, request: Request, user: str = Depends(require_user)
):
    res = await save_and_apply_compose(container_name, payload.raw_yaml)
    audit(request, user, "compose_apply", container_name, res.get("error") or "", bool(res.get("ok")))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Apply failed")
    return res


@app.post("/api/apps/{container_name}/compose/rollback")
async def api_rollback_compose(
    container_name: str, payload: RollbackPayload, request: Request, user: str = Depends(require_user)
):
    res = await rollback_compose(container_name, payload.filename)
    audit(request, user, "compose_rollback", container_name, payload.filename, bool(res.get("ok")))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Rollback failed")
    return res


# ---------------- Smart Uninstall & Actions ----------------

@app.post("/api/apps/{container_name}/uninstall")
async def api_uninstall_app(
    container_name: str, payload: UninstallPayload, request: Request, user: str = Depends(require_user)
):
    res = await uninstall_app(
        container_name,
        remove_compose=payload.remove_compose,
        remove_images=payload.remove_images,
        remove_appdata=payload.remove_appdata,
        confirm_name=payload.confirm_name,
    )
    audit(
        request, user, "uninstall", container_name,
        f"compose={payload.remove_compose} images={payload.remove_images} appdata={payload.remove_appdata}",
        bool(res.get("ok")),
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Uninstall failed")
    return res


@app.post("/api/apps/{container_id}/{action}")
async def api_app_action(container_id: str, action: str, request: Request, user: str = Depends(require_user)):
    if action not in ("start", "stop", "restart", "kill"):
        raise HTTPException(status_code=400, detail="Invalid action")
    try:
        res = await asyncio.to_thread(container_action, container_id, action)
        audit(request, user, action, container_id)
        return res
    except KeyError:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/settings")
async def api_get_settings(_: str = Depends(require_user)):
    return {
        "settings": {**get_public_settings(), "auto_prune_next_run": get_auto_prune_next_run()},
        "history": get_update_history(30),
    }


def _valid_hhmm(value: str, default: str) -> str:
    try:
        h, m = (int(x) for x in (value or "").split(":", 1))
        if 0 <= h < 24 and 0 <= m < 60:
            return f"{h:02d}:{m:02d}"
    except ValueError:
        pass
    return default


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload, request: Request, user: str = Depends(require_user)):
    set_setting("check_interval_hours", str(max(1, min(168, payload.check_interval_hours))))
    set_setting("auto_update_enabled", "true" if payload.auto_update_enabled else "false")
    set_setting("auto_update_time", _valid_hhmm(payload.auto_update_time, "03:30"))
    set_setting("prune_old_images", "true" if payload.prune_old_images else "false")
    set_setting("auto_rollback", "true" if payload.auto_rollback else "false")
    set_setting("health_wait_seconds", str(max(10, min(120, payload.health_wait_seconds))))
    set_setting("auto_prune_enabled", "true" if payload.auto_prune_enabled else "false")
    set_setting("auto_prune_freq", payload.auto_prune_freq if payload.auto_prune_freq in ("daily", "weekly", "monthly") else "weekly")
    set_setting("auto_prune_weekday", str(max(0, min(6, payload.auto_prune_weekday))))
    set_setting("auto_prune_time", _valid_hhmm(payload.auto_prune_time, "04:00"))
    set_setting("auto_prune_images", payload.auto_prune_images if payload.auto_prune_images in ("off", "dangling", "all") else "dangling")
    set_setting("auto_prune_cache", "true" if payload.auto_prune_cache else "false")
    set_setting("backup_before_update", "true" if payload.backup_before_update else "false")
    set_setting("backup_max_mb", str(max(50, min(102400, payload.backup_max_mb))))
    set_setting("backup_keep", str(max(1, min(20, payload.backup_keep))))
    if payload.github_token is not None:
        set_setting("github_token", payload.github_token.strip())
    configure_jobs()
    audit(request, user, "settings_saved")
    return {"ok": True, "settings": {**get_public_settings(), "auto_prune_next_run": get_auto_prune_next_run()}}


# ---------------- Resource history & app data backups ----------------

@app.get("/api/system/history")
async def api_resource_history(container: str = "", hours: int = 24, _: str = Depends(require_user)):
    since = int(time.time()) - max(1, min(168, hours)) * 3600
    if container:
        points = await asyncio.to_thread(get_resource_samples, container, since)
    else:
        points = await asyncio.to_thread(get_resource_totals, since)
    return {"container": container, "hours": hours, "points": points}


@app.get("/api/backups")
async def api_list_backups(_: str = Depends(require_user)):
    return {"items": await asyncio.to_thread(list_backups)}


@app.post("/api/backups/restore")
async def api_restore_backup(payload: BackupActionPayload, request: Request, user: str = Depends(require_user)):
    try:
        res = await asyncio.to_thread(restore_backup, payload.app, payload.file)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(request, user, "backup_restore", payload.app, payload.file, bool(res.get("ok")))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Restore failed")
    return res


@app.post("/api/backups/delete")
async def api_delete_backup(payload: BackupActionPayload, request: Request, user: str = Depends(require_user)):
    try:
        await asyncio.to_thread(delete_backup, payload.app, payload.file)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(request, user, "backup_delete", payload.app, payload.file)
    return {"ok": True}


# ---------------- WebSockets ----------------

@app.websocket("/ws/task-manager")
async def ws_task_manager(websocket: WebSocket):
    ws_user = verify_websocket_user(websocket)
    await websocket.accept()
    if not ws_user:
        await websocket.close(code=4401)
        return
    try:
        while True:
            snapshot = await asyncio.to_thread(collect_task_manager_snapshot)
            await websocket.send_json(snapshot)
            await asyncio.sleep(2.0)
    except (WebSocketDisconnect, Exception):
        pass


@app.websocket("/ws/deploy")
async def ws_deploy_app(websocket: WebSocket):
    ws_user = verify_websocket_user(websocket)
    await websocket.accept()
    if not ws_user:
        await websocket.close(code=4401)
        return

    async def send_log(text: str):
        try:
            await websocket.send_text(text)
        except Exception:
            pass

    try:
        payload = await websocket.receive_json()
        app_id = str(payload.get("app_id") or "")
        raw_yaml = str(payload.get("raw_yaml") or "")
        res = await deploy_new_app_stream(app_id, raw_yaml, send_log)
        audit(websocket, ws_user, "deploy", app_id, ok=bool(res.get("ok")))
        if res.get("ok"):
            await send_log("__DEPLOY_OK__\n")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await send_log(f"[ERROR] {exc}\n")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/logs/{container_id}")
async def ws_container_logs(websocket: WebSocket, container_id: str):
    ws_user = verify_websocket_user(websocket)
    await websocket.accept()
    if not ws_user:
        await websocket.close(code=4401)
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    stop_event = threading.Event()
    holder: dict[str, Any] = {}

    def push(item):
        # Hàng đợi không giới hạn nhưng bỏ bớt dòng cũ khi quá dài để không tốn RAM
        if item is not None and queue.qsize() > 2000:
            return
        queue.put_nowait(item)

    def reader_thread():
        try:
            client = get_docker_client()
            container = client.containers.get(container_id)
            stream = container.logs(stream=True, follow=True, tail=150, timestamps=True)
            holder["stream"] = stream
            for chunk in stream:
                if stop_event.is_set():
                    break
                loop.call_soon_threadsafe(push, chunk.decode("utf-8", errors="replace"))
        except Exception as exc:
            if not stop_event.is_set():
                loop.call_soon_threadsafe(push, f"\n[AppManager Pro] Stream closed: {exc}\n")
        finally:
            loop.call_soon_threadsafe(push, None)

    async def watch_disconnect():
        # Phát hiện client đóng kết nối ngay cả khi container không in log nào
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
        except Exception:
            pass
        loop.call_soon_threadsafe(push, None)

    threading.Thread(target=reader_thread, daemon=True).start()
    watcher = asyncio.create_task(watch_disconnect())

    try:
        while True:
            line = await queue.get()
            if line is None:
                break
            await websocket.send_text(line)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        stop_event.set()
        watcher.cancel()
        stream = holder.get("stream")
        if stream is not None:
            try:
                stream.close()  # đóng kết nối Docker -> luồng đọc thoát ra
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/update/{container_name}")
async def ws_update_app(websocket: WebSocket, container_name: str):
    ws_user = verify_websocket_user(websocket)
    await websocket.accept()
    if not ws_user:
        await websocket.close(code=4401)
        return

    async def send_log(text: str):
        try:
            await websocket.send_text(text)
        except Exception:
            pass

    audit(websocket, ws_user, "update", container_name)
    try:
        await update_app_stream(container_name, send_log, mode="manual")
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/update-all")
async def ws_update_all(websocket: WebSocket):
    ws_user = verify_websocket_user(websocket)
    await websocket.accept()
    if not ws_user:
        await websocket.close(code=4401)
        return

    async def send_event(payload: dict):
        try:
            await websocket.send_json(payload)
        except Exception:
            pass

    audit(websocket, ws_user, "update_all")
    try:
        await update_all_apps_stream(send_event)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
