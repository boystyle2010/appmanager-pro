import asyncio, os, subprocess, sys, time
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db(); set_setting("health_wait_seconds", "8"); set_setting("backup_before_update", "false")
from app.core import net
from app.core.updater import update_app_stream
M = "mirror.gcr.io/library"; S = os.environ["S"]; R = []
def sh(x, env=None): return subprocess.run(x, shell=True, capture_output=True, text=True, env=env)
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:500]}"), flush=True)
async def log(t): pass
async def main():
    # registry riêng có mật khẩu (Basic, HTTP trên localhost)
    sh("docker rm -f privreg privapp; mkdir -p %s/auth" % S)
    htp = sh(f"docker run --rm --entrypoint htpasswd {M}/httpd:2 -Bbn tester s3cret").stdout.strip()
    open(f"{S}/auth/htpasswd", "w").write(htp + "\n")
    sh(f"docker run -d --name privreg -p 5001:5000 -v {S}/auth:/auth -e REGISTRY_AUTH=htpasswd -e REGISTRY_AUTH_HTPASSWD_REALM=r -e REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd {M}/registry:2"); time.sleep(3)
    sh("echo s3cret | docker login localhost:5001 -u tester --password-stdin")
    for t in ("1.35", "1.36"):
        sh(f"docker pull -q {M}/busybox:{t}; docker tag {M}/busybox:{t} localhost:5001/priv:{t} && docker push -q localhost:5001/priv:{t}")
    sh("docker rmi localhost:5001/priv:1.36; docker run -d --name privapp localhost:5001/priv:1.35 sleep 3600")
    sh("docker logout localhost:5001")  # máy host KHÔNG còn đăng nhập
    ok, msg = await net.test_login("localhost:5001", "tester", "wrong")
    check("N1 wrong token is rejected before saving", not ok and "Wrong" in msg, msg)
    ok, msg = await net.test_login("localhost:5001", "tester", "s3cret")
    check("N2 correct token passes the test", ok, msg)
    r = await update_app_stream("privapp", log, "manual", "1.36")
    check("N3 without a saved login: update refused, nothing changed", not r.get("ok") and "1.35" in sh("docker inspect -f '{{.Config.Image}}' privapp").stdout)
    net.save_login("localhost:5001", "tester", "s3cret")
    check("N4 saving writes AppManager's own docker config (DOCKER_CONFIG)", os.environ.get("DOCKER_CONFIG") and os.path.exists(os.environ["DOCKER_CONFIG"] + "/config.json"))
    r = await update_app_stream("privapp", log, "manual", "1.36")
    check("N5 with the saved login the private image is pulled and the app updated", r.get("ok") and "1.36" in sh("docker inspect -f '{{.Config.Image}}' privapp").stdout, r)
    check("N6 host docker config was not touched (host still logged out)", "localhost:5001" not in open(os.path.expanduser("~/.docker/config.json")).read() if os.path.exists(os.path.expanduser("~/.docker/config.json")) else True)
    net.delete_login("localhost:5001")
    check("N7 removing the last login removes AppManager's docker config", not os.environ.get("DOCKER_CONFIG"))
    # Docker Hub thật: tài khoản sai bị từ chối
    ok, msg = await net.test_login("docker.io", "amp-test-nonexistent-user", "dckr_pat_invalid")
    check("N8 real Docker Hub rejects a wrong account", not ok, msg)
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
