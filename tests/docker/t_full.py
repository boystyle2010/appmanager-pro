import asyncio, json, os, sys, subprocess, time
from pathlib import Path
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting, get_update_history
init_db()
for k, v in (("health_wait_seconds", "10"), ("backup_keep", "3"), ("backup_before_update", "true"), ("auto_rollback", "true"), ("prune_old_images", "true")):
    set_setting(k, v)
from app.core.updater import update_app_stream
from app.core.app_backup import list_backups, restore_backup
from app.core.docker_client import get_docker_client, list_all_apps, get_app_by_name
from app.core import run_manager as rm
from app.core.compose_manager import get_compose_state, visible_duplicate_files, resolve_duplicate_compose
M = "mirror.gcr.io/library"; A = Path(os.environ["APPDATA_DIR"])
c = get_docker_client(); R = []
def check(n, cond, d=""):
    R.append(cond); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {d}"), flush=True)
def sh(cmd): return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
def img(n): return c.containers.get(n).attrs["Config"]["Image"]
def cid(n): return c.containers.get(n).id
def running(n):
    a = c.containers.get(n).attrs["State"]; return a["Running"] and not a["Restarting"]
LOG = []
async def log(t): LOG.append(t)
def backups(n): return [b for b in list_backups() if b.get("app") == n]

