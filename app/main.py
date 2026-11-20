import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path

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
from app.core.database import get_user_by_username, has_admin_user, init_db
from app.core.docker_client import container_action, get_docker_client, list_all_apps

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR.parent / "assets"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="AppManager Pro", version="0.1.0", lifespan=lifespan)

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


# ---------------- Pages ----------------

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if not has_admin_user():
        return RedirectResponse(url="/login", status_code=302)
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "username": user, "version": app.version},
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


# ---------------- Docker App APIs ----------------

@app.get("/api/apps")
async def api_list_apps(_: str = Depends(require_user)):
    try:
        data = await asyncio.to_thread(list_all_apps)
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker socket error: {e}")


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


# ---------------- WebSocket Live Logs ----------------

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
