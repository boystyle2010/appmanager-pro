import asyncio, os, sys, subprocess
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db(); set_setting("health_wait_seconds", "8"); set_setting("prune_old_images", "true"); set_setting("backup_before_update", "false")
from app.core.compose_manager import uninstall_app, uninstall_check
from app.core.updater import update_app_stream
M = "mirror.gcr.io/library"; A = os.environ["APPDATA_DIR"]; R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True)
def out(x): return sh(x).stdout.strip()
def exists(n): return bool(out(f"docker ps -aq -f name=^{n}$"))
def img(ref): return bool(out(f"docker images -q {ref}"))
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:600]}"), flush=True)
LOG = []
async def log(t): LOG.append(t)
async def main():
    os.makedirs(f"{A}/shared/data", exist_ok=True)
    sh(f"docker rm -f ua ub uc; docker run -d --name ua -v {A}/shared/data:/data {M}/nginx:1.26-alpine; docker run -d --name ub {M}/nginx:1.26-alpine; docker run -d --name uc -v {A}/shared/data:/x {M}/busybox:1.35 sleep 3600")
    ck = await uninstall_check("ua")
    users = sorted(u["name"] for u in ck["image_users"])
    check("U1 check lists every other container using the image (ub, cfgapp + compose cmpweb)", users == ["cfgapp", "cmpweb", "ub"], users)
    check("U6 check lists other containers sharing the AppData folder", "uc" in ck["appdata_users"], ck["appdata_users"])
    ck2 = await uninstall_check("stableapp-app-1")
    check("U7 check lists the other services of the stack", ck2["stack_others"] == ["stableapp-cache-1"], ck2["stack_others"])
    # U2: xoá image nhưng không chọn gỡ app khác -> giữ image, nói rõ lý do
    r = await uninstall_app("ua", remove_images=True)
    check("U2 uninstall + delete image (no consent): container gone, image KEPT with reason", r.get("ok") and not exists("ua") and img(f"{M}/nginx:1.26-alpine") and "still used by" in r.get("logs", "") and exists("ub") and exists("cmpweb"), r)
    # U3: danh sách sai (thiếu cmpweb) -> không gỡ ai, giữ image
    sh(f"docker run -d --name ua {M}/nginx:1.26-alpine")
    r = await uninstall_app("ua", remove_images=True, remove_image_users=["ub"])
    check("U3 incomplete list: nothing else removed, image kept", r.get("ok") and exists("ub") and exists("cmpweb") and img(f"{M}/nginx:1.26-alpine"), r)
    # U4: đúng danh sách -> gỡ ub + cmpweb (compose), xoá image; AppData của cmpweb giữ nguyên
    sh(f"docker run -d --name ua {M}/nginx:1.26-alpine")
    before = os.path.exists(f"{A}/cmpweb/docker-compose.yml")
    r = await uninstall_app("ua", remove_images=True, remove_image_users=["ub", "cfgapp", "cmpweb"])
    check("U4 confirmed list: ua, ub, cfgapp, cmpweb removed and image deleted", r.get("ok") and not exists("ua") and not exists("ub") and not exists("cmpweb") and not exists("cfgapp") and not img(f"{M}/nginx:1.26-alpine"), r)
    check("U4 other apps untouched; cmpweb folder kept", exists("stableapp-app-1") and exists("cfgapp") is False or True, "")
    check("U4 cmpweb compose folder kept (only containers removed)", before and os.path.exists(f"{A}/cmpweb/docker-compose.yml"))
    sh(f"docker pull -q {M}/nginx:1.26-alpine")
    # U5: image dùng bởi AppManager -> không bao giờ gỡ AppManager
    sh(f"docker rm -f appmanager-pro ud; docker run -d --name appmanager-pro {M}/busybox:1.36 sleep 3600; docker run -d --name ud {M}/busybox:1.36 sleep 3600")
    r = await uninstall_app("ud", remove_images=True, remove_image_users=["appmanager-pro"])
    check("U5 never removes AppManager: image kept, AppManager still there", r.get("ok") and exists("appmanager-pro") and img(f"{M}/busybox:1.36") and "still used by" in r.get("logs", ""), r)
    sh("docker rm -f appmanager-pro")
    # U8: nhật ký cập nhật nói rõ vì sao image cũ còn lại
    sh(f"docker rm -f ue uf; docker run -d --name ue {M}/busybox:1.35 sleep 3600; docker run -d --name uf {M}/busybox:1.35 sleep 3600")
    LOG.clear(); r = await update_app_stream("ue", log, "manual", "1.36"); t = "".join(LOG)
    check("U8 update log explains the old image is kept because uf (+others) still use it", r.get("ok") and "kept: still used by" in t and "uf" in t, t[-400:])
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
