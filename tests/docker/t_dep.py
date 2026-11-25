import asyncio, sys, subprocess
sys.path.insert(0, ".")
from app.core.database import init_db; init_db()
from app.core import run_manager as rm
async def log(t): print(t, end="")
async def main():
    r = await rm.recreate_stream("web", "mirror.gcr.io/library/nginx:1.26-alpine", log, window=10)
    out = subprocess.run("docker exec bb-sidecar wget -qO- -T 2 http://127.0.0.1/", shell=True, capture_output=True, text=True).stdout.strip()
    print("\nRESULT", r.get("ok"), "sidecar sees new web:", out == "hello-from-bind")
asyncio.run(main())
