"""Kênh phát hành (beta / dev): dữ liệu thật của Docker Hub (nicolargo/glances) + giữ kênh đã biết khi registry lỗi
tạm thời (vd giới hạn lượt gọi ngay sau khi cập nhật) thay vì xoá mất. Container thật bb-latest (busybox:latest)."""
import asyncio, json, subprocess, sys
sys.path.insert(0, ".")
from app.core.database import init_db, get_update_cache_item
init_db()
import httpx
from app.core import net, registry_checker as rc
from app.core.docker_client import list_all_apps
R = []
def sh(x): return subprocess.run(x, shell=True, capture_output=True, text=True).stdout.strip()
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:500]}"), flush=True)

async def detect(tag, client=None):
    async with (client or net.client()) as c:
        return await rc._detect_channels(c, "registry-1.docker.io", "nicolargo/glances", tag, {}, "")

# C1 dữ liệu thật: glances:latest có kênh dev (đẩy sau bản ổn định); latest-full không có dev-full
ch = asyncio.run(detect("latest"))
check("C1 real Docker Hub: glances:latest offers the dev channel", any(c["tag"] == "dev" and c["kind"] == "pre" for c in ch), ch)
ch2 = asyncio.run(detect("latest-full"))
check("C1 real Docker Hub: glances:latest-full has no dev-full -> no channel to switch to", ch2 == [], ch2)

# C2 registry lỗi (503 / 429) -> báo lỗi, không trả "không có kênh" (xoá bộ đệm để thật sự hỏi lại)
net.clear_cache()
for code in (503, 429):
    t = httpx.MockTransport(lambda r, code=code: httpx.Response(code, json={}))
    try:
        r = asyncio.run(detect("latest", net.GuardedClient(transport=t)))
        check(f"C2 HTTP {code} from Docker Hub raises instead of returning []", False, r)
    except (rc.ChannelLookupFailed, net.RateLimited):
        check(f"C2 HTTP {code} from Docker Hub raises instead of returning []", True)
    net.clear_block("dockerhub")

# C3 kiểm tra thật cả app: kênh đã biết được giữ khi lần kiểm tra sau bị lỗi
sh("docker rm -f bb-latest; docker run -d --name bb-latest mirror.gcr.io/library/busybox:latest sleep 3600")
app = next(a for a in list_all_apps(False)["apps"] if a["name"] == "bb-latest")
fake = [{"tag": "latest", "channel": "latest", "kind": "stable", "version": "", "updated": "", "current": True},
        {"tag": "edge", "channel": "edge", "kind": "pre", "version": "", "updated": "", "current": False}]
orig = rc._detect_channels
async def ok(*a, **k): return [dict(c) for c in fake]
async def boom(*a, **k): raise rc.ChannelLookupFailed("busybox")
async def run_check():
    async with net.client() as c:
        return await rc.check_single_app(app, c)
rc._detect_channels = ok; asyncio.run(run_check())
c1 = json.loads(get_update_cache_item("bb-latest")["channels"])
check("C3 first check stores the channels (latest + edge)", [c["tag"] for c in c1] == ["latest", "edge"], c1)
rc._detect_channels = boom; asyncio.run(run_check())
c2 = json.loads(get_update_cache_item("bb-latest")["channels"])
check("C3 next check fails (rate limit after an update) -> channels kept, beta still shown", [c["tag"] for c in c2] == ["latest", "edge"] and c2[0]["current"], c2)
a2 = next(a for a in list_all_apps(True)["apps"] if a["name"] == "bb-latest")
check("C3 app list still returns the channels for the card / update window", len(a2.get("channels") or []) == 2, a2.get("channels"))
async def empty(*a, **k): return []
rc._detect_channels = empty; asyncio.run(run_check())
check("C3 a successful check that finds no channel still clears them (beta really gone)", json.loads(get_update_cache_item("bb-latest")["channels"]) == [])
rc._detect_channels = orig
sh("docker rm -f bb-latest")
print(f"\nSUMMARY {sum(R)} / {len(R)}")
