import asyncio, json, sys, time
sys.path.insert(0, ".")
from app.core.database import init_db, set_setting, get_update_cache_item, save_update_cache
init_db()
import httpx
from app.core import net
R = []
def check(n, c, d=""):
    R.append(bool(c)); print(("PASS" if c else "FAIL"), n, ("" if c else f":: {str(d)[:500]}"), flush=True)
calls = []
mode = {"gh": "ok", "hub": "ok", "reg": "ok", "inflight": 0, "max_inflight": 0}
async def handler(req: httpx.Request):
    calls.append((req.method, str(req.url), dict(req.headers)))
    h = req.url.host; p = req.url.path
    if h == "api.github.com":
        mode["inflight"] += 1; mode["max_inflight"] = max(mode["max_inflight"], mode["inflight"])
        await asyncio.sleep(0.05); mode["inflight"] -= 1
        if mode["gh"] == "limited":
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-limit": "60", "x-ratelimit-reset": str(int(time.time()) + 600)}, json={"message": "API rate limit exceeded"})
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"', "x-ratelimit-remaining": "55", "x-ratelimit-limit": "60"})
        return httpx.Response(200, headers={"etag": '"v1"', "x-ratelimit-remaining": "56", "x-ratelimit-limit": "60"}, json={"tag_name": "v1.2.3", "body": "notes"})
    if h == "registry-1.docker.io":
        if mode["reg"] == "limited":
            return httpx.Response(429, headers={"retry-after": "120"}, json={"errors": [{"code": "TOOMANYREQUESTS"}]})
        if p.endswith("/tags/list"):
            return httpx.Response(200, json={"tags": ["1.0", "1.1"]})
        if "/blobs/" in p:
            return httpx.Response(200, json={"config": {"Labels": {"a": "b"}}})
        if "/manifests/" in p:
            return httpx.Response(200, headers={"docker-content-digest": "sha256:" + "1" * 64}, json={"schemaVersion": 2})
    if h == "auth.docker.io":
        return httpx.Response(200, json={"token": "tok-" + ("auth" if "authorization" in req.headers else "anon")})
    if h == "hub.docker.com":
        if p == "/v2/users/login":
            return httpx.Response(200, json={"token": "JWT123"})
        return httpx.Response(200, json={"results": []})
    return httpx.Response(404)
orig_client = net.client
net.client = lambda **kw: net.GuardedClient(transport=httpx.MockTransport(handler), **kw)
def reset():
    calls.clear(); net._state.clear(); set_setting("net_blocks", "{}"); net.clear_cache()

