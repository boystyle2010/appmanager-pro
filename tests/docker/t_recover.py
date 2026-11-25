import os, subprocess, sys, time, signal
S = os.environ["S"]; R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {d}"), flush=True)
def crash_at(name, image, marker, extra_wait=0.0):
    env = dict(os.environ)
    p = subprocess.Popen([sys.executable, f"{S}/child_update.py", name, image], stdout=subprocess.PIPE, text=True, env=env)
    buf = ""
    while True:
        line = p.stdout.readline()
        if not line: break
        buf += line
        if marker in line:
            time.sleep(extra_wait); os.kill(p.pid, signal.SIGKILL); break
    p.wait(); return buf
def state(n):
    out = sh(f"docker inspect -f '{{{{.State.Status}}}} {{{{.Config.Image}}}}' {n} 2>/dev/null"); return out
def startup_recovery():
    """Khởi động AppManager (lifespan chạy phục hồi) rồi tắt."""
    port = "8799"
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", port], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for _ in range(40):
        time.sleep(1)
        if sh(f"curl -s -o /dev/null -w '%{{http_code}}' localhost:{port}/login") == "200": break
    p.terminate(); err = p.communicate(timeout=20)[1]
    return [l for l in err.splitlines() if "Recovery" in l]

M = "mirror.gcr.io/library"
# R1: chết ngay sau khi đổi tên container cũ (chưa tạo container mới)
b1 = crash_at("web", f"{M}/nginx:1.27-alpine", "Creating web from")
check("R1 crash after rename: web missing, web-amp-old left (danger state reproduced)", not state("web") and "exited" in state("web-amp-old"), (state("web"), state("web-amp-old")))
# R4: thêm cả Docker daemon khởi động lại
sh("pkill dockerd")
for _ in range(30):
    time.sleep(1)
    if not sh("pgrep -x dockerd"): break
subprocess.run(f"setsid nohup dockerd > {S}/dockerd.log 2>&1 < /dev/null &", shell=True)
for _ in range(60):
    time.sleep(1)
    if subprocess.run("docker info", shell=True, capture_output=True).returncode == 0: break
time.sleep(3)
print("docker restarted:", sh("docker ps -a --format '{{.Names}}:{{.Status}}' | tr '\\n' ' '"), flush=True)
logs = startup_recovery()
check("R1/R4 after Docker restart + AppManager start: web restored, running, old image", state("web").startswith("running") and "1.26" in state("web") and not state("web-amp-old"), (state("web"), logs))
check("R1 data still there", sh("docker exec web cat /data/file.txt") == "persisted")
# R2: chết khi container mới đã chạy (đang kiểm tra sức khoẻ)
crash_at("web", f"{M}/nginx:1.27-alpine", "Checking the new container", extra_wait=4)
check("R2 crash during health check: both containers exist", "running" in state("web") and state("web-amp-old"), (state("web"), state("web-amp-old")))
logs = startup_recovery()
check("R2 recovery keeps the running new container (1.27) and removes the old one", state("web").startswith("running") and "1.27" in state("web") and not state("web-amp-old"), (state("web"), logs))
# R3: container mới hỏng (restart liên tục) và tiến trình chết giữa chừng
crash_at("bb-fail", f"{M}/busybox:1.36", "Checking the new container", extra_wait=5)
logs = startup_recovery()
check("R3 broken new container + crash: old one restored and running (1.35)", state("bb-fail").startswith("running") and "1.35" in state("bb-fail") and not state("bb-fail-amp-old"), (state("bb-fail"), logs))
# R5: container vốn đang DỪNG bị cắt ngang -> phục hồi nhưng vẫn để dừng
crash_at("bb-stopped", f"{M}/busybox:1.36", "Creating bb-stopped from")
logs = startup_recovery()
check("R5 stopped container restored and left stopped", state("bb-stopped").startswith("exited") and not state("bb-stopped-amp-old"), (state("bb-stopped"), logs))
# R6: không có gì bị cắt ngang -> khởi động không đụng gì
before = sh("docker ps -aq --no-trunc | sort")
logs = startup_recovery()
check("R6 normal start does nothing", sh("docker ps -aq --no-trunc | sort") == before and not logs, logs)
print(f"\nSUMMARY {sum(R)} / {len(R)}")
