import asyncio, os, sys, subprocess
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting; init_db()
set_setting("prune_old_images", "true"); set_setting("health_wait_seconds", "10")
from app.core.updater import update_app_stream
from app.core.app_backup import list_backups, restore_backup
from app.core.docker_client import get_docker_client
c = get_docker_client(); M = "mirror.gcr.io/library"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
async def log(t): pass
async def main():
    sh(f"cd {os.environ['APPDATA_DIR']}/cmpweb && docker compose down")
    cur = c.containers.get("cfgapp").attrs["Config"]["Image"]
    if "1.26" not in cur:
        print("prep", await update_app_stream("cfgapp", log, "manual", "1.26-alpine"))
    users = sh(f"docker ps -a --filter ancestor={M}/nginx:1.26-alpine --format '{{{{.Names}}}}'")
    print("containers using 1.26:", users)
    r = await update_app_stream("cfgapp", log, "manual", "1.27-alpine")
    gone = not sh(f"docker images -q {M}/nginx:1.26-alpine")
    print(("PASS" if r.get("ok") and gone else "FAIL"), "P4 update to 1.27 auto-pruned old 1.26 image:", gone)
    b = [x for x in list_backups() if x["app"] == "cfgapp"][0]
    res = restore_backup("cfgapp", b["file"])
    a = c.containers.get("cfgapp").attrs
    ok = res.get("ok") and "1.26" in a["Config"]["Image"] and a["State"]["Running"]
    print(("PASS" if ok else "FAIL"), "P4 restore re-pulled the removed image by digest and runs 1.26")
    print("\n".join(l for l in res.get("log", []) if "Pull" in l or "OK" in l or "Tagged" in l))
asyncio.run(main())