async def main():
    # L5/L12 ETag + remaining
    reset()
    async with net.client() as c:
        await c.get("https://api.github.com/repos/a/b/releases/latest")
        conn = __import__("app.core.database", fromlist=["x"]).get_connection(); conn.execute("UPDATE http_cache SET expires = 0"); conn.commit(); conn.close()
        r2 = await c.get("https://api.github.com/repos/a/b/releases/latest")
    st = {x["source"]: x for x in net.status()}
    check("L5 GitHub ETag: second call revalidated with If-None-Match -> 304 served from cache", r2.status_code == 200 and r2.json()["tag_name"] == "v1.2.3" and calls[-1][2].get("if-none-match") == '"v1"', calls[-1])
    check("L12 remaining / limit read from headers", st["github"]["remaining"] == 55 and st["github"]["limit"] == 60, st["github"])
    # L6/L7/L8 cache policy
    reset()
    async with net.client() as c:
        for _ in range(2):
            await c.get("https://registry-1.docker.io/v2/library/x/blobs/sha256:" + "a" * 64)
            await c.get("https://registry-1.docker.io/v2/library/x/tags/list")
            await c.get("https://registry-1.docker.io/v2/library/x/manifests/latest")
    n = lambda frag: sum(1 for m, u, _ in calls if frag in u)
    check("L6 blob (by digest) fetched once, then from cache", n("/blobs/") == 1)
    check("L7 tags/list fetched once within an hour", n("/tags/list") == 1)
    check("L8 manifests are never cached (update detection stays live)", n("/manifests/") == 2)
    # L1 GitHub limited -> blocked, next call does not hit network
    reset(); mode["gh"] = "limited"
    async with net.client() as c:
        try:
            await c.get("https://api.github.com/repos/a/b/releases/latest"); e1 = None
        except net.RateLimited as e: e1 = e
        before = len(calls)
        try:
            await c.get("https://api.github.com/repos/c/d"); e2 = None
        except net.RateLimited as e: e2 = e
    check("L1 GitHub 403 + remaining 0 -> paused until reset; next call refused without network", e1 and e2 and len(calls) == before and 590 < net.blocked_until("github") - time.time() <= 600, (e1, e2, len(calls), before))
    # L3 persisted across restart
    net._state.clear()
    check("L3 pause survives a restart (stored in settings)", net.blocked_until("github") > time.time())
    # L11 resume
    net.clear_block("github"); mode["gh"] = "ok"
    async with net.client() as c:
        r = await c.get("https://api.github.com/repos/c/d")
    check("L11 'Resume now' clears the pause", r.status_code == 200)
    # L2 Docker Hub 429 Retry-After
    reset(); mode["reg"] = "limited"
    async with net.client() as c:
        try:
            await c.get("https://registry-1.docker.io/v2/library/x/manifests/latest")
        except net.RateLimited: pass
    left = net.blocked_until("dockerhub") - time.time()
    check("L2 Docker Hub 429 + Retry-After 120 -> paused ~2 min (whole Docker Hub source)", 100 < left <= 120, left)
    # L4 check_single_app keeps previous state when limited
    from app.core import registry_checker as rc
    save_update_cache({"container_name": "demo", "image": "nginx:latest", "local_digest": "sha256:" + "0" * 64, "remote_digest": "sha256:" + "9" * 64,
                       "current_version": "1.0", "remote_version": "1.1", "has_update": 1, "source_url": "", "changelog": "c", "release_tag": "v1.1",
                       "release_url": "", "published_at": "", "checked_at": "2026-11-24T00:00:00", "error": "", "target_tag": "", "channels": "[]"})
    app = {"name": "demo", "image": "nginx:latest", "local_digests": ["sha256:" + "0" * 64], "image_id": "sha256:x", "version": "1.0", "icon": "", "source_url": ""}
    async with net.client() as c:
        await rc.check_single_app(app, c)
    cache = get_update_cache_item("demo")
    check("L4 while limited the known 'update available' state is kept, with a clear message", cache["has_update"] == 1 and cache["remote_version"] == "1.1" and "rate limit" in cache["error"], cache)
    # L9 credentials attached
    reset(); mode["reg"] = "ok"
    set_setting("registry_logins", json.dumps([{"registry": "docker.io", "username": "me", "token": "dckr_pat_x"}]))
    async with net.client() as c:
        tok = await c.get("https://auth.docker.io/token", params={"service": "registry.docker.io", "scope": "repository:library/x:pull"})
        await c.get("https://hub.docker.com/v2/repositories/library/x/tags")
    hub_req = [h for m, u, h in calls if "hub.docker.com/v2/repositories" in u][0]
    check("L9 registry token request uses Basic login; Docker Hub API uses the login JWT", tok.json()["token"] == "tok-auth" and hub_req.get("authorization") == "Bearer JWT123", (tok.json(), hub_req.get("authorization")))
    set_setting("registry_logins", "[]")
    # L10 concurrency per source
    reset(); mode["max_inflight"] = 0
    async with net.client() as c:
        await asyncio.gather(*(c.get(f"https://api.github.com/repos/x/y{i}") for i in range(12)))
    check("L10 at most 4 GitHub requests in flight", mode["max_inflight"] <= 4, mode["max_inflight"])
    net.client = orig_client
    print(f"\nSUMMARY {sum(R)} / {len(R)}")
asyncio.run(main())
