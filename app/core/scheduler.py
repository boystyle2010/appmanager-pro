import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import get_all_update_cache, get_public_settings
from app.core.docker_client import list_all_apps
from app.core.registry_checker import check_all_updates
from app.core.updater import update_app_stream

logger = logging.getLogger("appmanager.scheduler")
scheduler = AsyncIOScheduler()


async def _silent_log(_: str) -> None:
    pass


async def run_auto_update_job() -> None:
    cfg = get_public_settings()
    if not cfg["auto_update_enabled"]:
        return

    logger.info("Running scheduled auto-update check...")
    await check_all_updates()

    data = await asyncio.to_thread(list_all_apps, True)
    targets = [
        a
        for a in data["apps"]
        if a["auto_update"] and a["has_update"] and a["can_update"] and not a["is_self"]
    ]

    for app in targets:
        logger.info("Auto-updating %s (%s -> %s)", app["name"], app["version"], app["remote_version"])
        await update_app_stream(app["name"], _silent_log, mode="auto")


async def _startup_check_if_stale() -> None:
    await asyncio.sleep(4)
    # Luôn làm mới lại cache của chính AppManager Pro ngay khi vừa restart/self-update
    from app.core.registry_checker import check_one_app_by_name
    try:
        await check_one_app_by_name("appmanager-pro")
    except Exception:
        pass

    cache = get_all_update_cache()
    if not cache:
        await check_all_updates()
        return

    latest_str = max((v.get("checked_at") or "" for v in cache.values()), default="")
    if not latest_str:
        await check_all_updates()
        return

    try:
        latest_dt = datetime.fromisoformat(latest_str)
        if datetime.now(timezone.utc) - latest_dt > timedelta(hours=1):
            await check_all_updates()
    except Exception:
        await check_all_updates()


def configure_jobs() -> None:
    cfg = get_public_settings()
    interval_h = max(1, min(168, int(cfg["check_interval_hours"])))

    scheduler.add_job(
        check_all_updates,
        trigger=IntervalTrigger(hours=interval_h),
        id="periodic_check",
        replace_existing=True,
    )

    if scheduler.get_job("auto_update_job"):
        scheduler.remove_job("auto_update_job")

    if cfg["auto_update_enabled"]:
        try:
            hour, minute = [int(x) for x in cfg["auto_update_time"].split(":", 1)]
        except Exception:
            hour, minute = 3, 30
        scheduler.add_job(
            run_auto_update_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="auto_update_job",
            replace_existing=True,
        )


def start_scheduler() -> None:
    if not scheduler.running:
        configure_jobs()
        scheduler.start()
        asyncio.create_task(_startup_check_if_stale())


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
