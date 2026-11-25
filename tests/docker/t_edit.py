import asyncio, sys, subprocess, io
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting, get_update_history
init_db(); set_setting("health_wait_seconds", "8")
from ruamel.yaml import YAML
from app.core.compose_manager import get_compose_state, save_and_apply_compose, merge_ui_into_yaml
from app.core.docker_client import get_docker_client
from app.core import run_manager as rm
c = get_docker_client(); R = []
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def A(n): return c.containers.get(n).attrs
def y_load(t): return YAML().load(t)
def y_dump(d):
    b = io.StringIO(); y = YAML(); y.indent(mapping=2, sequence=4, offset=2); y.dump(d, b); return b.getvalue()
def svc(d): return next(iter(d["services"].values()))

async def main():
    st = await get_compose_state("web")
    check("E1 run container opens in editor (YAML + visual UI, run_mode)", st.get("run_mode") and "nginx:1.26" in st["raw_yaml"] and st["ui"], st.get("raw_yaml"))
    print(st["raw_yaml"])
    # E2: visual UI round trip: add env + change host port
    ui = st["ui"]; s_ui = ui["service"]
    s_ui["environment"].append({"key": "NEW_VAR", "value": "hello"})
    for p in s_ui["ports"]:
        if p.get("container") == "80": p["host"] = "8282"
    y2 = merge_ui_into_yaml(st["raw_yaml"], ui)
    old_id = A("web")["Id"]
    r = await save_and_apply_compose("web", y2)
    a = A("web")
    check("E2 visual edit applied (new env + port 8282)", r.get("ok") and "NEW_VAR=hello" in a["Config"]["Env"] and a["HostConfig"]["PortBindings"]["80/tcp"][0]["HostPort"] == "8282", (r, a["HostConfig"]["PortBindings"]))
    check("E2 container recreated (new id), still running", a["Id"] != old_id and a["State"]["Running"])
    nets = a["NetworkSettings"]["Networks"]
    check("E2 settings not shown in YAML kept (static IP, aliases, healthcheck)", nets["appnet"]["IPAddress"] == "172.30.0.50" and "webalias" in (nets["appnet"].get("Aliases") or []) and a["Config"].get("Healthcheck"), nets)
    check("E2 data kept (named + anonymous volume)", sh("docker exec web cat /data/file.txt") == "persisted" and sh("docker exec web cat /cachevol/a.txt") == "anon")
    check("E12 sidecar recreated and reaches edited web", sh("docker exec bb-sidecar wget -qO- -T 2 http://127.0.0.1/") == "hello-from-bind")
    # E3: remove env var, change restart, add cap + device + tmpfs
    d = y_load((await get_compose_state("web"))["raw_yaml"]); s = svc(d)
    s["environment"] = [e for e in s["environment"] if not str(e).startswith("MYVAR=")]
    s["restart"] = "always"; s.setdefault("cap_add", []).append("SYS_PTRACE")
    s.setdefault("devices", []).append("/dev/null:/dev/xnull"); s.setdefault("tmpfs", []).append("/run/extra")
    r = await save_and_apply_compose("web", y_dump(d)); a = A("web")
    env = a["Config"]["Env"]
    check("E3 env removed, restart=always, cap/device/tmpfs added", r.get("ok") and not any(e.startswith("MYVAR=") for e in env) and a["HostConfig"]["RestartPolicy"]["Name"] == "always"
          and any("SYS_PTRACE" in x for x in a["HostConfig"]["CapAdd"] or []) and any(dv["PathInContainer"] == "/dev/xnull" for dv in a["HostConfig"]["Devices"] or []) and "/run/extra" in (a["HostConfig"]["Tmpfs"] or {}), (r, a["HostConfig"].get("Tmpfs")))
    check("E3 image default env still from image (NGINX_VERSION present)", any(e.startswith("NGINX_VERSION=") for e in env))
    # E5: change image tag in editor
    d = y_load((await get_compose_state("web"))["raw_yaml"]); svc(d)["image"] = "mirror.gcr.io/library/nginx:1.27-alpine"
    r = await save_and_apply_compose("web", y_dump(d))
    check("E5 image changed through editor", r.get("ok") and "1.27" in A("web")["Config"]["Image"], r)
    # E6: invalid port -> nothing changed
    before = A("web")["Id"]
    d = y_load((await get_compose_state("web"))["raw_yaml"]); svc(d)["ports"] = ["abc:80"]
    r = await save_and_apply_compose("web", y_dump(d))
    check("E6 invalid port rejected, container untouched", not r.get("ok") and A("web")["Id"] == before and "Invalid" in (r.get("error") or ""), r)
    # E8: rename refused
    d = y_load((await get_compose_state("web"))["raw_yaml"]); svc(d)["container_name"] = "web-renamed"
    r = await save_and_apply_compose("web", y_dump(d))
    check("E8 rename refused, untouched", not r.get("ok") and A("web")["Id"] == before, r)
    # E9: relative volume refused
    d = y_load((await get_compose_state("web"))["raw_yaml"]); svc(d)["volumes"].append("./x:/x")
    r = await save_and_apply_compose("web", y_dump(d))
    check("E9 relative volume refused, untouched", not r.get("ok") and A("web")["Id"] == before, r)
    # E7: config that breaks the container -> rollback to previous container
    d = y_load((await get_compose_state("bb-fail"))["raw_yaml"]); svc(d)["command"] = ["sh", "-c", "exit 7"]
    old = A("bb-fail")["Id"]
    r = await save_and_apply_compose("bb-fail", y_dump(d))
    a = A("bb-fail")
    check("E7 broken settings rolled back to the same previous container", not r.get("ok") and a["Id"] == old and a["State"]["Running"] and "previous container is running again" in (r.get("error") or ""), r)
    h = [x for x in get_update_history(30) if x["container_name"] == "bb-fail"]
    check("E7 history records config rollback", h and h[0]["status"] == "rolled_back" and h[0]["mode"] == "config", h[:1])
    # E10: leave backnet, keep appnet with static IP
    d = y_load((await get_compose_state("web"))["raw_yaml"]); svc(d)["networks"] = ["appnet"]
    r = await save_and_apply_compose("web", y_dump(d)); nets = A("web")["NetworkSettings"]["Networks"]
    check("E10 network removed, static IP on remaining network kept", r.get("ok") and list(nets) == ["appnet"] and nets["appnet"]["IPAddress"] == "172.30.0.50", (r, list(nets)))
    # E13: drop the named volume from config -> volume itself still exists with data
    d = y_load((await get_compose_state("web"))["raw_yaml"]); s = svc(d)
    s["volumes"] = [v for v in s["volumes"] if not str(v).startswith("webdata:")]
    r = await save_and_apply_compose("web", y_dump(d))
    check("E13 volume unmounted but named volume + data still exist", r.get("ok") and "webdata" in sh("docker volume ls -q") and not any(m.get("Name") == "webdata" for m in A("web")["Mounts"]), r)
    # E11: network none for a busybox, then back to bridge
    d = y_load((await get_compose_state("bb-none"))["raw_yaml"]); s = svc(d); s["network_mode"] = "bridge"
    r = await save_and_apply_compose("bb-none", y_dump(d))
    check("E11 network_mode none -> bridge", r.get("ok") and A("bb-none")["HostConfig"]["NetworkMode"] == "bridge", r)
    d = y_load((await get_compose_state("bb-none"))["raw_yaml"]); s = svc(d); s.pop("networks", None); s["network_mode"] = "host"
    r = await save_and_apply_compose("bb-none", y_dump(d))
    check("E11 network_mode -> host", r.get("ok") and A("bb-none")["HostConfig"]["NetworkMode"] == "host", r)
    # E15: docker run command reflects edits
    a = A("web"); cmd = rm.docker_run_command(a, c.images.get(a["Image"]).attrs["Config"])
    check("E15 docker run command shows edited values", "8282:80" in cmd and "NEW_VAR=hello" in cmd and "--restart always" in cmd, cmd)
    # E16: dict-style environment + string command + mem/cpus limits
    d = y_load((await get_compose_state("stopped-ok" if False else "redis"))["raw_yaml"]); s = svc(d)
    s["environment"] = {"A": "1", "B": "two words"}; s["command"] = "redis-server --save '' --appendonly no"; s["mem_limit"] = "256m"; s["cpus"] = 0.5
    r = await save_and_apply_compose("redis", y_dump(d)); a = A("redis")
    check("E16 dict env, string command, mem_limit 256m, cpus 0.5", r.get("ok") and "B=two words" in a["Config"]["Env"] and a["Config"]["Cmd"][:2] == ["redis-server", "--save"] and a["HostConfig"]["Memory"] == 256 * 1024 * 1024 and a["HostConfig"]["NanoCpus"] == 500000000, (r, a["Config"]["Cmd"]))
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
