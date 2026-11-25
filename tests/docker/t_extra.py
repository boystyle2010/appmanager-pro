import asyncio, io, os, sys, subprocess
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db(); set_setting("health_wait_seconds", "8"); set_setting("backup_before_update", "true")
from ruamel.yaml import YAML
from app.core.compose_manager import get_compose_state, save_and_apply_compose
from app.core.updater import update_app_stream
from app.core.app_backup import list_backups, restore_backup
from app.core.docker_client import get_docker_client
c = get_docker_client(); R = []; S = os.environ["S"]
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
def A(n): return c.containers.get(n).attrs
def yl(t): return YAML().load(t)
def yd(d):
    b = io.StringIO(); y = YAML(); y.indent(mapping=2, sequence=4, offset=2); y.dump(d, b); return b.getvalue()
def svc(d): return next(iter(d["services"].values()))
async def log(t): pass
async def edit(name, fn):
    d = yl((await get_compose_state(name))["raw_yaml"]); fn(svc(d)); return await save_and_apply_compose(name, yd(d))

async def main():
    # X1 sửa cấu hình trong lúc đang cập nhật
    t = asyncio.create_task(update_app_stream("redis", log, "manual", "7.4-alpine"))
    await asyncio.sleep(1.5)
    r = await edit("redis", lambda s: s.setdefault("environment", []).append("X=1"))
    await t
    check("X1 edit while updating is refused (no clash)", not r.get("ok") and "being updated" in (r.get("error") or ""), r)
    # X2 sửa container đang dừng -> vẫn dừng, có cấu hình mới
    r = await edit("bb-stopped", lambda s: s.setdefault("environment", []).append("STOPPED_EDIT=1"))
    a = A("bb-stopped")
    check("X2 stopped container edited and left stopped", r.get("ok") and not a["State"]["Running"] and "STOPPED_EDIT=1" in a["Config"]["Env"], r)
    # X3 container do công cụ khác quản lý: không sửa được
    try:
        await get_compose_state("ext-swarm"); opened = True
    except Exception:
        opened = False
    r = await save_and_apply_compose("ext-swarm", "services:\n  x:\n    image: busybox\n")
    check("X3 external container cannot be opened / applied", not opened and not r.get("ok"), r)
    # X4 hồi quy: sửa app compose vẫn ghi vào file compose
    r = await edit("demo-demo-1", lambda s: s.__setitem__("environment", ["FROM_EDITOR=1"]))
    txt = open(f"{S}/stack/demo/docker-compose.yml").read()
    a = A("demo-demo-1")
    check("X4 compose edit writes the compose file and stays compose-managed", r.get("ok") and "FROM_EDITOR=1" in txt and "FROM_EDITOR=1" in a["Config"]["Env"] and a["Config"]["Labels"].get("com.docker.compose.project") == "demo", r)
    # X6/X5: cập nhật (có sao lưu) -> sửa -> cập nhật giữ cấu hình đã sửa -> khôi phục về trước khi sửa
    r = await update_app_stream("bb-none", log, "manual", "1.36")
    b_before_edit = [b for b in list_backups() if b["app"] == "bb-none"][0]["file"]
    r = await edit("bb-none", lambda s: s.setdefault("environment", []).append("EDITED=yes"))
    check("X5 edit after update ok", r.get("ok") and "EDITED=yes" in A("bb-none")["Config"]["Env"], r)
    r = await update_app_stream("bb-none", log, "manual", "1.38")
    a = A("bb-none")
    check("X5 later update keeps the edited setting", r.get("ok") and "1.38" in a["Config"]["Image"] and "EDITED=yes" in a["Config"]["Env"], r)
    res = restore_backup("bb-none", b_before_edit)
    a = A("bb-none")
    check("X6 restore brings back settings + image from before the edit", res.get("ok") and "EDITED=yes" not in (a["Config"]["Env"] or []) and "1.35" in a["Config"]["Image"] and a["State"]["Running"], res.get("log"))
    # X7 áp dụng không đổi gì
    st = await get_compose_state("web")
    r = await save_and_apply_compose("web", st["raw_yaml"]); a = A("web")
    check("X7 apply without changes keeps everything working", r.get("ok") and a["State"]["Running"] and a["NetworkSettings"]["Networks"]["appnet"]["IPAddress"] == "172.30.0.50", r)
    # X8 khôi phục khi image KHÔNG đổi nhưng cấu hình đã sửa -> cấu hình trở lại
    await update_app_stream("redis", log, "manual", "7.2-alpine")
    bfile = [b for b in list_backups() if b["app"] == "redis"][0]["file"]
    r = await edit("redis", lambda s: s.setdefault("environment", []).append("AFTER_BACKUP=1"))
    meta_img = __import__("json").load(open(f"{os.environ['APP_DATA_DIR']}/app-backups/redis/{bfile}.json"))["image_id"]
    res = restore_backup("redis", bfile); a = A("redis")
    check("X8 same image + changed settings: restore reverts the settings", r.get("ok") and meta_img == a["Image"] and "AFTER_BACKUP=1" not in (a["Config"]["Env"] or []) and a["State"]["Running"], (res.get("log"), a["Config"]["Env"]))
    # X9 container --rm: chỉ xem; cập nhật / chuyển compose bị từ chối, container vẫn còn
    subprocess.run("docker rm -f tmp-rm; docker run -d --rm --name tmp-rm mirror.gcr.io/library/busybox:1.35 sleep 3600", shell=True, capture_output=True)
    from app.core.docker_client import list_all_apps
    from app.core.compose_convert import convert_stream
    ap = {x["name"]: x for x in list_all_apps(False)["apps"]}["tmp-rm"]
    r1 = await update_app_stream("tmp-rm", log, "manual", "1.36")
    r2 = await convert_stream("tmp-rm", f"{S}/conv-tmp", "services: {}", log)
    alive = bool(subprocess.run("docker ps -q -f name=^tmp-rm$", shell=True, capture_output=True, text=True).stdout.strip())
    check("X9 --rm container: read-only, update + convert refused, still running", ap["manage"] == "external" and ap["compose_issue"] == "autoremove" and not ap["can_update"] and not r1.get("ok") and not r2.get("ok") and alive, (ap["manage"], r1, r2, alive))
    # X10 image ghim digest: cập nhật không tự đổi sang :latest
    subprocess.run("docker pull -q mirror.gcr.io/library/busybox:1.36", shell=True, capture_output=True)
    dig = subprocess.run("docker image inspect -f '{{index .RepoDigests 0}}' mirror.gcr.io/library/busybox:1.36", shell=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(f"docker rm -f pinned; docker run -d --name pinned {dig} sleep 3600", shell=True, capture_output=True)
    r = await update_app_stream("pinned", log, "manual", "")
    check("X10 digest-pinned container keeps its digest on update", r.get("ok") and A("pinned")["Config"]["Image"] == dig, (r, A("pinned")["Config"]["Image"]))
    # X11 alias ngắn dạng hex được giữ
    subprocess.run("docker rm -f aliasapp; docker network create aliasnet; docker run -d --name aliasapp --network aliasnet --network-alias ab --network-alias db mirror.gcr.io/library/busybox:1.35 sleep 3600", shell=True, capture_output=True)
    r = await update_app_stream("aliasapp", log, "manual", "1.36")
    al = A("aliasapp")["NetworkSettings"]["Networks"]["aliasnet"].get("Aliases") or []
    check("X11 short aliases (ab, db) kept", r.get("ok") and "ab" in al and "db" in al, al)
    # X12 ghi kết quả tự cập nhật từ 2 luồng cùng lúc -> 1 dòng Lịch sử
    import threading, json as _j
    from app.core import updater as up
    from app.core.database import get_update_history as gh
    up.SELF_RESULT_FILE.write_text(_j.dumps({"container": "appmanager-pro", "title": "AppManager Pro", "from_version": "1", "to_version": "2", "status": "success", "message": "race-test", "log": ""}))
    ts = [threading.Thread(target=up.collect_self_update_result) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check("X12 concurrent result collection writes History once", sum(1 for h in gh(50) if h.get("message") == "race-test") == 1)
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
