import asyncio, os, sys, subprocess, time
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db()
for k, v in (("health_wait_seconds", "15"), ("backup_before_update", "true"), ("auto_rollback", "true"), ("prune_old_images", "false")):
    set_setting(k, v)
from app.core.updater import update_app_stream
from app.core.app_backup import list_backups, restore_backup
from app.core.compose_manager import uninstall_app
from app.core.docker_client import get_docker_client, list_all_apps
c = get_docker_client(); R = []; S = os.environ["S"]; A = os.environ["APPDATA_DIR"]; M = "mirror.gcr.io/library"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True)
def out(x): return sh(x).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:700]}"), flush=True)
def st(n):
    try:
        a = c.containers.get(n).attrs; return a["State"]["Status"], a["Config"]["Image"]
    except Exception: return "", ""
LOG = []
async def log(t): LOG.append(t)

async def main():
    # ---------- #2 registry riêng tư ----------
    sh("docker rm -f privreg; mkdir -p %s/auth" % S)
    htp = out(f"docker run --rm --entrypoint htpasswd {M}/httpd:2 -Bbn tester s3cret")
    open(f"{S}/auth/htpasswd", "w").write(htp + "\n")
    sh(f"docker run -d --name privreg -p 5001:5000 -v {S}/auth:/auth -e REGISTRY_AUTH=htpasswd -e REGISTRY_AUTH_HTPASSWD_REALM=r -e REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd {M}/registry:2")
    time.sleep(3)
    sh("echo s3cret | docker login localhost:5001 -u tester --password-stdin")
    for t in ("1.35", "1.36"):
        sh(f"docker tag {M}/busybox:{t} localhost:5001/priv:{t} && docker push -q localhost:5001/priv:{t}")
    sh("docker rmi localhost:5001/priv:1.36; docker rm -f privapp; docker run -d --name privapp localhost:5001/priv:1.35 sleep 3600")
    sh("docker logout localhost:5001")
    LOG.clear(); r = await update_app_stream("privapp", log, "manual", "1.36"); txt = "".join(LOG)
    check("M2 private image without login: update refused, container untouched", not r.get("ok") and st("privapp") == ("running", "localhost:5001/priv:1.35"), (r, st("privapp")))
    check("M2 log explains that a registry login is needed", "needs a login" in txt, txt[-500:])
    sh("echo s3cret | docker login localhost:5001 -u tester --password-stdin")
    r = await update_app_stream("privapp", log, "manual", "1.36")
    check("M2 with credentials the update works", r.get("ok") and st("privapp") == ("running", "localhost:5001/priv:1.36"), (r, st("privapp")))
    sh("docker logout localhost:5001")

    # ---------- #3 app khởi động chậm (40s mới healthy) ----------
    sh(f"docker rm -f slowapp; docker run -d --name slowapp --health-cmd 'test -f /tmp/ready' --health-interval 3s --health-start-period 90s {M}/busybox:1.35 sh -c 'sleep 40; touch /tmp/ready; sleep 3600'")
    time.sleep(45)
    r = await update_app_stream("slowapp", log, "manual", "1.36")
    check("M3 slow-starting app (healthy after 40s > 15s check) is NOT rolled back", r.get("ok") and st("slowapp")[1].endswith("1.36"), r)

    # ---------- #4 Postgres có dữ liệu ----------
    sh(f"docker rm -f pg; docker volume rm pgdata; docker run -d --name pg --restart unless-stopped -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data {M}/postgres:16.4-alpine")
    for _ in range(60):
        if sh("docker exec pg pg_isready -U postgres").returncode == 0: break
        time.sleep(1)
    time.sleep(3)
    sh("docker exec pg psql -U postgres -c \"create table t(id int, v text); insert into t select g, md5(g::text) from generate_series(1,50000) g;\"")
    cnt0 = out("docker exec pg psql -U postgres -tAc 'select count(*), sum(id) from t'")
    r = await update_app_stream("pg", log, "manual", "16.6-alpine")
    for _ in range(60):
        if sh("docker exec pg pg_isready -U postgres").returncode == 0: break
        time.sleep(1)
    cnt1 = out("docker exec pg psql -U postgres -tAc 'select count(*), sum(id) from t'")
    logs_old = out("docker logs pg 2>&1 | grep -c 'database system was not properly shut down'")
    check("M4 Postgres 16.4 -> 16.6: data intact (50000 rows)", r.get("ok") and cnt0 == cnt1 == "50000|1250025000" and st("pg")[1].endswith("16.6-alpine"), (r, cnt0, cnt1))
    check("M4 clean shutdown on update (no crash recovery needed)", logs_old == "0", logs_old)
    b = [x for x in list_backups() if x["app"] == "pg"][0]["file"]
    res = restore_backup("pg", b)
    for _ in range(60):
        if sh("docker exec pg pg_isready -U postgres").returncode == 0: break
        time.sleep(1)
    cnt2 = out("docker exec pg psql -U postgres -tAc 'select count(*), sum(id) from t'")
    check("M4 restore back to 16.4: data intact", res.get("ok") and st("pg")[1].endswith("16.4-alpine") and cnt2 == "50000|1250025000", (res.get("log"), cnt2))

    # ---------- #5 macvlan ----------
    mk = sh("docker network rm mvnet; docker network create -d macvlan --subnet 192.168.250.0/24 --gateway 192.168.250.1 -o parent=eth0 mvnet")
    if mk.returncode != 0:
        print("SKIP M5 macvlan not available here:", mk.stderr.strip()[:200])
    else:
        sh(f"docker rm -f mvapp; docker run -d --name mvapp --network mvnet --ip 192.168.250.77 --mac-address 02:42:c0:a8:fa:4d {M}/busybox:1.35 sleep 3600")
        r = await update_app_stream("mvapp", log, "manual", "1.36")
        ep = c.containers.get("mvapp").attrs["NetworkSettings"]["Networks"].get("mvnet", {})
        check("M5 macvlan: static IP + MAC kept", r.get("ok") and ep.get("IPAddress") == "192.168.250.77" and ep.get("MacAddress") == "02:42:c0:a8:fa:4d", (r, ep.get("IPAddress"), ep.get("MacAddress")))

    # ---------- #6 --link ----------
    sh(f"docker rm -f linktarget linker; docker run -d --name linktarget {M}/nginx:1.26-alpine; docker run -d --name linker --link linktarget:lt {M}/busybox:1.35 sleep 3600")
    time.sleep(2)
    r = await update_app_stream("linker", log, "manual", "1.36")
    ok1 = sh("docker exec linker wget -qO- -T 3 http://lt/").returncode == 0
    check("M6 container with --link updated, link still works", r.get("ok") and ok1, (r, c.containers.get("linker").attrs["HostConfig"].get("Links")))
    r = await update_app_stream("linktarget", log, "manual", "1.27-alpine")
    time.sleep(2)
    ok2 = sh("docker exec linker wget -qO- -T 3 http://lt/").returncode == 0
    check("M6 link TARGET updated: linking container still reaches it", r.get("ok") and ok2, (r, out("docker inspect -f '{{json .HostConfig.Links}} {{.State.Status}}' linker")))

    # ---------- #12 tên dài ----------
    long = "app-" + "x" * 56
    sh(f"docker rm -f {long}; docker run -d --name {long} {M}/busybox:1.35 sleep 3600")
    r = await update_app_stream(long, log, "manual", "1.36")
    check("M12 60-char container name updates (temp name 68 chars)", r.get("ok") and st(long)[1].endswith("1.36"), r)

    # ---------- #13 gỡ kèm AppData ----------
    os.makedirs(f"{A}/delme/config", exist_ok=True); open(f"{A}/delme/config/settings.json", "w").write("{}")
    sh(f"docker rm -f delme; docker run -d --name delme -v {A}/delme/config:/config {M}/busybox:1.35 sleep 3600")
    r_bad = await uninstall_app("delme", remove_appdata=True, confirm_name="wrong")
    r = await uninstall_app("delme", remove_appdata=True, confirm_name="delme")
    check("M13 uninstall needs the exact name, then removes container + AppData only", not r_bad.get("ok") and r.get("ok") and not st("delme")[0] and not os.path.exists(f"{A}/delme") and os.path.exists(f"{A}/cfgapp"), (r_bad, r))

    # ---------- #10 120 container ----------
    sh(f"for i in $(seq 1 120); do docker run -d --name many$i {M}/busybox:1.35 sleep 3600 >/dev/null; done")
    t0 = time.time(); apps = list_all_apps(True)["apps"]; dt = time.time() - t0
    check(f"M10 listing {len(apps)} containers takes {dt:.1f}s (< 8s)", len(apps) >= 120 and dt < 8, dt)
    sh("docker rm -f $(docker ps -aq -f name=^many)")
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
