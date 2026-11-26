"""Kênh thông báo mới (0.18.1): Email qua máy chủ SMTP thật (Mailpit), Apprise API thật -> ntfy thật,
Slack / Teams / Google Chat / Mattermost / Matrix / Signal / Bark / Pushover / Pushbullet đúng định dạng API (giả lập),
kiểm tra dữ liệu nhập, ẩn bí mật, gửi qua hàng đợi thật. Tự dựng & dọn Mailpit (:8025/:1025) và Apprise (:8095)."""
import asyncio, json, os, subprocess, sys, time
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting
init_db(); set_setting("notify_channels", "[]"); set_setting("notify_lang", "vi")
import httpx
from app.core import notify, net
S = os.environ["S"]; R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:600]}"), flush=True)

sh("docker rm -f mailpit apprise")
sh("docker run -d --name mailpit -p 1025:1025 -p 8025:8025 mirror.gcr.io/axllent/mailpit:latest")
sh("docker run -d --name apprise -e IPV4_ONLY=yes -p 8095:8000 --add-host=host.docker.internal:host-gateway mirror.gcr.io/caronc/apprise:latest")
for _ in range(40):
    try:
        if httpx.get("http://localhost:8025/api/v1/messages", timeout=2).status_code == 200 and httpx.get("http://localhost:8095/status", timeout=2).status_code == 200: break
    except Exception: pass
    time.sleep(1)
