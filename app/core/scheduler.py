import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.compose_snapshot import snapshot_running_apps
from app.core.database import add_resource_samples, add_update_history, get_all_update_cache, get_public_settings, set_setting
from app.core.registry_checker import check_all_updates
from app.core.updater import collect_self_update_result, update_app_stream

logger = logging.getLogger("appmanager.scheduler")
_BACKGROUND_TASKS: set = set()  # giữ tham chiếu để task nền không bị thu hồi giữa chừng
scheduler = AsyncIOScheduler()


async def _silent_log(_: str) -> None:
    pass


async def run_auto_update_job() -> None:
    """Chạy mỗi 5 phút: app nào tới giờ tự cập nhật hôm nay (giờ chung hoặc giờ / ngày riêng của app) thì
    kiểm tra bản mới rồi cập nhật nếu đúng quy tắc (mức phiên bản, đợi N ngày). Máy tắt lúc tới giờ -> chạy bù
    khi bật lại trong ngày."""
    from app.core import update_policy
    from app.core.database import get_all_app_prefs, save_app_pref
    from app.core.docker_client import get_app_by_name
    from app.core.registry_checker import check_one_app_by_name

    cfg = get_public_settings()
    if not cfg["auto_update_enabled"]:
        return
    now = datetime.now()  # giờ máy chủ (TZ của container)
    today = now.strftime("%Y-%m-%d")
    for name, pref in get_all_app_prefs().items():
        if not pref.get("auto_update"):
            continue
        policy = update_policy.parse(pref.get("policy") or "")
        if not update_policy.due_today(policy, cfg["auto_update_time"], pref.get("last_auto") or "", now):
            continue
        save_app_pref(name, last_auto=today)  # mỗi app tối đa 1 lần / ngày
        try:
            await check_one_app_by_name(name)
            app = await asyncio.to_thread(get_app_by_name, name)
        except Exception:
            logger.exception("Auto-update check failed for %s", name)
            continue
        if not app or not app.get("has_update") or not app.get("can_update") or app.get("is_self"):
            continue
        hold = app.get("auto_hold")
        if hold:
            logger.info("Auto-update of %s held back by its rule: %s", name, hold)
            continue
        logger.info("Auto-updating %s (%s -> %s)", name, app.get("version"), app.get("remote_version"))
        await update_app_stream(name, _silent_log, mode="auto")


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


RESOURCE_SAMPLE_MINUTES = 5


async def run_resource_sampler() -> None:
    """Lưu CPU/RAM của từng container mỗi 5 phút (giữ 7 ngày) để vẽ biểu đồ trong Task Manager."""
    from app.core.system_monitor import collect_task_manager_snapshot

    try:
        snap = await asyncio.to_thread(collect_task_manager_snapshot)
    except Exception as exc:
        logger.debug("Resource sampling skipped: %s", exc)
        return
    ts = int(datetime.now(timezone.utc).timestamp())
    rows = [
        (t["name"], float(t.get("cpu_pct") or 0), int(t.get("mem_bytes") or 0))
        for t in snap.get("tasks", [])
        if t.get("status") == "running"
    ]
    if rows:
        await asyncio.to_thread(add_resource_samples, ts, rows)


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
        # Mỗi 5 phút xem app nào tới giờ (giờ chung hoặc giờ / ngày riêng theo quy tắc của từng app)
        scheduler.add_job(run_auto_update_job, trigger=IntervalTrigger(minutes=5), id="auto_update_job",
                          replace_existing=True, max_instances=1, coalesce=True)


    scheduler.add_job(
        run_resource_sampler,
        trigger=IntervalTrigger(minutes=RESOURCE_SAMPLE_MINUTES),
        id="resource_sampler",
        replace_existing=True,
    )

    # Kết quả tự cập nhật do container phụ ghi lại (bản mới khởi động trước khi kiểm tra sức khoẻ xong)
    scheduler.add_job(
        collect_self_update_result,  # hàm thường -> APScheduler chạy trong thread pool
        trigger=IntervalTrigger(minutes=1),
        id="self_update_result",
        replace_existing=True,
    )

    # Ghi nhớ compose đang chạy tốt của từng app (để quay về đúng bản này nếu lần sửa/cập nhật sau bị hỏng)
    scheduler.add_job(
        snapshot_running_apps,
        trigger=IntervalTrigger(minutes=30),
        id="compose_snapshot",
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3),
        replace_existing=True,
    )

    # Thông báo: app gặp sự cố / ổ đĩa sắp đầy / gửi tin để dành sau giờ im lặng
    from app.core import notify

    scheduler.add_job(notify.check_app_health, trigger=IntervalTrigger(minutes=2), id="notify_health",
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20), replace_existing=True)
    scheduler.add_job(notify.check_disk, trigger=IntervalTrigger(hours=1), id="notify_disk",
                      next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2), replace_existing=True)
    scheduler.add_job(notify.flush_deferred, trigger=IntervalTrigger(minutes=5), id="notify_flush", replace_existing=True)
    # Máy phụ (0.21): báo khi mất kết nối / kết nối lại
    from app.core import servers as _servers

    scheduler.add_job(_servers.watch_once, trigger=IntervalTrigger(minutes=3), id="servers_watch", max_instances=1,
                      coalesce=True, next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45), replace_existing=True)

    # Quét lỗ hổng (0.26): theo lịch trong Cài đặt → Quét lỗ hổng
    from app.core import vulnscan as _vulnscan
    _vulnscan.configure(scheduler)

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
        try:
            prune_trig = CronTrigger(**trig_kwargs)
        except ValueError:
            prune_trig = CronTrigger(hour=4, minute=0)
        scheduler.add_job(run_auto_prune_job, trigger=prune_trig, id="auto_prune_job", replace_existing=True)


def start_scheduler() -> None:
    if not scheduler.running:
        configure_jobs()
        scheduler.start()
        _BACKGROUND_TASKS.add(t := asyncio.create_task(_startup_check_if_stale()))
        t.add_done_callback(_BACKGROUND_TASKS.discard)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