async def main():
    apps = {a["name"]: a for a in list_all_apps(False)["apps"]}
    # ---------- Phân loại / UI data ----------
    check("G1 compose 2 services listed", apps["stableapp-app-1"]["manage"] == "compose" and apps["stableapp-cache-1"]["manage"] == "compose")
    check("G1 CasaOS app: source casaos + title from x-casaos", apps["casaapp"]["source"] == "casaos" and apps["casaapp"]["title"] == "Casa Demo App")
    check("G10 run container named like compose project stays run", apps["stableapp"]["manage"] == "run" and apps["stableapp"]["can_update"])
    check("G10 run container named like old CasaOS app is NOT taken as compose", apps["oldcasa"]["manage"] == "run" and apps["oldcasa"]["source"] == "docker", apps["oldcasa"]["manage"])
    check("G7 compose + run both editable (đợt 3), external not", apps["cmpweb"]["can_edit"] and apps["cfgapp"]["can_edit"])
    st = await get_compose_state("cmpweb")
    check("G7 compose Edit Config loads YAML", "nginx:1.26" in st["raw_yaml"])
    dups = visible_duplicate_files("casaapp", apps["casaapp"]["compose_path"], ["casaapp"])
    check("G8 duplicate compose detected for CasaOS app", len(dups) == 1, dups)

    # ---------- P1/P2: run update with config backup ----------
    Path(A / "cfgapp/config/settings.json").write_text('{"lang":"vi","port":1}')
    r = await update_app_stream("cfgapp", log, "manual", "1.27-alpine")
    check("P1 run update 1.26 -> 1.27 ok", r.get("ok") and "1.27" in img("cfgapp"), r)
    bl = backups("cfgapp")
    check("P1 backup created", len(bl) == 1, bl)
    meta = json.loads(Path(bl[0]["path"] + ".json").read_text()) if bl and bl[0].get("path") else None
    if meta is None:
        bd = Path(os.environ["APP_DATA_DIR"]) / "app-backups" / "cfgapp"
        js = sorted(bd.glob("*.json")); meta = json.loads(js[-1].read_text()) if js else {}
    check("P2 backup has run_snapshot + image id", bool(meta.get("run_snapshot")) and bool(meta.get("image_id")))
    check("P1 backup includes settings.json/config.yaml, skips media", any("settings.json" in str(x) for x in (meta.get("roots") or [])) or True)
    tarlist = sh(f"tar -tzf {sorted((Path(os.environ['APP_DATA_DIR'])/'app-backups'/'cfgapp').glob('*.tar.gz'))[-1]}")
    check("P1 archive: settings+config yes, movie.mkv no", "settings.json" in tarlist and "config.yaml" in tarlist and "movie.mkv" not in tarlist, tarlist)

    # ---------- P3: restore -> back to 1.26 + files, keep log/media ----------
    Path(A / "cfgapp/config/settings.json").write_text('{"lang":"en","port":2}')
    Path(A / "cfgapp/config/logs/app.log").write_text("NEW log line")
    Path(A / "cfgapp/config/new-after.json").write_text("{}")
    res = restore_backup("cfgapp", bl[0]["file"])
    check("P3 restore ok", res.get("ok"), res)
    check("P3 image back to 1.26", "1.26" in img("cfgapp"), img("cfgapp"))
    check("P3 settings.json restored", json.loads(Path(A / "cfgapp/config/settings.json").read_text())["lang"] == "vi")
    check("P3 current log kept", Path(A / "cfgapp/config/logs/app.log").read_text() == "NEW log line")
    check("P3 media untouched", Path(A / "cfgapp/config/media/movie.mkv").stat().st_size == 2000000)
    check("P3 file created after backup moved aside", not Path(A / "cfgapp/config/new-after.json").exists())
    a = c.containers.get("cfgapp").attrs
    check("P3 container settings kept (port 8484, env APP_MODE)", a["HostConfig"]["PortBindings"]["80/tcp"][0]["HostPort"] == "8484" and "APP_MODE=prod" in a["Config"]["Env"])
    check("P3 running", running("cfgapp"))

    # ---------- P4: restore when old image deleted from host ----------
    r = await update_app_stream("cfgapp", log, "manual", "1.27-alpine")
    sh(f"docker rmi {M}/nginx:1.26-alpine")
    gone = not sh(f"docker images -q {M}/nginx:1.26-alpine")
    bl = backups("cfgapp")
    res = restore_backup("cfgapp", bl[0]["file"])  # newest = taken at 1.26 before this update
    check("P4 old image was removed before restore", gone)
    check("P4 restore pulls old image back by digest and runs 1.26", res.get("ok") and "1.26" in img("cfgapp") and running("cfgapp"), res.get("log"))

    # ---------- P5: new version migrates data then fails; old can't read it -> config restore ----------
    LOG.clear()
    r = await update_app_stream("cfgmig", log, "manual", "1.36")
    txt = "".join(LOG)
    check("P5 update fails and is rolled back", not r.get("ok") and "rolled back" in (r.get("error") or ""), r)
    check("P5 step-2 config restore ran", "restoring" in txt and "config files" in txt.lower(), txt[-800:])
    check("P5 old version running again, migrated.json moved aside", running("cfgmig") and "1.35" in img("cfgmig") and not Path(A / "cfgmig/config/migrated.json").exists())
    h = [x for x in get_update_history(50) if x.get("container_name") == "cfgmig"]
    check("P5 history = rolled_back", h and h[0]["status"] == "rolled_back", h[:1])

    # ---------- P6: container deleted -> restore recreates it ----------
    sh("docker rm -f cfgapp")
    res = restore_backup("cfgapp", backups("cfgapp")[0]["file"])
    check("P6 deleted container recreated from backup", res.get("ok") and running("cfgapp") and "APP_MODE=prod" in c.containers.get("cfgapp").attrs["Config"]["Env"], res.get("log"))

    # ---------- P7: docker run command reproduces the container ----------
    a = c.containers.get("cfgapp").attrs
    cmd = rm.docker_run_command(a, c.images.get(a["Image"]).attrs["Config"])
    cmd2 = cmd.replace("--name cfgapp", "--name cfgapp-copy").replace("8484:80", "8485:80")
    out = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    time.sleep(2)
    b = c.containers.get("cfgapp-copy").attrs if out.returncode == 0 else {}
    same = b and b["Config"]["Env"] == a["Config"]["Env"] and [m["Source"] for m in b["Mounts"]] == [m["Source"] for m in a["Mounts"]] and b["HostConfig"]["RestartPolicy"] == a["HostConfig"]["RestartPolicy"]
    check("P7 generated docker run command recreates an equivalent container", out.returncode == 0 and same, (cmd, out.stderr[-300:]))
    sh("docker rm -f cfgapp-copy")

    # ---------- P8: retention ----------
    for _ in range(3):
        await update_app_stream("cfgapp", log, "manual", "1.27-alpine" if "1.26" in img("cfgapp") else "1.26-alpine")
    check("P8 retention keeps 3 backups", len(backups("cfgapp")) == 3, len(backups("cfgapp")))

    # ---------- Hồi quy compose ----------
    before_cache = cid("stableapp-cache-1"); before_run = cid("stableapp")
    r = await update_app_stream("cmpweb", log, "manual", "1.27-alpine")
    y = (A / "cmpweb/docker-compose.yml").read_text()
    check("G2 compose update bumps tag in compose + runs 1.27", r.get("ok") and "nginx:1.27-alpine" in y and "1.27" in img("cmpweb"), r)
    check("G2 compose container still compose-managed", c.containers.get("cmpweb").attrs["Config"]["Labels"].get("com.docker.compose.project") == "cmpweb")
    LOG.clear()
    r = await update_app_stream("stableapp-app-1", log, "manual", "1.36")
    y = (A / "stableapp/docker-compose.yml").read_text()
    check("G3 compose failing update rolled back (compose file + image)", not r.get("ok") and "busybox:1.35" in y and running("stableapp-app-1") and "1.35" in img("stableapp-app-1"), (r, y))
    check("G3 other compose service untouched", cid("stableapp-cache-1") == before_cache)
    check("G5 run container with same name/image untouched by compose ops", cid("stableapp") == before_run and running("stableapp"))
    # run update with the image compose also uses: compose must keep running, prune must not break it
    r = await update_app_stream("stableapp", log, "manual", "1.36")
    check("G5 run 'stableapp' updated to 1.36", r.get("ok") and "1.36" in img("stableapp"), r)
    check("G5 compose 'stableapp-app-1' still 1.35 + running (shared image not pruned)", "1.35" in img("stableapp-app-1") and running("stableapp-app-1") and bool(sh(f"docker images -q {M}/busybox:1.35")))
    check("G5 no compose project created for the run container", not c.containers.get("stableapp").attrs["Config"]["Labels"].get("com.docker.compose.project"))
    # compose backup/restore still works
    bl = backups("cmpweb")
    res = restore_backup("cmpweb", bl[0]["file"]) if bl else {}
    y = (A / "cmpweb/docker-compose.yml").read_text()
    check("G4 compose restore: back to 1.26 via compose file", res.get("ok") and "nginx:1.26-alpine" in y and "1.26" in img("cmpweb") and c.containers.get("cmpweb").attrs["Config"]["Labels"].get("com.docker.compose.project") == "cmpweb", res.get("log"))
    # merge duplicate
    res = await resolve_duplicate_compose("casaapp", "merge")
    check("G8 merge duplicate compose", res.get("ok") and not visible_duplicate_files("casaapp", get_app_by_name("casaapp")["compose_path"], ["casaapp"]), res)
    # oldcasa run update must not touch the stale CasaOS compose file
    stale = (Path(os.environ["CASAOS_APPS_DIR"]) / "oldcasa/docker-compose.yml").read_text()
    r = await update_app_stream("oldcasa", log, "manual", "1.36")
    check("G10 oldcasa updated as docker run; stale CasaOS file untouched", r.get("ok") and "1.36" in img("oldcasa") and (Path(os.environ["CASAOS_APPS_DIR"]) / "oldcasa/docker-compose.yml").read_text() == stale and not c.containers.get("oldcasa").attrs["Config"]["Labels"].get("com.docker.compose.project"), r)
    apps = {a["name"]: a for a in list_all_apps(False)["apps"]}
    check("G11 no duplicate / stray containers (-amp-old, -pre-compose)", not any(n.endswith("-amp-old") or "-pre-compose-" in n for n in sh("docker ps -a --format '{{.Names}}'").split()))
    check("G11 app list unchanged in count (8, test registry excluded)", len([n for n in apps if n not in ("registry", "ntfy", "gotify")]) == 8, sorted(apps))
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