try:
    # E1 email thật qua SMTP (Mailpit), tiêu đề tiếng Việt
    httpx.delete("http://localhost:8025/api/v1/messages")
    em = notify.upsert_channel({"type": "email", "name": "Mail", "config": {"host": "localhost", "port": "1025", "security": "none",
                                "sender": "AppManager <amp@example.com>", "to": "me@example.com, you@example.com"}})
    ok = notify.send_test(em)
    time.sleep(1)
    msgs = httpx.get("http://localhost:8025/api/v1/messages").json().get("messages") or []
    m = msgs[0] if msgs else {}
    check("E1 email reaches a real SMTP server (Mailpit) with a Vietnamese subject, 2 recipients", ok[0] and "Tin thử" in m.get("Subject", "") and len(m.get("To") or []) == 2, (ok, m.get("Subject"), m.get("To")))
    errs = []
    for cfg in ({"host": "smtp.x", "sender": "nobody", "to": "a@b.c"}, {"host": "smtp.x", "sender": "a@b.c", "to": "a@b.c", "security": "tls13"},
                {"host": "smtp.x", "sender": "a@b.c", "to": "a@b.c", "port": "99999"}):
        try: notify.upsert_channel({"type": "email", "config": cfg}); errs.append("saved")
        except ValueError as e: errs.append(str(e))
    check("E2 invalid e-mail address / security / port refused", "saved" not in errs, errs)
    ch = notify.upsert_channel({"type": "email", "name": "Bad SMTP", "config": {"host": "localhost", "port": "1", "security": "none", "sender": "a@b.c", "to": "a@b.c"}})
    t0 = time.time(); r = notify.send_test(ch)
    check("E3 unreachable SMTP server -> clear error, quick", not r[0] and r[1].startswith("SMTP") and time.time() - t0 < 30, r)

    # A1 Apprise API thật -> ntfy thật (chuỗi 2 máy chủ thật)
    topic = "amp-apprise-" + str(int(time.time()))
    ap = notify.upsert_channel({"type": "apprise", "name": "Apprise", "config": {"server": "http://localhost:8095", "urls": f"ntfy://host.docker.internal:8091/{topic}"}})
    r = notify.send_test(ap); time.sleep(2)
    got = [json.loads(l) for l in httpx.get(f"http://localhost:8091/{topic}/json?poll=1").text.splitlines() if l.strip()]
    check("A1 Apprise API (real) forwards to a real ntfy server", r[0] and any("Tin thử" in (x.get("title") or "") for x in got), (r, got[-1:] if got else got))
    try: notify.upsert_channel({"type": "apprise", "config": {"server": "http://localhost:8095"}}); a2 = "saved"
    except ValueError as e: a2 = str(e)
    check("A2 Apprise needs URLs or a key", a2 != "saved", a2)
    httpx.post("http://localhost:8095/add/ampkey", data={"urls": f"ntfy://host.docker.internal:8091/{topic}-k"})
    ak = notify.upsert_channel({"type": "apprise", "name": "Apprise key", "config": {"server": "http://localhost:8095", "key": "ampkey"}})
    r = notify.send_test(ak); time.sleep(2)
    got = [json.loads(l) for l in httpx.get(f"http://localhost:8091/{topic}-k/json?poll=1").text.splitlines() if l.strip()]
    check("A3 Apprise with a saved configuration key", r[0] and got, (r, got))

    # M1 các dịch vụ đám mây: đúng URL / phương thức / nội dung (giả lập)
    seen = []
    def handler(req):
        body = req.content.decode()
        try: data = json.loads(body)
        except Exception: data = dict(x.split("=", 1) for x in body.split("&")) if "=" in body else body
        seen.append((req.method, str(req.url), dict(req.headers), data))
        return httpx.Response(202 if "logic.azure" in str(req.url) else 200, json={"ok": True, "status": 1})
    orig = net.client; net.client = lambda **kw: net.GuardedClient(transport=httpx.MockTransport(handler), **kw)
    cases = {
        "slack": {"webhook_url": "https://hooks.slack.com/services/T/B/X"},
        "teams": {"webhook_url": "https://prod-1.westus.logic.azure.com/workflows/abc"},
        "googlechat": {"webhook_url": "https://chat.googleapis.com/v1/spaces/AAA/messages?key=k"},
        "mattermost": {"webhook_url": "https://mm.example.com/hooks/xyz"},
        "matrix": {"server": "https://matrix.example.org", "access_token": "syt_abc", "room_id": "!room:example.org"},
        "signal": {"server": "http://signal.local:8080", "number": "+84900000001", "recipients": "+84900000002, +84900000003"},
        "bark": {"device_key": "BARKKEY"},
        "pushover": {"app_token": "APPTOK", "user_key": "USERKEY"},
        "pushbullet": {"access_token": "o.PB"},
    }
    res = {}
    for t, cfg in cases.items():
        seen.clear()
        ok = asyncio.run(notify._send({"type": t, "config": cfg}, "❌ Cập nhật thất bại", "nginx 1.26 → 1.27", "update_failed", {}))
        res[t] = (ok, seen[0] if seen else None)
    net.client = orig
    g = lambda t: res[t][1] or ("", "", {}, {})
    check("M1 Slack: POST webhook, text with *bold* title", res["slack"][0][0] and g("slack")[1].startswith("https://hooks.slack.com/") and g("slack")[3]["text"].startswith("*❌"), res["slack"])
    tm = g("teams")[3]
    check("M1 Teams (Workflows): Adaptive Card 1.4, red title for failures, 202 accepted",
          res["teams"][0][0] and tm["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive" and tm["attachments"][0]["content"]["body"][0]["color"] == "Attention", tm)
    check("M1 Google Chat: POST {text}", res["googlechat"][0][0] and g("googlechat")[3]["text"].startswith("*❌"), res["googlechat"])
    check("M1 Mattermost: POST {text, username}", res["mattermost"][0][0] and g("mattermost")[3]["username"] == "AppManager Pro" and g("mattermost")[3]["text"].startswith("**❌"), res["mattermost"])
    mx = g("matrix")
    check("M1 Matrix: PUT /rooms/<encoded id>/send/m.room.message/<txn> with Bearer + HTML",
          mx[0] == "PUT" and "/_matrix/client/v3/rooms/%21room%3Aexample.org/send/m.room.message/amp" in mx[1] and mx[2]["authorization"] == "Bearer syt_abc" and "<b>" in mx[3]["formatted_body"], mx)
    sg = g("signal")
    check("M1 Signal (signal-cli-rest-api): POST /v2/send, 2 recipients", sg[1] == "http://signal.local:8080/v2/send" and sg[3]["recipients"] == ["+84900000002", "+84900000003"], sg)
    bk = g("bark")
    check("M1 Bark: POST api.day.app/push, timeSensitive for failures", bk[1] == "https://api.day.app/push" and bk[3]["device_key"] == "BARKKEY" and bk[3]["level"] == "timeSensitive", bk)
    po = g("pushover")
    check("M1 Pushover: form POST with token, user, priority 1 for failures", po[1] == "https://api.pushover.net/1/messages.json" and po[3].get("token") == "APPTOK" and po[3].get("priority") == "1", po)
    pb = g("pushbullet")
    check("M1 Pushbullet: Access-Token header, note push", pb[2].get("access-token") == "o.PB" and pb[3]["type"] == "note", pb)

    # S1 bí mật không trả về trình duyệt; sửa để trống giữ nguyên
    p = notify.upsert_channel({"type": "pushover", "name": "PO", "config": {"app_token": "APPTOK", "user_key": "USERKEY"}})
    mc = next(c for c in notify.masked_channels() if c["id"] == p["id"])["config"]
    notify.upsert_channel({"id": p["id"], "type": "pushover", "name": "PO2", "config": {"app_token": "", "user_key": ""}})
    kept = next(c for c in notify.channels() if c["id"] == p["id"])["config"]
    check("S1 Pushover keys masked; empty on edit keeps them", mc["app_token"] == "" and mc["has_user_key"] and kept["app_token"] == "APPTOK" and kept["user_key"] == "USERKEY", (mc, kept))
    check("S2 all 16 channel types known", len(notify.CHANNEL_TYPES) == 16 and set(notify.REQUIRED) == set(notify.CHANNEL_TYPES) == set(notify.SECRET_FIELDS))

    # Q1 sự kiện thật qua hàng đợi: email nhận "cập nhật thất bại", kênh chỉ chọn sự kiện khác thì không
    httpx.delete("http://localhost:8025/api/v1/messages")
    notify.upsert_channel({"type": "email", "name": "Only security", "events": ["security"], "config": {"host": "localhost", "port": "1025", "security": "none", "sender": "a@example.com", "to": "sec@example.com"}})
    notify.notify("update_failed", "❌ Cập nhật thất bại", "web: 1.26 → 1.27 (đã quay lại)")
    notify.wait_idle(30); time.sleep(1)
    to = [x["Address"] for m in httpx.get("http://localhost:8025/api/v1/messages").json()["messages"] for x in m["To"]]
    check("Q1 queued real event -> e-mail delivered only to channels that chose it", "me@example.com" in to and "sec@example.com" not in to, to)
finally:
    sh("docker rm -f mailpit apprise")
print(f"\nSUMMARY {sum(R)} / {len(R)}")
