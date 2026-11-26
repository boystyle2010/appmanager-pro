"""0.21: log (khoảng thời gian, tìm, lọc mức, tải về, Token), log / sao lưu / khôi phục app trên máy phụ qua máy chính,
báo máy phụ mất kết nối / kết nối lại, sự kiện mới tự bật cho kênh đã có. Máy chính uvicorn :8783, máy phụ :8782
(chạy từ repo, cùng Docker trong sandbox; setup.sh: bb-none busybox:1.35 chạy bằng docker run). Container log thật: lg."""
import asyncio, atexit, json, os, subprocess, sys, tempfile, time
import httpx
S = os.environ["S"]; R = []
MAIN, REM = "http://localhost:8783", "http://127.0.0.1:8782"
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, cond, d=""):
    R.append(bool(cond)); print(("PASS" if cond else "FAIL"), n, ("" if cond else f":: {str(d)[:600]}"), flush=True)
procs = []
atexit.register(lambda: [p.terminate() for p in procs])
def start(port, data):
    sh(f"rm -rf {data} && mkdir -p {data}")
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                                  env={**os.environ, "APP_DATA_DIR": data}, stdout=open(f"{data}.log", "w"), stderr=subprocess.STDOUT))
def wait(url):
    for _ in range(60):
        try:
            if httpx.get(url + "/login", timeout=2).status_code < 500: return True
        except Exception: time.sleep(0.5)
    return False
def admin(base):
    h = {"Origin": base}
    httpx.post(base + "/api/auth/setup", headers=h, json={"username": "admin", "password": "Test-Passw0rd!x", "confirm_password": "Test-Passw0rd!x"})
    c = httpx.Client(base_url=base, headers=h, timeout=300)
    assert c.post("/api/auth/login", json={"username": "admin", "password": "Test-Passw0rd!x"}).status_code == 200
    return c

LOG_CMD = ('echo "INFO started"; echo "WARNING disk almost full"; echo "ERROR cannot connect db"; '
           'echo "Traceback (most recent call last):"; echo "  File x.py line 3"; echo "plain line about cats"; '
           'echo "another line about dogs"; sleep 3600')
