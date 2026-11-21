import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import add_update_history, get_all_update_cache, get_public_settings, set_setting
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


async def run_auto_prune_job() -> None:
    """Dọn SSD theo lịch. Chỉ dọn image & build cache; KHÔNG bao giờ tự xoá container hay volume."""
    cfg = get_public_settings()
    if not cfg["auto_prune_enabled"]:
        return
    mode = cfg["auto_prune_images"]
    do_images = mode in ("dangling", "all")
    do_cache = bool(cfg["auto_prune_cache"])
    if not do_images and not do_cache:
        return

    from app.core.system_prune import prune_docker_resources

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        res = await asyncio.to_thread(
            prune_docker_resources,
            prune_images=do_images,
            all_unused_images=(mode == "all"),
            prune_build_cache=do_cache,
            prune_containers=False,
            prune_volumes=False,
        )
        msg = f"Freed {res['freed_display']}"
        add_update_history("system", "Auto SSD cleanup", "", "", "auto", "success", msg)
        set_setting("auto_prune_last", f"{now} • {msg}")
        logger.info("Auto prune: %s", msg)
    except Exception as exc:
        add_update_history("system", "Auto SSD cleanup", "", "", "auto", "failed", str(exc)[:200])
        set_setting("auto_prune_last", f"{now} • Failed: {str(exc)[:80]}")
        logger.warning("Auto prune failed: %s", exc)


def get_auto_prune_next_run() -> str:
    job = scheduler.get_job("auto_prune_job")
    if not job or not job.next_run_time:
        return ""
    return job.next_run_time.strftime("%Y-%m-%d %H:%M")


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


    if scheduler.get_job("auto_prune_job"):
        scheduler.remove_job("auto_prune_job")

    if cfg["auto_prune_enabled"] and (cfg["auto_prune_images"] != "off" or cfg["auto_prune_cache"]):
        try:
            ph, pm = [int(x) for x in cfg["auto_prune_time"].split(":", 1)]
        except Exception:
            ph, pm = 4, 0
        trig_kwargs: dict = {"hour": ph, "minute": pm}
        if cfg["auto_prune_freq"] == "weekly":
            trig_kwargs["day_of_week"] = max(0, min(6, int(cfg["auto_prune_weekday"])))
        elif cfg["auto_prune_freq"] == "monthly":
            trig_kwargs["day"] = 1
        scheduler.add_job(
            run_auto_prune_job,
            trigger=CronTrigger(**trig_kwargs),
            id="auto_prune_job",
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
