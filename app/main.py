import asyncio
import logging
import json
import threading
import time
import re
from urllib.parse import quote
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core import api_tokens, jobs, servers
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
    token_user,
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
    resolve_duplicate_compose,
    duplicate_compose_state,
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
    get_update_log,
    get_user_by_username,
    has_admin_user,
    init_db,
    save_app_pref,
    set_setting,
)
from app.core.database import get_setting
from app.core import compose_convert, data_setup, net, notify
from app.core.docker_client import (
    APP_VERSION,
    container_action,
    get_app_by_name,
    get_docker_client,
    list_all_apps,
)
from app.core.registry_checker import (
    check_all_updates,
    extract_github_slug,
    fetch_github_release,
    suggest_image_tags,
    pinned_version_label,
    check_one_app_by_name,
    is_check_running,
)
from app.core.scheduler import configure_jobs, get_auto_prune_next_run, start_scheduler, stop_scheduler
from app.core.system_monitor import collect_task_manager_snapshot
from app.core.system_prune import get_docker_disk_usage, prune_docker_resources
from app.core.updater import collect_self_update_result, get_update_all_excluded, update_all_apps_stream, update_app_stream

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR.parent / "assets"


logger = logging.getLogger("appmanager")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        net.apply_docker_logins()  # tài khoản registry cho docker pull / compose pull
    except Exception:
        logger.exception("Cannot apply registry logins")
    collect_self_update_result()
    # Cập nhật / sửa cấu hình bị cắt ngang (mất điện, Docker khởi động lại) -> trả container về như cũ
    try:
        from app.core.database import add_update_history
        from app.core.run_manager import recover_interrupted_sync

        from app.core.updater import SELF_JOB_FILE, _own_container

        busy: set[str] = set()
        if SELF_JOB_FILE.exists():  # container phụ đang cập nhật AppManager: nó tự lo container cũ / rollback
            try:
                busy.add(_own_container(get_docker_client()).name)
            except Exception:
                busy.add("appmanager-pro")
        for line in await asyncio.to_thread(recover_interrupted_sync, busy):
            logger.warning("Recovery: %s", line)
            name = line.split(":", 1)[0]
            add_update_history(name, name, "", "", "recovery", "rolled_back" if "restored" in line else "success", line[:300])
    except Exception:
        logger.exception("Recovery of interrupted updates failed")
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="AppManager Pro", version=APP_VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)  # tài liệu API chỉ cho người đã đăng nhập: /docs

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
    backup_before_update: bool = True
    backup_max_mb: int = 2048
    backup_file_max_mb: int = 50
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
    remove_image_users: list[str] = []  # gỡ cả các app đang dùng chung image (người dùng đã xác nhận đúng danh sách)


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
    await asyncio.to_thread(setup_first_admin, payload.username, payload.password)
    set_session_cookie(response, request, payload.username.strip(), remember=True)
    audit(request, payload.username.strip(), "setup", detail="Admin account created")
    return {"ok": True}


def _notify_if_locked(ip: str, username: str) -> None:
    if is_ip_locked(ip):
        vi = notify.settings()["lang"] == "vi"
        notify.on_security((f"IP {ip} bị khoá 15 phút sau nhiều lần đăng nhập sai (tài khoản: {username or '?'})." if vi
                            else f"IP {ip} was locked for 15 minutes after repeated failed logins (user: {username or '?'})."),
                           {"ip": ip, "username": username, "kind": "ip_locked"})


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
        _notify_if_locked(ip, payload.username.strip())
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user["totp_enabled"]:
        if not (payload.otp or "").strip():
            return {"ok": False, "otp_required": True}
        if not check_second_factor(user, payload.otp or ""):
            record_failed_attempt(ip)
            audit(request, user["username"], "login_failed", detail="Wrong 2FA code", ok=False)
            _notify_if_locked(ip, user["username"])
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
    notify.on_security(("Xác thực 2 lớp (2FA) đã bị TẮT cho tài khoản " if notify.settings()["lang"] == "vi"
                        else "Two-factor authentication was DISABLED for ") + user + f" (IP {get_client_ip(request)}).",
                       {"kind": "2fa_disabled", "user": user})
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
    notify.on_security(("Mật khẩu của " if notify.settings()["lang"] == "vi" else "The password of ") + user +
                       (" vừa được đổi" if notify.settings()["lang"] == "vi" else " was changed") + f" (IP {get_client_ip(request)}).",
                       {"kind": "password_changed", "user": user})
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
        # Bản sao lưu mới nhất của từng app (cho nút Khôi phục trên thẻ app)
        per_app: dict[str, list[dict]] = {}
        for b in await asyncio.to_thread(list_backups):  # đã sắp xếp mới nhất trước
            per_app.setdefault(b["app"], []).append(b)
        for a in data.get("apps") or []:
            a["backups"] = per_app.get(a["name"], [])
            a["latest_backup"] = a["backups"][0] if a["backups"] else None
        # App còn file compose khác nội dung (chưa bấm Skip) -> biểu tượng trên thẻ app
        def _dups() -> dict[str, tuple[int, bool]]:
            out: dict[str, tuple[int, bool]] = {}
            for a in data.get("apps") or []:
                cp = a.get("compose_path") or ""
                if not cp:
                    continue
                try:
                    names = [a.get("project") or "", a["name"], Path(cp).parent.name]
                    out[a["name"]] = duplicate_compose_state(a["name"], cp, names)
                except Exception:
                    pass
            return out
        dups = await asyncio.to_thread(_dups)
        for a in data.get("apps") or []:
            a["dup_compose"], a["dup_skipped"] = dups.get(a["name"], (0, False))
        data["update_all_excluded"] = get_update_all_excluded()
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


