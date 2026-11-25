import asyncio, sys
sys.path.insert(0, ".")
from app.core.database import init_db; init_db()
from app.core.run_manager import recreate_stream
async def log(t): print(t, end="", flush=True)
asyncio.run(recreate_stream(sys.argv[1], sys.argv[2], log, window=40))
