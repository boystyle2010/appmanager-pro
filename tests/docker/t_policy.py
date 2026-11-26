"""0.20 quy tắc tự cập nhật theo từng app: mức phiên bản, đợi N ngày, ngày / giờ riêng, chạy bù, 1 lần / ngày.
Container thật bb-none (busybox:1.35 từ setup.sh, có bản mới 1.38). Gọi đúng hàm lịch run_auto_update_job."""
import asyncio, json, subprocess, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting, save_app_pref, get_app_pref, get_connection, get_update_cache_item
init_db(); set_setting("health_wait_seconds", "8"); set_setting("backup_before_update", "false")
from app.core import update_policy as up, scheduler
from app.core.registry_checker import check_one_app_by_name
from app.core.docker_client import get_app_by_name
R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:500]}"), flush=True)
img = lambda: sh("docker inspect -f '{{.Config.Image}}' bb-none")
now = datetime.now(); today = now.strftime("%Y-%m-%d")
earlier = (now - timedelta(minutes=10)).strftime("%H:%M") if now.hour or now.minute >= 10 else "00:00"
later = (now + timedelta(hours=1)).strftime("%H:%M") if now.hour < 23 else None

def set_policy(**kw):
    pol = up.normalize(kw)
    save_app_pref("bb-none", auto_update=True, policy="" if up.is_default(pol) else json.dumps(pol), last_auto="")
def run(): asyncio.run(scheduler.run_auto_update_job())

asyncio.run(check_one_app_by_name("bb-none"))
a = get_app_by_name("bb-none"); c = get_update_cache_item("bb-none")
check("P0 bb-none (busybox 1.35) has a new version and AppManager records when it first saw it", a["has_update"] and c.get("first_seen"), (a.get("remote_version"), c.get("first_seen")))
fs = c["first_seen"]; asyncio.run(check_one_app_by_name("bb-none"))
check("P0 re-check keeps the same 'first seen' time for the same new version", get_update_cache_item("bb-none")["first_seen"] == fs)

set_setting("auto_update_enabled", "true"); set_setting("auto_update_time", earlier)
# P1 chỉ bản vá: 1.35 -> 1.38 là bản nhỏ -> giữ lại
set_policy(level="patch"); a = get_app_by_name("bb-none")
check("P1 'patch only': list shows why it is held (minor version)", a["auto_hold"] and a["auto_hold"]["code"] == "level" and a["auto_hold"]["change"] == "minor", a["auto_hold"])
run()
check("P1 scheduled run does NOT update, but marks today as done", "1.35" in img() and get_app_pref("bb-none")["last_auto"] == today, (img(), get_app_pref("bb-none")["last_auto"]))
# P2 đợi 3 ngày (vừa thấy) -> giữ; giả lập đã thấy 4 ngày trước -> hết giữ
set_policy(level="minor", min_age_days=3); a = get_app_by_name("bb-none")
check("P2 'wait 3 days' just after discovery -> held, 3 days left", a["auto_hold"] and a["auto_hold"]["code"] == "wait" and a["auto_hold"]["days_left"] == 3, a["auto_hold"])
conn = get_connection(); conn.execute("UPDATE update_cache SET first_seen=? WHERE container_name='bb-none'", ((datetime.now(timezone.utc) - timedelta(days=4)).isoformat(timespec="seconds"),)); conn.commit(); conn.close()
check("P2 seen 4 days ago -> no longer held", get_app_by_name("bb-none")["auto_hold"] is None)
# P3 ngày không được phép -> không chạy
other = [d for d in range(7) if d != now.weekday()]
set_policy(level="minor", min_age_days=3, days=other[:3])
run()
check("P3 today is not an allowed day -> nothing runs, not marked", "1.35" in img() and get_app_pref("bb-none")["last_auto"] == "")
# P4 giờ riêng chưa tới -> không chạy
if later:
    set_policy(level="minor", min_age_days=3, time=later); run()
    check("P4 app's own time not reached yet -> nothing runs", "1.35" in img() and get_app_pref("bb-none")["last_auto"] == "")
# P5 đúng giờ (giờ chung đã qua: chạy bù), mức cho phép, đã đợi đủ -> cập nhật thật
set_policy(level="minor", min_age_days=3); run()
check("P5 rule satisfied -> scheduled run really updates the container (1.35 -> 1.38)", "1.38" in img(), img())
check("P5 marked as done today; a second run the same day does nothing", get_app_pref("bb-none")["last_auto"] == today)
before = sh("docker inspect -f '{{.Id}}' bb-none"); run()
check("P5 second tick the same day leaves the container alone", sh("docker inspect -f '{{.Id}}' bb-none") == before)
# P6 tắt tự cập nhật chung -> không làm gì
save_app_pref("bb-none", last_auto=""); set_setting("auto_update_enabled", "false"); run()
check("P6 global auto-update off -> rules never run", get_app_pref("bb-none")["last_auto"] == "")
# P7 kiểm tra dữ liệu nhập
errs = []
for bad in ({"level": "huge"}, {"min_age_days": 500}, {"days": [9]}, {"time": "25:00"}):
    try: up.normalize(bad); errs.append("ok")
    except ValueError as e: errs.append(str(e)[:30])
check("P7 invalid rules refused (level, days to wait, weekday, time)", "ok" not in errs, errs)
check("P7 default rule is stored as empty (old behaviour)", up.is_default({"level": "all", "min_age_days": 0, "days": [0,1,2,3,4,5,6], "time": ""}))
print(f"\nSUMMARY {sum(R)} / {len(R)}")