sh('pkill -f "port 878[23]"; sleep 1')  # tiến trình sót lại từ lần chạy hỏng trước
sh("docker rm -f lg; docker run -d --name lg mirror.gcr.io/library/busybox:latest sh -c '" + LOG_CMD + "'")
try:
    start(8783, f"{S}/v21_main"); start(8782, f"{S}/v21_rem")
    check("2 AppManager instances up (main + remote)", wait(MAIN) and wait(REM))
    main, rem = admin(MAIN), admin(REM)
    time.sleep(1)

    # ---------------- L: log trên máy này
    r = main.get("/api/apps/lg/logs").json()
    check("L1 last hour: all 7 lines, timestamps kept", r["matched"] == 7 and r["text"].count("\n") == 7 and r["text"][:4].isdigit(), r)
    r = main.get("/api/apps/lg/logs", params={"level": "error"}).json()
    check("L2 errors only: the ERROR line + the stack trace that follows it (with its indented line)",
          r["matched"] == 3 and "cannot connect db" in r["text"] and "File x.py" in r["text"] and "WARNING" not in r["text"], r)
    r = main.get("/api/apps/lg/logs", params={"level": "warn"}).json()
    check("L2 warnings = warnings + errors (4 lines)", r["matched"] == 4 and "WARNING disk" in r["text"], r)
    r = main.get("/api/apps/lg/logs", params={"q": "LINE -dogs"}).json()
    check("L3 search: case-insensitive, several words, -word excludes",
          "about cats" in r["text"] and "dogs" not in r["text"] and "File x.py line 3" in r["text"], r)
    r = main.get("/api/apps/lg/logs", params={"range": "15m", "q": "nothing-like-this"}).json()
    check("L3 no match -> empty text, counts kept", r["matched"] == 0 and r["text"] == "" and r["scanned"] == 7, r)
    bad = [main.get("/api/apps/lg/logs", params={"range": "2y"}).status_code, main.get("/api/apps/lg/logs", params={"level": "x"}).status_code,
           main.get("/api/apps/no-such-app/logs").status_code, main.get("/api/apps/..%2Fetc/logs").status_code]
    check("L4 invalid range / level -> 400, unknown app -> 404, odd name rejected", bad[:3] == [400, 400, 404] and bad[3] in (400, 404), bad)
    d = main.get("/api/apps/lg/logs/download", params={"range": "all", "q": "about"})
    cd = d.headers.get("content-disposition", "")
    check("L5 download: .txt attachment named after the app, header line + matching lines only",
          d.status_code == 200 and 'attachment; filename="lg-logs-all-' in cd and cd.endswith('.txt"')
          and d.text.startswith("# AppManager Pro — logs of lg") and "about cats" in d.text and "about dogs" in d.text and "ERROR" not in d.text, (cd, d.text[:300]))
    au = main.get("/api/audit").json()
    au = au.get("items", au) if isinstance(au, dict) else au
    check("L5 download is written to the activity log", any(a.get("action") == "logs_download" and a.get("target") == "lg" for a in au), au[:3])

    # Token (máy phụ): đọc log được bằng quyền Chỉ đọc; khôi phục cần quyền Cập nhật
    TOK = rem.post("/api/tokens", json={"name": "Main", "scope": "update", "ips": "127.0.0.1"}).json()["token"]
    RO = rem.post("/api/tokens", json={"name": "Viewer", "scope": "read"}).json()["token"]
    hro = {"Authorization": f"Bearer {RO}"}
    a = httpx.get(REM + "/api/apps/lg/logs?level=error", headers=hro).json()
    b = httpx.get(REM + "/api/apps/lg/logs/download?range=1h", headers=hro)
    check("L6 read-only Token can read and download logs", a.get("matched") == 3 and b.status_code == 200 and "cannot connect db" in b.text, (a, b.status_code))
    rr = httpx.post(REM + "/api/backups/restore", headers={**hro, "Origin": REM}, json={"app": "bb-none", "file": "x.tar.gz"})
    check("L6 read-only Token cannot restore (403)", rr.status_code == 403, rr.text)

    # ---------------- M: máy chính -> máy phụ
    sv = main.post("/api/servers", json={"name": "Remote", "url": REM, "token": TOK}).json()["server"]
    SID = sv["id"]
    r = main.get(f"/api/servers/{SID}/apps/lg/logs", params={"level": "error"}).json()
    check("M1 remote logs through the main server (filters applied on the remote)", r.get("matched") == 3 and "cannot connect db" in r.get("text", ""), r)
    d = main.get(f"/api/servers/{SID}/apps/lg/logs/download", params={"range": "all", "q": "cats"})
    check("M2 remote log download streams the remote file (name + content)",
          d.status_code == 200 and "lg-logs-all-" in d.headers.get("content-disposition", "") and "about cats" in d.text and "dogs" not in d.text,
          (d.status_code, d.headers.get("content-disposition"), d.text[:200]))
    e = main.get(f"/api/servers/{SID}/apps/no-such-app/logs")
    e2 = main.get(f"/api/servers/{SID}/apps/lg/logs", params={"range": "2y"})
    check("M3 unknown remote app -> 404 with a clear message; bad filter refused before calling the remote",
          e.status_code == 404 and "App not found" in e.text and e2.status_code == 400, (e.status_code, e.text, e2.status_code))
    tok_try = httpx.get(MAIN + f"/api/servers/{SID}/apps/lg/logs", headers={"Authorization": f"Bearer {TOK}"})
    check("M3 remote proxy endpoints are for signed-in users only (no API Token)", tok_try.status_code in (401, 403), tok_try.status_code)

    # sao lưu thật trên máy phụ cho bb-none (docker run) rồi khôi phục từ máy chính
    out = subprocess.run([sys.executable, "-c", (
        "import json; from app.core.database import init_db; init_db();"
        "from app.core.docker_client import get_app_by_name; from app.core.app_backup import create_backup;"
        "from app.core.run_manager import snapshot_for_backup;"
        "a = get_app_by_name('bb-none'); snap = snapshot_for_backup('bb-none');"
        "print(json.dumps(create_backup('bb-none', a.get('appdata_path') or '', a.get('version') or '1.35', 2048, 3,"
        " mounts=[], image_id=a.get('image_id') or '', image_ref=a['image'], run_snapshot=snap)))")],
        env={**os.environ, "APP_DATA_DIR": f"{S}/v21_rem"}, capture_output=True, text=True)
    bres = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    check("M4 a real backup of bb-none exists on the remote", bres.get("ok"), out.stdout[-400:] + out.stderr[-400:])
    lst = main.get(f"/api/servers/{SID}/backups", params={"app_name": "bb-none"}).json()["items"]
    other = main.get(f"/api/servers/{SID}/backups", params={"app_name": "lg"}).json()["items"]
    check("M4 remote backups listed through the main server, filtered by app", len(lst) == 1 and lst[0]["file"] == bres.get("file") and other == [], (lst, other))
    old_id = sh("docker inspect -f '{{.Id}}' bb-none")
    rs = main.post(f"/api/servers/{SID}/backups/restore", json={"app": "bb-none", "file": lst[0]["file"]})
    new_id = sh("docker inspect -f '{{.Id}}' bb-none"); state = sh("docker inspect -f '{{.State.Status}}' bb-none")
    log = " ".join(rs.json().get("log") or []) if rs.status_code == 200 else ""
    check("M5 restore on the remote from the main server: stopped, restored, running again (steps returned)",
          rs.status_code == 200 and rs.json().get("ok") and state == "running" and "Stopping container bb-none" in log
          and "Starting container bb-none" in log, (rs.status_code, rs.text[:400], state))
    au_main = main.get("/api/audit").json(); au_main = au_main.get("items", au_main) if isinstance(au_main, dict) else au_main
    au_rem = rem.get("/api/audit").json(); au_rem = au_rem.get("items", au_rem) if isinstance(au_rem, dict) else au_rem
    check("M5 audit on both servers (main: remote_backup_restore, remote: backup_restore by the Token)",
          any(a.get("action") == "remote_backup_restore" and "bb-none" in a.get("target", "") for a in au_main)
          and any(a.get("action") == "backup_restore" and a.get("target") == "bb-none" for a in au_rem), (au_main[:2], au_rem[:2]))
    main.post("/api/servers", json={"id": SID, "name": "Remote", "url": REM, "token": RO})
    rs2 = main.post(f"/api/servers/{SID}/backups/restore", json={"app": "bb-none", "file": lst[0]["file"]})
    check("M6 restore with a read-only Token -> 403 with a clear message", rs2.status_code == 403 and "Not allowed" in rs2.text, rs2.text)
    main.post("/api/servers", json={"id": SID, "name": "Remote", "url": REM, "token": TOK})
    rs3 = main.post(f"/api/servers/{SID}/backups/restore", json={"app": "bb-none", "file": "../../etc/passwd"})
    check("M6 path tricks in the backup file name are refused by the remote", rs3.status_code == 400, rs3.text)