@app.get("/api/apps/{container_name}/channel-preview")
async def api_channel_preview(container_name: str, tag: str, _: str = Depends(require_user)):
    """Changelog của một kênh phát hành (chỉ xem, không đổi gì) — trước khi người dùng bấm cập nhật."""
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        raise HTTPException(status_code=404, detail="App not found")
    ch = next((c for c in (app_info.get("channels") or []) if c.get("tag") == tag), None)
    if not ch and await _version_tag_allowed(container_name, app_info, tag):
        ch = {"tag": tag, "channel": "version", "kind": "version", "version": pinned_version_label(tag)}
    if not ch:
        raise HTTPException(status_code=400, detail="This tag is not an available version for this app.")
    pref = get_app_pref(container_name)
    slug = extract_github_slug(
        (pref.get("custom_repo") or "").strip() or app_info.get("source_url") or "", app_info["image"], app_info.get("icon") or ""
    )
    out = {"channel": ch, "changelog": "", "release_tag": "", "release_url": "", "error": ""}
    if not slug:
        out["error"] = "No GitHub repository known for this app."
        return out
    async with net.client(timeout=20, follow_redirects=True) as client:
        gh = await fetch_github_release(
            client, slug, prefer_version=str(ch.get("version") or ""), prerelease=ch.get("kind") == "pre"
        )
    out.update({k: gh.get(k, "") for k in ("changelog", "release_tag", "release_url", "error")})
    return out


# Danh sách phiên bản gần nhất mỗi app (để kiểm tra tag người dùng chọn mà không hỏi registry lại mỗi lần)
_VERSION_CACHE: dict[str, tuple[float, str, set[str]]] = {}
_VERSION_TTL = 3600


async def _list_app_versions(container_name: str, app_info: dict) -> dict:
    image = (app_info.get("image") or "").strip()
    if not image or "$" in image or "@" in image.split("/")[-1]:
        raise HTTPException(status_code=400, detail="The image of this app has no tag that can be changed.")
    data = await suggest_image_tags(image, limit=15)
    _VERSION_CACHE[container_name] = (time.time(), image, {t["tag"] for t in data.get("tags") or []})
    return data


async def _version_tag_allowed(container_name: str, app_info: dict, tag: str) -> bool:
    """Tag phải nằm trong danh sách phiên bản do server tự lấy từ registry (không nhận tag tuỳ ý)."""
    if not tag or len(tag) > 128:
        return False
    cached = _VERSION_CACHE.get(container_name)
    if not cached or time.time() - cached[0] > _VERSION_TTL or cached[1] != (app_info.get("image") or ""):
        try:
            await _list_app_versions(container_name, app_info)
        except Exception:
            return False
        cached = _VERSION_CACHE.get(container_name)
    return bool(cached) and tag in cached[2]


@app.get("/api/apps/{container_name}/versions")
async def api_app_versions(container_name: str, _: str = Depends(require_user)):
    """Các phiên bản ổn định gần nhất (cùng biến thể) để người dùng chọn chuyển lên/xuống."""
    app_info = await asyncio.to_thread(get_app_by_name, container_name)
    if not app_info:
        raise HTTPException(status_code=404, detail="App not found")
    try:
        data = await _list_app_versions(container_name, app_info)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot read tags from the registry: {str(exc)[:120]}")
    for t in data.get("tags") or []:
        t["version"] = pinned_version_label(t["tag"]) if t.get("kind") != "channel" else ""
    data["app_version"] = app_info.get("version") or ""
    return data


@app.get("/api/image-tags")
async def api_image_tags(image: str, _: str = Depends(require_user)):
    """Gợi ý tag (latest + vài phiên bản ổn định mới nhất) cho ô Image & Tag trong trình sửa."""
    image = (image or "").strip()
    if not image or len(image) > 300 or any(c.isspace() for c in image):
        raise HTTPException(status_code=400, detail="Invalid image reference")
    if "$" in image:
        raise HTTPException(status_code=400, detail="The image uses a variable (${...}); tags cannot be suggested.")
    try:
        return await suggest_image_tags(image)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot read tags from the registry: {str(exc)[:120]}")


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
    if app_info and app_info.get("manage") == "run":
        # docker run: kiểm tra cú pháp + chuyển được sang cấu hình container (không chạy gì)
        from app.core.docker_client import get_docker_client
        from app.core.run_manager import body_from_yaml

        def check() -> str:
            client = get_docker_client()
            c = client.containers.get(container_name)
            try:
                img_cfg = client.images.get(c.attrs.get("Image")).attrs.get("Config") or {}
            except Exception:
                img_cfg = {}
            body_from_yaml(c.attrs, img_cfg, payload.raw_yaml, c.name)
            return "OK"

        try:
            return {"ok": True, "message": await asyncio.to_thread(check)}
        except Exception as exc:
            return {"ok": False, "message": str(exc)[:300]}
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
        # Kèm nhật ký (log container hỏng, kết quả quay về compose cũ) để hiện trong trình sửa
        return JSONResponse(
            status_code=400,
            content={"detail": res.get("error") or "Apply failed", "logs": res.get("logs") or ""},
        )
    return res


