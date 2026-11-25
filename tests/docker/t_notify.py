import asyncio, hashlib, hmac, json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db(); set_setting("health_wait_seconds", "8"); set_setting("backup_before_update", "false")
import httpx
from app.core import notify, net
from app.core.updater import update_app_stream
S = os.environ["S"]; M = "mirror.gcr.io/library"; R = []
APPTOK, CLITOK = open(f"{S}/gotify.tok").read().split()
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True)
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:600]}"), flush=True)
# --- webhook nhận tin thật
HOOK = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        HOOK.append({"body": json.loads(body), "raw": body, "sig": self.headers.get("X-AppManager-Signature")})
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
threading.Thread(target=HTTPServer(("127.0.0.1", 8093), H).serve_forever, daemon=True).start()
def ntfy_msgs(topic): return [json.loads(l) for l in sh(f"curl -s 'http://localhost:8091/{topic}/json?poll=1'").stdout.splitlines() if l.strip()]
def gotify_msgs(): return json.loads(sh(f"curl -s 'http://localhost:8092/message?token={CLITOK}'").stdout).get("messages", [])
async def log(t): pass
def hook_events(): return [h["body"]["event"] for h in HOOK]
def wait(): notify.wait_idle(30); time.sleep(0.3)

async def main():
    set_setting("notify_channels", "[]"); set_setting("notify_lang", "en")
    topic = "amp-test-" + str(int(time.time()))
    a = notify.upsert_channel({"type": "ntfy", "name": "Phone", "config": {"server": "http://localhost:8091", "topic": topic}})
    g = notify.upsert_channel({"type": "gotify", "name": "Gotify", "config": {"server": "http://localhost:8092", "app_token": APPTOK}})
    w = notify.upsert_channel({"type": "webhook", "name": "Hook", "config": {"url": "http://127.0.0.1:8093/hook", "secret": "s3"}})
    notify.upsert_channel({"type": "webhook", "name": "FailsOnly", "events": ["update_failed"], "config": {"url": "http://127.0.0.1:8093/failsonly"}})
    # N2 tin thử tới máy chủ thật
    r1 = notify.send_test(a); r2 = notify.send_test(g); r3 = notify.send_test(w)  # gọi ngay trong event loop: phải vẫn chạy
    nm = ntfy_msgs(topic); gm = gotify_msgs()
    check("N2 test message reaches real ntfy", r1[0] and any("Test notification" in m.get("title", "") for m in nm), (r1, nm[-1:] if nm else nm))
    check("N2 test message reaches real Gotify", r2[0] and any("Test notification" in m.get("title", "") for m in gm), (r2, gm[:1]))
    sig_ok = HOOK and HOOK[-1]["sig"] == "sha256=" + hmac.new(b"s3", HOOK[-1]["raw"], hashlib.sha256).hexdigest()
    check("N2 webhook receives JSON with a valid HMAC signature", r3[0] and sig_ok, HOOK[-1:] if HOOK else HOOK)
    # N4 bí mật bị ẩn; sửa để trống giữ giá trị cũ
    mg = next(c for c in notify.masked_channels() if c["id"] == g["id"])
    notify.upsert_channel({"id": g["id"], "type": "gotify", "name": "Gotify 2", "config": {"server": "http://localhost:8092", "app_token": ""}})
    kept = next(c for c in notify.channels() if c["id"] == g["id"])["config"]["app_token"] == APPTOK
    check("N4 secrets are never returned; editing with an empty secret keeps it", mg["config"]["app_token"] == "" and mg["config"].get("has_app_token") and kept)
    # N6 cập nhật thật -> update_success; cập nhật hỏng -> update_failed (rolled_back)
    HOOK.clear()
    r = await update_app_stream("bb-none", log, "manual", "1.36"); wait()
    ev = [h for h in HOOK if h["body"]["event"] == "update_success"]
    check("N6 real update -> 'update_success' with app + versions", r.get("ok") and ev and ev[0]["body"]["data"]["app"] == "bb-none" and ev[0]["body"]["data"]["to"], HOOK)
    check("N5 channel limited to 'update_failed' did not get the success message", not any(True for h in HOOK if False) and len([h for h in HOOK if h["body"]["event"] == "update_success"]) == 1)
    HOOK.clear()
    r = await update_app_stream("bb-fail", log, "manual", "1.36"); wait()
    fails = [h for h in HOOK if h["body"]["event"] == "update_failed"]
    check("N6 failed update (rolled back) -> 'update_failed' sent to both webhook channels", not r.get("ok") and len(fails) == 2 and fails[0]["body"]["data"]["status"] == "rolled_back", [h["body"] for h in HOOK])
    check("N6 ntfy shows the rollback message with high priority", any("rolled back" in m.get("title", "") and m.get("priority") == 4 for m in ntfy_msgs(topic)))
    # N7 có bản mới: chỉ báo phiên bản chưa báo
    HOOK.clear()
    apps = [{"name": "x1", "title": "X1", "has_update": 1, "version": "1.0", "remote_version": "1.1", "remote_digest": "d1"},
            {"name": "x2", "title": "X2", "has_update": 1, "version": "2.0", "remote_version": "2.1", "remote_digest": "d2"}]
    notify.on_updates_found(apps); wait(); n1 = hook_events().count("update_available")
    notify.on_updates_found(apps); wait(); n2 = hook_events().count("update_available")
    apps[0]["remote_digest"] = "d1b"; apps[0]["remote_version"] = "1.2"
    notify.on_updates_found(apps); wait(); n3 = hook_events().count("update_available")
    last = [h for h in HOOK if h["body"]["event"] == "update_available"][-1]["body"]
    check("N7 updates found: one grouped message, not repeated, only new versions", (n1, n2, n3) == (1, 1, 2) and len(last["data"]["apps"]) == 1, (n1, n2, n3, last))
    # N8 giờ im lặng
    HOOK.clear()
    now = time.localtime(); start = f"{(now.tm_hour - 1) % 24:02d}:00"; end = f"{(now.tm_hour + 1) % 24:02d}:00"
    notify.save_settings({"quiet_enabled": True, "quiet_start": start, "quiet_end": end})
    notify.on_history("demo", "Demo", "1", "2", "manual", "success", ""); notify.on_history("demo", "Demo", "1", "2", "manual", "failed", "boom"); wait()
    check("N8 quiet hours: success is held back, failure is sent immediately", hook_events() == ["update_failed", "update_failed"], hook_events())
    notify.save_settings({"quiet_enabled": False}); notify.flush_deferred(); wait()
    dig = [h["body"] for h in HOOK if h["body"]["event"] == "digest"]
    check("N8 after quiet hours the held message arrives as one summary", len(dig) == 1 and "Demo" in dig[0]["message"], dig)
    notify.flush_deferred(); wait()
    check("N8 summary is sent only once", len([h for h in HOOK if h["body"]["event"] == "digest"]) == 1)
    # N9 app gặp sự cố: chỉ báo khi chuyển trạng thái
    HOOK.clear(); notify._health.clear(); notify._health_ready = False
    notify.check_app_health()  # mốc ban đầu
    sh(f"docker rm -f crashy; docker run -d --name crashy --restart always {M}/busybox:1.35 sh -c 'sleep 2; exit 3'"); time.sleep(9)
    notify.check_app_health(); wait(); c1 = [h["body"] for h in HOOK if h["body"]["event"] == "app_unhealthy"]
    notify.check_app_health(); wait(); c2 = [h["body"] for h in HOOK if h["body"]["event"] == "app_unhealthy"]
    check("N9 crash-looping app -> one 'app_unhealthy' message, not repeated", len(c1) == 1 and c1[0]["data"]["app"] == "crashy" and len(c2) == 1, (c1, c2))
    sh("docker update --restart no crashy; docker rm -f crashy")
    HOOK.clear(); notify.check_app_health()
    sh("docker stop -t 2 redis"); notify.check_app_health(); wait()
    check("N9 a container stopped by the user is not reported as a problem", not [h for h in HOOK if h["body"]["event"] == "app_unhealthy"], [h["body"] for h in HOOK])
    sh(f"docker rm -f oneshot; docker run -d --name oneshot {M}/busybox:1.35 sh -c 'sleep 4; exit 5'"); time.sleep(1); notify.check_app_health(); time.sleep(6)
    notify.check_app_health(); wait()
    ex = [h["body"] for h in HOOK if h["body"]["event"] == "app_unhealthy"]
    check("N9 a running app that exits with an error code is reported", len(ex) == 1 and "code 5" in ex[0]["message"], ex)
    sh("docker rm -f oneshot")
    # N10 ổ đĩa
    HOOK.clear(); set_setting("notify_disk_sent", "{}")
    import shutil; real = shutil.disk_usage
    shutil.disk_usage = lambda p: real.__call__(p)._replace(used=int(real(p).total * 0.95)) if False else type(real(p))(real(p).total, int(real(p).total * 0.95), int(real(p).total * 0.05))
    notify.check_disk(); notify.check_disk(); wait(); shutil.disk_usage = real
    d = [h["body"] for h in HOOK if h["body"]["event"] == "disk_low"]
    check("N10 disk above threshold -> warned once per day per folder", 1 <= len(d) <= 2 and len(d) == len({x["data"]["path"] for x in d}), d)
    # N12 tiếng Việt
    notify.save_settings({"lang": "vi"}); HOOK.clear()
    notify.on_history("demo", "Demo", "1", "2", "manual", "success", ""); wait()
    check("N12 Vietnamese messages", HOOK and "Đã cập nhật" in HOOK[-1]["body"]["title"], HOOK[-1:] if HOOK else HOOK)
    notify.save_settings({"lang": "en"})
    # N13 kênh hỏng không làm chậm / hỏng việc khác
    bad = notify.upsert_channel({"type": "webhook", "name": "Down", "config": {"url": "http://127.0.0.1:1/none"}})
    t0 = time.time(); notify.on_history("demo", "Demo", "1", "2", "manual", "success", ""); dt = time.time() - t0
    wait(); last = next(c for c in notify.channels() if c["id"] == bad["id"]).get("last", {})
    check("N13 unreachable channel: caller not slowed down (queued), failure recorded on the channel", dt < 0.5 and last.get("ok") is False, (dt, last))
    notify.delete_channel(bad["id"])
    # N14 AppManager tự cập nhật
    HOOK.clear(); notify.on_history("appmanager-pro", "AppManager Pro", "0.14.1", "0.16.0", "manual", "success", ""); wait()
    check("N14 AppManager self-update -> 'self_update'", hook_events() == ["self_update"], hook_events())
    # N3 Telegram + Discord: đúng định dạng API
    seen = []
    async def handler(req):
        seen.append((str(req.url), json.loads(req.content))); return httpx.Response(200, json={"ok": True})
    orig = net.client; net.client = lambda **kw: net.GuardedClient(transport=httpx.MockTransport(handler), **kw)
    tg = {"id": "t", "type": "telegram", "config": {"bot_token": "123:ABC", "chat_id": "42"}}
    dc = {"id": "d", "type": "discord", "config": {"webhook_url": "https://discord.com/api/webhooks/1/x"}}
    ok1 = await notify._send(tg, "T", "B", "update_failed", {}); ok2 = await notify._send(dc, "T", "B", "update_failed", {})
    net.client = orig
    check("N3 Telegram: POST /bot<token>/sendMessage with chat_id + text", ok1[0] and seen[0][0] == "https://api.telegram.org/bot123:ABC/sendMessage" and seen[0][1]["chat_id"] == "42" and "T\nB" == seen[0][1]["text"], seen[:1])
    check("N3 Discord: webhook with a red embed for failures", ok2[0] and seen[1][1]["embeds"][0]["color"] == 0xE11D48, seen[1:])
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