finally:
    for p in procs: p.terminate()
    sh("docker rm -f lg")

# ---------------- W: theo dõi máy phụ (chạy trong tiến trình test, máy phụ thật :8782 đã tắt ở trên -> bật lại)
tmp = tempfile.mkdtemp()
os.environ["APP_DATA_DIR"] = tmp
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting, get_setting
init_db()
from app.core import notify, servers
start(8782, f"{S}/v21_rem2"); wait(REM); rem2 = admin(REM)
TOK2 = rem2.post("/api/tokens", json={"name": "Main", "scope": "read"}).json()["token"]
sent = []
notify.notify = lambda ev, title, body="", data=None: sent.append((ev, title, body, data)) or 1
good = servers.upsert({"name": "Good", "url": REM, "token": TOK2})
flaky = servers.upsert({"name": "Flaky", "url": "http://127.0.0.1:8779", "token": TOK2})
r1 = asyncio.run(servers.watch_once())
check("W1 first failure: no alert yet (could be a short network blip)", r1 == [] and not sent, sent)
r2 = asyncio.run(servers.watch_once())
off = [x for x in sent if x[3].get("online") is False]
check("W2 second failure in a row: one 'server unreachable' alert with the reason", r2 == ["offline:Flaky"] and len(off) == 1
      and "Flaky" in off[0][1] and "Cannot connect" in off[0][2] and off[0][0] == "server_offline", sent)
asyncio.run(servers.watch_once())
check("W3 still down: no repeated alert", len(sent) == 1, sent)
check("W3 down state remembered (survives a restart)", flaky["id"] in json.loads(get_setting("servers_down", "{}")))
servers.upsert({"id": flaky["id"], "name": "Flaky", "url": "http://localhost:8782", "token": ""})  # máy "sống lại"
r4 = asyncio.run(servers.watch_once())
on = [x for x in sent if x[3].get("online") is True]
check("W4 back online: one 'reachable again' alert with how long it was down", r4 == ["online:Flaky"] and len(on) == 1 and "min" in on[0][2], sent)
check("W4 down state cleared; the healthy server never alerted", get_setting("servers_down", "{}") == "{}" and not any("Good" in x[1] for x in sent), sent)
for p in procs: p.terminate()

# sự kiện mới tự bật cho kênh đã có (kênh tạo trước 0.21 chỉ có 7 sự kiện cũ)
set_setting("notify_known_events", "")
set_setting("notify_channels", json.dumps([{"id": "a1", "type": "ntfy", "name": "Phone", "enabled": True, "config": {"topic": "x"},
                                            "events": ["update_failed", "disk_low"]}]))
ch = notify.channels()
check("N1 existing channel gets the new 'server unreachable' event once", ch[0]["events"] == ["update_failed", "disk_low", "server_offline"], ch)
ch[0]["events"] = ["update_failed"]; notify._save_channels(ch)
check("N1 turning it off afterwards is kept (not re-added)", notify.channels()[0]["events"] == ["update_failed"])
check("N2 server_offline is critical (sent even in quiet hours) and listed as an event", "server_offline" in notify.CRITICAL and "server_offline" in notify.EVENTS)

print(f"SUMMARY {sum(R)} / {len(R)}")