class UpdateAllExcludedPayload(BaseModel):
    names: list[str]


@app.post("/api/update-all/excluded")
async def api_update_all_excluded(payload: UpdateAllExcludedPayload, request: Request, user: str = Depends(require_user)):
    names = sorted({n.strip() for n in payload.names if n and n.strip() and len(n) <= 128})[:500]
    set_setting("update_all_excluded", json.dumps(names))
    audit(request, user, "update_all_excluded", ",".join(names)[:300])
    return {"ok": True, "excluded": names}


# ---------------- Thiết lập thư mục Data App (người dùng mới chưa mount thư mục Data) ----------------
class DataPathPayload(BaseModel):
    path: str


class DataApplyPayload(BaseModel):
    paths: list[str]


class DataUpdatePayload(BaseModel):
    add: list[str] = []
    remove: list[str] = []


class DataDismissPayload(BaseModel):
    dismissed: bool = True


@app.get("/api/setup/data-status")
async def api_data_status(_: str = Depends(require_user)):
    st = await asyncio.to_thread(data_setup.data_status)
    st["dismissed"] = get_setting(data_setup.dismissed_key(), "") == "1"
    st["prompt"] = bool(st.get("needs_setup")) and not st["dismissed"] and data_setup.env_flag()
    return st


@app.post("/api/setup/data-dismiss")
async def api_data_dismiss(payload: DataDismissPayload, _: str = Depends(require_user)):
    set_setting(data_setup.dismissed_key(), "1" if payload.dismissed else "")
    return {"ok": True}


@app.post("/api/setup/data-scan")
async def api_data_scan(request: Request, user: str = Depends(require_user)):
    """mode=quick: chỉ đọc nhãn Docker (tức thì). mode=deep: quét ổ đĩa host bằng container phụ (chạy nền)."""
    mode = request.query_params.get("mode") or "deep"
    if mode == "quick":
        try:
            return {"running": False, "candidates": await asyncio.to_thread(data_setup.quick_candidates), "error": ""}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)[:200])
    audit(request, user, "data_scan", "", "deep")
    return await asyncio.to_thread(data_setup.start_deep_scan)


@app.get("/api/setup/data-scan")
async def api_data_scan_state(_: str = Depends(require_user)):
    return data_setup.scan_state()


