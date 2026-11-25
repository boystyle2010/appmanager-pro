import asyncio, os, sys, subprocess
sys.path.insert(0, ".")
from app.core.database import init_db
init_db()
from app.core import run_manager as rm
from app.core.docker_client import get_docker_client, list_all_apps
M = "mirror.gcr.io/library"
c = get_docker_client()
results = []
def check(name, cond, detail=""):
    results.append(("PASS" if cond else "FAIL", name, detail)); print(("PASS" if cond else "FAIL"), name, detail, flush=True)
def sh(cmd): return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
async def log(t): open(os.environ["LOGF"], "a").write(t)

async def main():
    apps = {a["name"]: a for a in list_all_apps(False)["apps"]}
    check("H10 compose app classified compose", apps.get("demo-demo-1", {}).get("manage") == "compose", apps.get("demo-demo-1", {}).get("manage"))
    check("H5 swarm-labelled -> external, no update", apps["ext-swarm"]["manage"] == "external" and not apps["ext-swarm"]["can_update"])
    check("H1 docker run -> manage=run, can_update, can_edit (đợt 3)", apps["web"]["manage"] == "run" and apps["web"]["can_update"] and apps["web"]["can_edit"])
    check("-amp-old containers hidden from list", "redis-amp-old" not in apps)
    old = c.containers.get("web").attrs
    print("docker run cmd:", rm.docker_run_command(old, c.images.get(old["Image"]).attrs["Config"]))

    # H1 update 1.26 -> 1.27
    r = await rm.recreate_stream("web", f"{M}/nginx:1.27-alpine", log, window=12)
    check("H1 update ok", r.get("ok") and r.get("changed"), r.get("reason"))
    n = c.containers.get("web").attrs
    cfg, host = n["Config"], n["HostConfig"]
    check("H1 image is 1.27", "1.27" in cfg["Image"])
    env = dict(e.split("=", 1) for e in cfg["Env"])
    check("H1 user env kept", env.get("TZ") == "Asia/Ho_Chi_Minh" and env.get("MYVAR") == "keep")
    check("H1 image env follows NEW image (not pinned)", env.get("NGINX_VERSION", "").startswith("1.27"), env.get("NGINX_VERSION"))
    check("H1 ports kept", sorted(host["PortBindings"]) == ["443/tcp", "80/tcp"] and host["PortBindings"]["80/tcp"][0]["HostPort"] == "8181")
    check("H1 restart policy kept", host["RestartPolicy"]["Name"] == "unless-stopped")
    check("H1 hostname kept", cfg["Hostname"] == "myweb")
    check("H1 label kept", cfg["Labels"].get("com.example.owner") == "me")
    check("H1 cap_add + tmpfs kept", any("NET_ADMIN" in x for x in (host.get("CapAdd") or [])) and "/run/tmpx" in (host.get("Tmpfs") or {}))
    check("H1 healthcheck kept", "wget" in " ".join(cfg.get("Healthcheck", {}).get("Test", [])))
    nets = n["NetworkSettings"]["Networks"]
    check("H1 both networks", set(nets) == {"appnet", "backnet"}, list(nets))
    check("H1 static IP kept", nets["appnet"]["IPAddress"] == "172.30.0.50", nets["appnet"]["IPAddress"])
    check("H1 aliases kept", "webalias" in (nets["appnet"].get("Aliases") or []) and "webback" in (nets["backnet"].get("Aliases") or []), (nets["appnet"].get("Aliases"), nets["backnet"].get("Aliases")))
    check("H1 named volume data kept", sh("docker exec web cat /data/file.txt") == "persisted")
    check("H1 anonymous volume data kept", sh("docker exec web cat /cachevol/a.txt") == "anon")
    check("H1 bind mount ro kept", sh("curl -s localhost:8181 || docker exec web wget -qO- http://127.0.0.1/") .strip() == "hello-from-bind")
    check("H1 old container removed", not sh("docker ps -a --filter name=^web-amp-old$ -q"))
    check("H1 snapshot saved", rm.load_snapshot("web") is not None)
    check("H12 sidecar (--network container:web) recreated and reaches NEW web", sh("docker exec bb-sidecar wget -qO- -T 2 http://127.0.0.1/") == "hello-from-bind")

    # H7 same image, no force
    r = await rm.recreate_stream("web", f"{M}/nginx:1.27-alpine", log, window=5)
    check("H7 same image -> nothing changed", r.get("ok") and not r.get("changed"))

    # H2 failing new version -> rollback
    oid = c.containers.get("bb-fail").id
    r = await rm.recreate_stream("bb-fail", f"{M}/busybox:1.36", log, window=10)
    st = c.containers.get("bb-fail").attrs
    check("H2 failure detected + rolled back", (not r.get("ok")) and r.get("rolled_back"), r.get("reason"))
    check("H2 original container back (same id, running, 1.35)", st["Id"] == oid and st["State"]["Running"] and "1.35" in st["Config"]["Image"])
    check("H2 no leftover -amp-old", not sh("docker ps -a --filter name=^bb-fail-amp-old$ -q"))

    # H3 stopped stays stopped
    r = await rm.recreate_stream("bb-stopped", f"{M}/busybox:1.36", log, window=5)
    st = c.containers.get("bb-stopped").attrs
    check("H3 stopped container updated but left stopped", r.get("ok") and not st["State"]["Running"] and "1.36" in st["Config"]["Image"])

    # H4 network none
    r = await rm.recreate_stream("bb-none", f"{M}/busybox:1.36", log, window=6)
    st = c.containers.get("bb-none").attrs
    check("H4 network none kept", r.get("ok") and st["HostConfig"]["NetworkMode"] == "none", r.get("reason"))

    # H5 external refused
    r = await rm.recreate_stream("ext-swarm", f"{M}/busybox:1.36", log, window=5)
    check("H5 external refused, untouched", not r.get("ok") and "1.35" in c.containers.get("ext-swarm").attrs["Config"]["Image"])

    # H6 stale -amp-old removed
    r = await rm.recreate_stream("redis", f"{M}/redis:7.2-alpine", log, window=6, force=True)
    check("H6 stale redis-amp-old cleaned, redis recreated", r.get("ok") and not sh("docker ps -a --filter name=^redis-amp-old$ -q"), r.get("reason"))

    # H9 pull failure
    before = c.containers.get("redis").id
    r = await rm.recreate_stream("redis", f"{M}/redis:0.0.0-does-not-exist", log, window=5)
    check("H9 pull failure: nothing changed", not r.get("ok") and c.containers.get("redis").id == before and c.containers.get("redis").attrs["State"]["Running"], r.get("reason"))

    # H11 image_ref_with_tag
    check("H11 tag swap", rm.image_ref_with_tag("ghcr.io/a/b:1.0", "2.0") == "ghcr.io/a/b:2.0" and rm.image_ref_with_tag("localhost:5000/x", "3") == "localhost:5000/x:3")
    print("\nSUMMARY", sum(1 for r in results if r[0] == "PASS"), "/", len(results))
asyncio.run(main())
