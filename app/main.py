import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.auth import (
    clear_failed_attempts,
    clear_session_cookie,
    get_client_ip,
    get_current_user_optional,
    is_ip_locked,
    record_failed_attempt,
    require_user,
    set_session_cookie,
    setup_first_admin,
    verify_password,
    verify_websocket_user,
)
from app.core.database import (
    get_app_pref,
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
from app.core.scheduler import configure_jobs, start_scheduler, stop_scheduler
from app.core.updater import update_all_apps_stream, update_app_stream

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR.parent / "assets"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="AppManager Pro", version="0.2.1", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class SetupPayload(BaseModel):
    username: str
    password: str
    confirm_password: str


class LoginPayload(BaseModel):
    username: str
    password: str
    remember: bool = True


class AppPrefPayload(BaseModel):
    auto_update: Optional[bool] = None
    custom_repo: Optional[str] = None
    skipped_digest: Optional[str] = None


class SettingsPayload(BaseModel):
    check_interval_hours: int = 6
    auto_update_enabled: bool = False
    auto_update_time: str = "03:30"
    prune_old_images: bool = True
    github_token: Optional[str] = None


# ---------------- PWA Manifest & Pages ----------------

@app.get("/manifest.json")
async def pwa_manifest():
    return JSONResponse(
        content={
            "name": "AppManager Pro",
            "short_name": "AppManager",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0a1122",
            "theme_color": "#0a1122",
            "icons": [
                {"src": "/assets/icon.png", "sizes": "512x512", "type": "image/png"}
            ],
        }
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if not has_admin_user() or not get_current_user_optional(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "version": app.version},
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    is_setup = not has_admin_user()
    if not is_setup and get_current_user_optional(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        "auth.html",
        {"request": request, "is_setup": is_setup, "version": app.version},
    )


# ---------------- Auth APIs ----------------

@app.post("/api/auth/setup")
async def api_setup(payload: SetupPayload, request: Request, response: Response):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    setup_first_admin(payload.username, payload.password)
    set_session_cookie(response, request, payload.username.strip(), remember=True)
    return {"ok": True}


@app.post("/api/auth/login")
async def api_login(payload: LoginPayload, request: Request, response: Response):
    ip = get_client_ip(request)
    lock_remaining = is_ip_locked(ip)
    if lock_remaining > 0:
        mins = (lock_remaining + 59) // 60
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {mins} minute(s).",
        )

    user = get_user_by_username(payload.username.strip())
    if not user or not verify_password(user["password_hash"], payload.password):
        record_failed_attempt(ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    clear_failed_attempts(ip)
    set_session_cookie(response, request, user["username"], remember=payload.remember)
    return {"ok": True, "username": user["username"]}


@app.post("/api/auth/logout")
async def api_logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


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
    # Nếu chưa từng check app này, check ngay lần đầu mở modal
    if not cache or not cache.get("checked_at"):
        cache = await check_one_app_by_name(container_name) or {}
        app_info = await asyncio.to_thread(get_app_by_name, container_name) or app_info

    pref = get_app_pref(container_name)
    return {
        "app": app_info,
        "changelog": cache.get("changelog") or "",
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


@app.post("/api/apps/{container_id}/{action}")
async def api_app_action(container_id: str, action: str, _: str = Depends(require_user)):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="Invalid action")
    try:
        return await asyncio.to_thread(container_action, container_id, action)
    except KeyError:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/settings")
async def api_get_settings(_: str = Depends(require_user)):
    return {
        "settings": get_public_settings(),
        "history": get_update_history(30),
    }


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload, _: str = Depends(require_user)):
    set_setting("check_interval_hours", str(max(1, min(168, payload.check_interval_hours))))
    set_setting("auto_update_enabled", "true" if payload.auto_update_enabled else "false")
    set_setting("auto_update_time", payload.auto_update_time)
    set_setting("prune_old_images", "true" if payload.prune_old_images else "false")
    if payload.github_token is not None:
        set_setting("github_token", payload.github_token.strip())
    configure_jobs()
    return {"ok": True, "settings": get_public_settings()}


# ---------------- WebSockets: Live Logs & Live Update ----------------

@app.websocket("/ws/logs/{container_id}")
async def ws_container_logs(websocket: WebSocket, container_id: str):
    if not verify_websocket_user(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=500)
    stop_event = threading.Event()
    log_stream = None

    def reader_thread():
        nonlocal log_stream
        try:
            client = get_docker_client()
            container = client.containers.get(container_id)
            log_stream = container.logs(
                stream=True, follow=True, tail=150, timestamps=True
            )
            for chunk in log_stream:
                if stop_event.is_set():
                    break
                text = chunk.decode("utf-8", errors="replace")
                loop.call_soon_threadsafe(queue.put_nowait, text)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, f"\n[AppManager Pro] Stream closed: {exc}\n")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    thread = threading.Thread(target=reader_thread, daemon=True)
    thread.start()

    try:
        while True:
            line = await queue.get()
            if line is None:
                break
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        if log_stream is not None:
            try:
                log_stream.close()
            except Exception:
                pass


@app.websocket("/ws/update/{container_name}")
async def ws_update_app(websocket: WebSocket, container_name: str):
    if not verify_websocket_user(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def send_log(text: str):
        try:
            await websocket.send_text(text)
        except Exception:
            pass

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
    if not verify_websocket_user(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def send_event(payload: dict):
        try:
            await websocket.send_json(payload)
        except Exception:
            pass

    try:
        await update_all_apps_stream(send_event)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