@app.post("/api/setup/data-check")
async def api_data_check(payload: DataPathPayload, _: str = Depends(require_user)):
    try:
        res = await asyncio.to_thread(data_setup.check_path, payload.path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot check the folder: {str(exc)[:200]}")
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Invalid folder")
    return res


@app.post("/api/setup/data-apply")
async def api_data_apply(payload: DataApplyPayload, request: Request, user: str = Depends(require_user)):
    try:
        res = await asyncio.to_thread(data_setup.apply_paths, payload.paths)
    except ValueError as exc:
        audit(request, user, "data_mount_add", ",".join(payload.paths)[:300], str(exc), False)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        audit(request, user, "data_mount_add", ",".join(payload.paths)[:300], str(exc), False)
        raise HTTPException(status_code=500, detail=f"Cannot update AppManager: {str(exc)[:200]}")
    audit(request, user, "data_mount_add", ",".join(res["added"])[:300])
    set_setting(data_setup.dismissed_key(), "")
    return {**res, "self_update": True}


@app.post("/api/setup/data-update")
async def api_data_update(payload: DataUpdatePayload, request: Request, user: str = Depends(require_user)):
    """Sửa đường dẫn / gỡ thư mục dữ liệu đã thêm vào AppManager (tạo lại AppManager bằng container phụ)."""
    detail = f"remove={','.join(payload.remove)} add={','.join(payload.add)}"[:300]
    try:
        res = await asyncio.to_thread(data_setup.update_paths, payload.add, payload.remove)
    except ValueError as exc:
        audit(request, user, "data_mount_change", detail, str(exc), False)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        audit(request, user, "data_mount_change", detail, str(exc), False)
        raise HTTPException(status_code=500, detail=f"Cannot update AppManager: {str(exc)[:200]}")
    audit(request, user, "data_mount_change", detail)
    return {**res, "self_update": True}


# ---------------- API token cho tự động hoá (0.17) ----------------
class TokenCreatePayload(BaseModel):
    name: str
    scope: str = "read"
    days: int = 0
    ips: str = ""


class TokenDeletePayload(BaseModel):
    id: str


class UpdateJobPayload(BaseModel):
    tag: str = ""


def _session_only(request: Request) -> str:
    """Quản lý token chỉ qua giao diện web (cookie phiên) — token không tự tạo / xoá token được."""
    if api_tokens.bearer(request.headers):
        raise HTTPException(status_code=403, detail="API tokens cannot manage API tokens; sign in on the web page")
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


@app.get("/api/tokens")
async def api_tokens_list(_: str = Depends(_session_only)):
    return {"tokens": api_tokens.list_tokens(), "scopes": list(api_tokens.SCOPES)}


@app.post("/api/tokens")
async def api_tokens_create(payload: TokenCreatePayload, request: Request, user: str = Depends(_session_only)):
    try:
        rec, plain = api_tokens.create(payload.name, payload.scope, payload.days, payload.ips, created_by=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit(request, user, "token_create", rec["name"], f"{rec['scope']}, days={payload.days}, ips={','.join(rec['ips'])}"[:300])
    vi = notify.settings()["lang"] == "vi"
    notify.on_security((f"API token mới \"{rec['name']}\" (quyền {rec['scope']}) vừa được tạo bởi {user} (IP {get_client_ip(request)})." if vi
                        else f"A new API token \"{rec['name']}\" ({rec['scope']}) was created by {user} (IP {get_client_ip(request)})."),
                       {"token": rec["name"], "scope": rec["scope"]})
    return {"token": plain, "info": rec}


@app.post("/api/tokens/delete")
async def api_tokens_delete(payload: TokenDeletePayload, request: Request, user: str = Depends(_session_only)):
    rec = api_tokens.delete(payload.id)
    if not rec:
        raise HTTPException(status_code=404, detail="Token not found")
    audit(request, user, "token_delete", rec["name"])
    return {"ok": True}


@app.get("/api/health")
async def api_health(request: Request):
    """Không cần đăng nhập: {"status": "ok"} (Uptime Kuma). Kèm token / phiên: thêm phiên bản và số app."""
    out: dict[str, Any] = {"status": "ok"}
    try:
        authed = token_user(request) or get_current_user_optional(request)
    except HTTPException:
        authed = None
    if authed:
        out["version"] = APP_VERSION
        tok = getattr(request.state, "api_token", None)
        if tok:
            out["token_scope"] = tok.get("scope", "")
        try:
            data = await asyncio.to_thread(list_all_apps, False)
            out["apps"] = data["summary"]
            out["last_checked"] = data.get("last_checked", "")
            out["updates"] = [a["name"] for a in data["apps"] if a.get("has_update")][:100]
        except Exception as exc:
            out["status"] = "degraded"
            out["error"] = f"Docker: {str(exc)[:200]}"
    return out


@app.post("/api/apps/{container_name}/update", status_code=202)
async def api_update_job(container_name: str, request: Request, payload: Optional[UpdateJobPayload] = None,
                         user: str = Depends(require_user)):
    """Cập nhật 1 app (chạy nền). Trả mã việc ngay; xem tiến trình bằng GET /api/jobs/{id}."""
    tag = ((payload.tag if payload else "") or "").strip()
    info = await asyncio.to_thread(get_app_by_name, container_name)
    if not info:
        raise HTTPException(status_code=404, detail="App not found")
    if not info.get("can_update"):
        raise HTTPException(status_code=400, detail="This app cannot be updated by AppManager")
    if tag:
        allowed = {c.get("tag") for c in (info.get("channels") or [])}
        if tag not in allowed and not await _version_tag_allowed(container_name, info, tag):
            raise HTTPException(status_code=400, detail="This tag is not an available version for this app")
    if jobs.running("update", container_name):
        raise HTTPException(status_code=409, detail="This app is already being updated")
    audit(request, user, "channel_switch" if tag else "update", container_name, ("api " + tag).strip())
    job = jobs.start("update", container_name, user,
                     lambda log: update_app_stream(container_name, log, mode="manual", force_tag=tag))
    return {**job, "url": f"/api/jobs/{job['id']}"}


@app.post("/api/update-all", status_code=202)
async def api_update_all_job(request: Request, user: str = Depends(require_user)):
    """Cập nhật mọi app có bản mới (trừ app đã loại khỏi Update All), chạy nền."""
    if jobs.running("update_all"):
        raise HTTPException(status_code=409, detail="Update all is already running")
    audit(request, user, "update_all", "", "api")

    async def run(log):
        summary: dict[str, Any] = {"ok": True}

        async def ev(e: dict) -> None:
            t = e.get("type")
            if t == "log":
                await log(e.get("text", ""))
            elif t == "app_start":
                await log(f"\n==> {e.get('name')}\n")
            elif t == "complete":
                summary.update(succeeded=e.get("succeeded", 0), failed=e.get("failed", 0), ok=not e.get("failed"))
        await update_all_apps_stream(ev)
        return summary
    job = jobs.start("update_all", "", user, run)
    return {**job, "url": f"/api/jobs/{job['id']}"}


@app.get("/api/jobs")
async def api_jobs(_: str = Depends(require_user)):
    return {"jobs": jobs.recent()}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str, _: str = Depends(require_user)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (jobs are kept in memory until AppManager restarts)")
    return job


# Tài liệu API (Swagger) — chỉ khi đã đăng nhập
def _openapi_schema() -> dict:
    from fastapi.openapi.utils import get_openapi

    if app.openapi_schema:
        return app.openapi_schema
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/api/")]
    schema = get_openapi(
        title="AppManager Pro API", version=APP_VERSION, routes=routes,
        description=(
            "Send an API token (Settings → API tokens) in the header `Authorization: Bearer amp_…`.\n\n"
            "Permissions: **read** = every GET; **update** = read + check for updates, update an app, update all, "
            "start / stop / restart; **full** = everything except account, 2FA, API tokens and registry passwords.\n\n"
            "Updates run in the background: `POST /api/apps/{name}/update` returns a job; poll `GET /api/jobs/{id}`.\n\n"
            "`GET /api/health` needs no token (returns only `status`); with a token it also returns the version and app counts."
        ),
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["bearerAuth"] = {
        "type": "http", "scheme": "bearer", "description": "API token: amp_…"}
    schema["security"] = [{"bearerAuth": []}]
    for path, ops in (schema.get("paths") or {}).items():
        for method, op in ops.items():
            need = api_tokens.min_scope(method, path.replace("{", "x").replace("}", "x"))
            note = f"Token permission: **{need}**" if need else "Not available with an API token (web sign-in only)"
            op["description"] = (op.get("description", "") + "\n\n" + note).strip()
            parts = path.split("/")
            op["tags"] = [parts[2] if len(parts) > 2 else "api"]
    app.openapi_schema = schema
    return schema


@app.get("/openapi.json", include_in_schema=False)
async def openapi_json(request: Request):
    if not (get_current_user_optional(request) or token_user(request)):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return JSONResponse(_openapi_schema())


# ---------------- Nhiều máy chủ (0.18): máy chính gọi REST API của AppManager máy khác bằng API Token ----------------
class ServerPayload(BaseModel):
    id: str = ""
    name: str = ""
    url: str = ""
    token: str = ""
    verify_tls: bool = True


class ServerIdPayload(BaseModel):
    id: str


def _server_or_404(server_id: str) -> dict:
    try:
        return servers.get(server_id)
    except servers.RemoteError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)


async def _remote(s: dict, method: str, path: str, body: Any = None, timeout: float = 20) -> Any:
    try:
        return await servers.call(s, method, path, body, timeout)
    except servers.RemoteError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)


@app.get("/api/servers")
async def api_servers(_: str = Depends(_session_only)):
    return {"servers": servers.list_servers()}


@app.get("/api/servers/status")
async def api_servers_status(_: str = Depends(_session_only)):
    """Kiểm tra mọi máy (song song): kết nối, Token, phiên bản, số app / bản mới."""
    return {"servers": await servers.probe_all()}


@app.post("/api/servers/test")
async def api_server_test(payload: ServerPayload, _: str = Depends(_session_only)):
    """Thử kết nối trước khi lưu (Token để trống khi sửa = dùng Token đã lưu)."""
    existing = None
    if payload.id:
        existing = _server_or_404(payload.id)
    try:
        rec = servers.build(payload.model_dump(), existing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rec.pop("id", None)
    return await servers.probe(rec)


@app.post("/api/servers")
async def api_server_save(payload: ServerPayload, request: Request, user: str = Depends(_session_only)):
    try:
        rec = servers.upsert(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit(request, user, "server_edit" if payload.id else "server_add", rec["name"], rec["url"])
    st = await servers.probe(rec)
    return {"server": servers.public(rec), "status": st}


@app.post("/api/servers/delete")
async def api_server_delete(payload: ServerIdPayload, request: Request, user: str = Depends(_session_only)):
    rec = servers.delete(payload.id)
    if not rec:
        raise HTTPException(status_code=404, detail="Server not found")
    audit(request, user, "server_delete", rec["name"], rec["url"])
    return {"ok": True}


@app.get("/api/servers/{server_id}/apps")
async def api_server_apps(server_id: str, _: str = Depends(_session_only)):
    s = _server_or_404(server_id)
    data = await _remote(s, "GET", "/api/apps", timeout=60)
    apps = [servers.trim_app(a, s["url"]) for a in (data.get("apps") or [])]
    return {"server": servers.public(s), "apps": apps, "summary": data.get("summary") or {},
            "last_checked": data.get("last_checked", ""), "checking": bool(data.get("checking_updates"))}


@app.post("/api/servers/{server_id}/check")
async def api_server_check(server_id: str, request: Request, user: str = Depends(_session_only)):
    s = _server_or_404(server_id)
    audit(request, user, "remote_check", s["name"])
    await _remote(s, "POST", "/api/updates/check", {}, timeout=300)
    return {"ok": True}


@app.post("/api/servers/{server_id}/update-all")
async def api_server_update_all(server_id: str, request: Request, user: str = Depends(_session_only)):
    s = _server_or_404(server_id)
    audit(request, user, "remote_update_all", s["name"])
    return await _remote(s, "POST", "/api/update-all", {})


@app.post("/api/servers/{server_id}/apps/{name}/update")
async def api_server_update(server_id: str, name: str, request: Request, payload: Optional[UpdateJobPayload] = None,
                            user: str = Depends(_session_only)):
    s = _server_or_404(server_id)
    tag = (payload.tag if payload else "") or ""
    audit(request, user, "remote_update", f"{s['name']}/{name}", tag)
    return await _remote(s, "POST", f"/api/apps/{quote(name, safe='')}/update", {"tag": tag})


@app.get("/api/servers/{server_id}/jobs/{job_id}")
async def api_server_job(server_id: str, job_id: str, _: str = Depends(_session_only)):
    s = _server_or_404(server_id)
    if not re.fullmatch(r"[0-9a-f]{6,32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    return await _remote(s, "GET", f"/api/jobs/{job_id}")


@app.post("/api/servers/{server_id}/apps/{name}/{action}")
async def api_server_action(server_id: str, name: str, action: str, request: Request, user: str = Depends(_session_only)):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="Invalid action")
    s = _server_or_404(server_id)
    audit(request, user, f"remote_{action}", f"{s['name']}/{name}")
    return await _remote(s, "POST", f"/api/apps/{quote(name, safe='')}/{action}", {}, timeout=60)


# Mô tả các API hay dùng cho tự động hoá (hiện ở đầu trang /docs); API khác nằm trong mục "Các API khác"
_API_GUIDE: list[tuple[str, str, str, str, str]] = [
    # (method, path, english, tiếng Việt, ví dụ body JSON)
    ("GET", "/api/health", "Health check. Without a token: {\"status\": \"ok\"}. With a token: version, app counts and apps that have an update.",
     "Kiểm tra tình trạng. Không token: {\"status\": \"ok\"}. Có token: phiên bản, số app và các app có bản mới.", ""),
    ("GET", "/api/apps", "All apps with status, current / latest version and whether an update is available.",
     "Mọi app: trạng thái, phiên bản hiện tại / mới nhất, có bản cập nhật hay không.", ""),
    ("GET", "/api/apps/{container_name}/details", "One app in detail (image, ports, mounts, changelog).",
     "Chi tiết một app (image, cổng, thư mục, changelog).", ""),
    ("GET", "/api/apps/{container_name}/versions", "Versions you can switch to for one app.",
     "Các phiên bản có thể chuyển sang của một app.", ""),
    ("POST", "/api/updates/check", "Check every app for new versions now.", "Kiểm tra bản mới cho mọi app ngay.", ""),
    ("POST", "/api/apps/{container_name}/update", "Update one app in the background (health check + automatic rollback). Returns a job; optional body selects a version from /versions.",
     "Cập nhật một app (chạy nền, có kiểm tra sức khoẻ + tự quay lại). Trả về mã việc; body tuỳ chọn để chọn phiên bản trong /versions.", '{"tag": ""}'),
    ("POST", "/api/update-all", "Update every app that has an update (except apps excluded from Update All), in the background.",
     "Cập nhật mọi app có bản mới (trừ app đã loại khỏi Update All), chạy nền.", ""),
    ("GET", "/api/jobs/{job_id}", "Progress of a background job: status (running / success / failed), result and log.",
     "Tiến trình một việc chạy nền: trạng thái (running / success / failed), kết quả và nhật ký.", ""),
    ("GET", "/api/jobs", "Recent background jobs (kept until AppManager restarts).", "Các việc chạy nền gần đây (giữ tới khi AppManager khởi động lại).", ""),
    ("POST", "/api/apps/{container_id}/{action}", "Container action: start, stop or restart (kill needs full access).",
     "Thao tác container: start, stop, restart (kill cần toàn quyền).", ""),
    ("GET", "/api/settings", "Settings and the last 30 update history entries.", "Cài đặt và 30 mục lịch sử cập nhật gần nhất.", ""),
    ("GET", "/api/backups", "App configuration backups.", "Các bản sao lưu cấu hình app.", ""),
    ("POST", "/api/backups/restore", "Restore an app configuration backup.", "Khôi phục bản sao lưu cấu hình app.", '{"app": "<app>", "file": "<backup file>"}'),
    ("GET", "/api/system/storage", "Docker disk usage and reclaimable space.", "Dung lượng Docker và phần có thể dọn.", ""),
    ("GET", "/api/audit", "Activity log (who did what, from which IP).", "Nhật ký hoạt động (ai làm gì, từ IP nào).", ""),
]


@app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def api_docs(request: Request):
    """Tài liệu API gọn cho điện thoại, không cần CDN (chỉ khi đã đăng nhập)."""
    if not get_current_user_optional(request):
        return RedirectResponse(url="/login", status_code=302)
    lang = "vi" if (request.query_params.get("lang") or request.cookies.get("amp_lang") or
                    (request.headers.get("accept-language") or "")[:2]).lower().startswith("vi") else "en"
    schema = _openapi_schema()
    paths = schema.get("paths") or {}
    base = str(request.base_url).rstrip("/")

    def body_fields(op: dict) -> list[str]:
        ref = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
        name = (ref.get("$ref") or "").rsplit("/", 1)[-1]
        props = ((schema.get("components") or {}).get("schemas") or {}).get(name, {}).get("properties") or {}
        return list(props)

    def entry(method: str, path: str, text: str = "", example: str = "") -> dict:
        op = (paths.get(path) or {}).get(method.lower()) or {}
        need = api_tokens.min_scope(method, path.replace("{", "x").replace("}", "x"))
        params = [x.get("name") for x in op.get("parameters") or [] if x.get("in") == "query"]
        curl = f'curl{"" if method == "GET" else " -X " + method} -H "Authorization: Bearer amp_…"'
        if example:
            curl += f" -H \"Content-Type: application/json\" -d '{example}'"
        return {"method": method, "path": path, "text": text or op.get("summary", ""), "scope": need,
                "params": params, "body": body_fields(op), "curl": f"{curl} {base}{path}"}

    guide = [entry(m, pth, vi if lang == "vi" else en, ex) for m, pth, en, vi, ex in _API_GUIDE]
    seen = {(g["method"], g["path"]) for g in guide}
    others = [entry(m.upper(), pth) for pth, ops in sorted(paths.items()) for m in ops
              if (m.upper(), pth) not in seen]
    return templates.TemplateResponse(request, "api_docs.html", {
        "version": APP_VERSION, "lang": lang, "guide": guide, "others": others, "base": base,
        "embed": request.query_params.get("embed") == "1"})


# ---------------- Chuyển container docker run -> Docker Compose ----------------
class ComposeConvertPayload(BaseModel):
    folder: str
    yaml: str


@app.get("/api/apps/{container_name}/compose-convert")
async def api_compose_convert_preview(container_name: str, _: str = Depends(require_user)):
    try:
        return await asyncio.to_thread(compose_convert.generate_compose, container_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Cannot read the container: {str(exc)[:200]}")


@app.get("/api/apps/{container_name}/run-command")
async def api_run_command(container_name: str, _: str = Depends(require_user)):
    """Lệnh `docker run` tương đương với cấu hình hiện tại của container (chỉ xem / chép)."""
    from app.core.docker_client import get_docker_client
    from app.core.run_manager import docker_run_command

    def build() -> str:
        client = get_docker_client()
        c = client.containers.get(container_name)
        try:
            img_cfg = client.images.get(c.attrs.get("Image")).attrs.get("Config") or {}
        except Exception:
            img_cfg = {}
        return docker_run_command(c.attrs, img_cfg)

    try:
        return {"command": await asyncio.to_thread(build)}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Cannot read the container: {str(exc)[:200]}")


@app.post("/api/apps/{container_name}/compose-convert")
async def api_compose_convert(
    container_name: str, payload: ComposeConvertPayload, request: Request, user: str = Depends(require_user)
):
    info = await asyncio.to_thread(get_app_by_name, container_name)
    if not info:
        raise HTTPException(status_code=404, detail="App not found")
    if info.get("is_self"):
        raise HTTPException(status_code=400, detail="AppManager itself cannot be converted here")
    if len(payload.yaml) > 200_000:
        raise HTTPException(status_code=400, detail="docker-compose.yml is too large")
    chunks: list[str] = []

    async def collect(text: str) -> None:
        chunks.append(text)

    res = await compose_convert.convert_stream(container_name, payload.folder.strip(), payload.yaml, collect)
    audit(request, user, "compose_convert", container_name, res.get("error") or res.get("compose_path") or "", bool(res.get("ok")))
    return {**res, "log": "".join(chunks)[-20000:]}


# ---------------- Thông báo ----------------
class NotifyChannelPayload(BaseModel):
    ui_lang: str = ""  # ngôn ngữ giao diện: lần đầu thêm kênh, tin nhắn dùng luôn ngôn ngữ này
    id: str = ""
    type: str
    name: str = ""
    enabled: bool = True
    private: bool = False  # chế độ riêng tư: chỉ gửi tiêu đề chung, không chi tiết
    events: list[str] = []
    config: dict[str, Any] = {}


class NotifySettingsPayload(BaseModel):
    quiet_enabled: Optional[bool] = None
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    disk_pct: Optional[int] = None
    lang: Optional[str] = None


class NotifyIdPayload(BaseModel):
    id: str


@app.get("/api/notify")
async def api_notify_get(_: str = Depends(require_user)):
    return {"channels": notify.masked_channels(), "settings": notify.settings(), "events": list(notify.EVENTS),
            "critical": sorted(notify.CRITICAL)}


@app.post("/api/notify/channels")
async def api_notify_save(payload: NotifyChannelPayload, request: Request, user: str = Depends(require_user)):
    if payload.ui_lang in ("vi", "en") and not get_setting("notify_lang", ""):
        set_setting("notify_lang", payload.ui_lang)
    try:
        ch = await asyncio.to_thread(notify.upsert_channel, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit(request, user, "notify_channel_save", ch["type"], ch["name"])
    return {"ok": True, "id": ch["id"]}


@app.post("/api/notify/channels/delete")
async def api_notify_delete(payload: NotifyIdPayload, request: Request, user: str = Depends(require_user)):
    await asyncio.to_thread(notify.delete_channel, payload.id)
    audit(request, user, "notify_channel_delete", payload.id)
    return {"ok": True}


@app.post("/api/notify/test")
async def api_notify_test(payload: NotifyIdPayload, request: Request, user: str = Depends(require_user)):
    ch = next((c for c in notify.channels() if c["id"] == payload.id), None)
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    ok, detail = await asyncio.to_thread(notify.send_test, ch)
    audit(request, user, "notify_test", ch["type"], detail, ok)
    return {"ok": ok, "detail": detail}


@app.post("/api/notify/settings")
async def api_notify_settings(payload: NotifySettingsPayload, request: Request, user: str = Depends(require_user)):
    await asyncio.to_thread(notify.save_settings, payload.model_dump(exclude_none=True))
    audit(request, user, "notify_settings")
    return {"ok": True, "settings": notify.settings()}


# ---------------- Nguồn cập nhật & giới hạn API ----------------
class RegistryLoginPayload(BaseModel):
    registry: str
    username: str = ""
    token: str = ""


class SourcePayload(BaseModel):
    source: str = ""


@app.get("/api/system/api-status")
async def api_net_status(_: str = Depends(require_user)):
    return {
        "sources": await asyncio.to_thread(net.status),
        "logins": [{"registry": d["registry"], "username": d["username"]} for d in net.registry_logins()],
    }


@app.post("/api/system/registry-logins")
async def api_registry_login_save(payload: RegistryLoginPayload, request: Request, user: str = Depends(require_user)):
    reg = payload.registry.strip().lower()
    if not reg or "/" in reg or " " in reg or len(reg) > 200 or not payload.username.strip() or not payload.token.strip():
        raise HTTPException(status_code=400, detail="Registry, username and token are required")
    ok, msg = await net.test_login(reg, payload.username.strip(), payload.token.strip())
    audit(request, user, "registry_login", reg, msg, ok)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    await asyncio.to_thread(net.save_login, reg, payload.username, payload.token)
    return {"ok": True, "message": msg}


@app.post("/api/system/registry-logins/delete")
async def api_registry_login_delete(payload: RegistryLoginPayload, request: Request, user: str = Depends(require_user)):
    await asyncio.to_thread(net.delete_login, payload.registry)
    audit(request, user, "registry_logout", payload.registry.strip().lower())
    return {"ok": True}


@app.post("/api/system/api-status/resume")
async def api_net_resume(payload: SourcePayload, request: Request, user: str = Depends(require_user)):
    """Bỏ tạm dừng một nguồn (người dùng tự chịu: nguồn có thể vẫn đang giới hạn)."""
    await asyncio.to_thread(net.clear_block, payload.source)
    audit(request, user, "api_resume", payload.source)
    return {"ok": True}


@app.post("/api/system/api-cache/clear")
async def api_net_cache_clear(request: Request, user: str = Depends(require_user)):
    n = await asyncio.to_thread(net.clear_cache)
    audit(request, user, "api_cache_clear", "", str(n))
    return {"ok": True, "cleared": n}


class DuplicateComposePayload(BaseModel):
    action: str  # "merge" | "skip"


@app.post("/api/apps/{container_name}/compose/duplicates")
async def api_compose_duplicates(
    container_name: str, payload: DuplicateComposePayload, request: Request, user: str = Depends(require_user)
):
    res = await resolve_duplicate_compose(container_name, payload.action)
    audit(request, user, f"compose_dup_{payload.action}", container_name, res.get("error") or "", bool(res.get("ok")))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Failed")
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

@app.get("/api/apps/{container_name}/uninstall-check")
async def api_uninstall_check(container_name: str, _: str = Depends(require_user)):
    """Trước khi gỡ: app khác dùng chung image / AppData, stack nhiều service (để người dùng biết ảnh hưởng)."""
    from app.core.compose_manager import uninstall_check

    res = await uninstall_check(container_name)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res.get("error") or "Not found")
    return res


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
        remove_image_users=payload.remove_image_users,
    )
    audit(
        request, user, "uninstall", container_name,
        f"compose={payload.remove_compose} images={payload.remove_images} appdata={payload.remove_appdata} also={','.join(payload.remove_image_users)[:200]}",
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
    # Kết quả tự cập nhật do container phụ để lại -> ghi vào Lịch sử ngay khi mở (không phải chờ tới phút sau)
    await asyncio.to_thread(collect_self_update_result)
    return {
        "settings": {**get_public_settings(), "auto_prune_next_run": get_auto_prune_next_run()},
        "history": get_update_history(30),
    }


@app.get("/api/history/{history_id}/log")
async def api_update_log(history_id: int, _: str = Depends(require_user)):
    item = await asyncio.to_thread(get_update_log, history_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return item


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
    set_setting("backup_file_max_mb", str(max(1, min(10240, payload.backup_file_max_mb))))
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
        return JSONResponse(status_code=400, content={"detail": res.get("error") or "Restore failed", "log": res.get("log") or []})
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

    # ?tag=beta : chuyển kênh phát hành; chỉ nhận tag nằm trong danh sách kênh đã phát hiện của app
    force_tag = (websocket.query_params.get("tag") or "").strip()
    if force_tag:
        info = await asyncio.to_thread(get_app_by_name, container_name)
        allowed = {c.get("tag") for c in ((info or {}).get("channels") or [])}
        if force_tag not in allowed and not (info and await _version_tag_allowed(container_name, info, force_tag)):
            await send_log("[ERROR] This tag is not an available version for this app.\n")
            await websocket.close()
            return
    audit(websocket, ws_user, "channel_switch" if force_tag else "update", container_name, force_tag)
    try:
        await update_app_stream(container_name, send_log, mode="manual", force_tag=force_tag)
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
