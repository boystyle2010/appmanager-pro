from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.docker_client import get_docker_client, list_all_apps


def format_bytes(num: float) -> str:
    val = float(max(0, num or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} TB"


def _calc_container_stat(container, meta_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta = meta_map.get(container.name) or {}
    base = {
        "id": container.short_id,
        "name": container.name,
        "title": meta.get("title") or container.name,
        "icon": meta.get("icon") or "",
        "is_self": bool(meta.get("is_self", False)),
        "status": container.status,
        "cpu_pct": 0.0,
        "mem_bytes": 0,
        "mem_limit": 0,
        "mem_pct": 0.0,
        "mem_text": "0 MB",
        "net_rx": 0,
        "net_tx": 0,
        "net_rx_text": "0 B",
        "net_tx_text": "0 B",
        "blk_read": 0,
        "blk_write": 0,
        "pids": 0,
    }

    if container.status != "running":
        return base

    try:
        stats = container.stats(stream=False)

        # 1. CPU % (chuẩn Docker CLI)
        cpu_stats = stats.get("cpu_stats") or {}
        precpu_stats = stats.get("precpu_stats") or {}
        cpu_usage = (cpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
        precpu_usage = (precpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
        system_cpu = cpu_stats.get("system_cpu_usage", 0)
        presystem_cpu = precpu_stats.get("system_cpu_usage", 0)

        cpu_delta = cpu_usage - precpu_usage
        system_delta = system_cpu - presystem_cpu
        online_cpus = (
            cpu_stats.get("online_cpus")
            or len((cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or [])
            or 1
        )
        if system_delta > 0 and cpu_delta > 0:
            base["cpu_pct"] = round((cpu_delta / system_delta) * online_cpus * 100.0, 1)

        # 2. RAM (tính chuẩn cả cgroup v1 & v2, trừ inactive_file / cache giống docker stats)
        mem_stats = stats.get("memory_stats") or {}
        mem_raw = mem_stats.get("usage", 0) or 0
        sub = mem_stats.get("stats") or {}
        cache = sub.get("inactive_file", sub.get("cache", 0)) or 0
        mem_used = max(0, mem_raw - cache)
        mem_limit = mem_stats.get("limit", 0) or 0

        base["mem_bytes"] = mem_used
        base["mem_limit"] = mem_limit
        base["mem_text"] = format_bytes(mem_used)
        if mem_limit > 0:
            base["mem_pct"] = round((mem_used / mem_limit) * 100.0, 1)

        # 3. Network I/O
        nets = stats.get("networks") or {}
        rx = sum((n.get("rx_bytes") or 0) for n in nets.values())
        tx = sum((n.get("tx_bytes") or 0) for n in nets.values())
        base["net_rx"] = rx
        base["net_tx"] = tx
        base["net_rx_text"] = format_bytes(rx)
        base["net_tx_text"] = format_bytes(tx)

        # 4. Block I/O & PIDs
        blk_entries = (stats.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
        for entry in blk_entries:
            op = (entry.get("op") or "").lower()
            if op == "read":
                base["blk_read"] += entry.get("value") or 0
            elif op == "write":
                base["blk_write"] += entry.get("value") or 0

        base["pids"] = (stats.get("pids_stats") or {}).get("current", 0) or 0
    except Exception:
        pass

    return base


def collect_task_manager_snapshot() -> dict[str, Any]:
    client = get_docker_client()
    info = client.info() or {}
    host_cpus = int(info.get("NCPU") or 1)
    host_mem_total = int(info.get("MemTotal") or 0)

    apps_data = list_all_apps(include_cache=False)
    meta_map = {a["name"]: a for a in apps_data["apps"]}

    containers = client.containers.list(all=True)
    running_containers = [c for c in containers if c.status == "running"]
    stopped_containers = [c for c in containers if c.status != "running"]

    rows: list[dict[str, Any]] = []
    if running_containers:
        max_workers = min(10, max(2, len(running_containers)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_calc_container_stat, c, meta_map) for c in running_containers]
            for fut in futures:
                rows.append(fut.result())

    for c in stopped_containers:
        rows.append(_calc_container_stat(c, meta_map))

    total_cpu = round(sum(r["cpu_pct"] for r in rows), 1)
    total_mem = sum(r["mem_bytes"] for r in rows)
    total_mem_pct = round((total_mem / host_mem_total) * 100.0, 1) if host_mem_total > 0 else 0.0

    return {
        "host": {
            "cpus": host_cpus,
            "mem_total": host_mem_total,
            "mem_total_text": format_bytes(host_mem_total),
            "containers_cpu_pct": total_cpu,
            "containers_mem_bytes": total_mem,
            "containers_mem_text": format_bytes(total_mem),
            "containers_mem_pct": total_mem_pct,
            "running": len(running_containers),
            "total": len(containers),
        },
        "tasks": rows,
    }
