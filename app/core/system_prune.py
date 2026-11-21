from typing import Any

import docker


# Client riêng cho thao tác dọn dẹp: df/prune trên máy nhiều image có thể chạy > 60 giây (mặc định của docker-py)
def get_docker_client() -> docker.DockerClient:
    return docker.from_env(timeout=600)


def format_bytes(num_bytes: int) -> str:
    size = float(max(0, int(num_bytes or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return "0 B"


def get_docker_disk_usage() -> dict[str, Any]:
    """Đọc thống kê dung lượng Docker thực tế và tính dung lượng rác có thể giải phóng."""
    client = get_docker_client()
    df = client.df() or {}

    images = df.get("Images") or []
    containers = df.get("Containers") or []
    volumes = df.get("Volumes") or []
    build_cache = df.get("BuildCache") or []

    # 1. Images: tách riêng Dangling (<none>) và toàn bộ Unused (không container nào dùng)
    img_total_size = 0
    dangling_count = 0
    dangling_size = 0
    unused_img_count = 0
    unused_img_size = 0

    for img in images:
        sz = max(0, int(img.get("Size") or 0))
        shared = max(0, int(img.get("SharedSize") or 0))
        # SharedSize = -1 nghĩa là Docker chưa tính -> dùng Size; ngược lại chỉ tính phần layer riêng của image
        raw_shared = img.get("SharedSize")
        effective = sz if raw_shared is None or int(raw_shared) < 0 else max(0, sz - shared)

        used_by = int(img.get("Containers") or 0)
        if used_by == 0:
            unused_img_count += 1
            unused_img_size += effective
            tags = img.get("RepoTags") or []
            if not tags or tags == ["<none>:<none>"]:
                dangling_count += 1
                dangling_size += effective

    # 2. Containers đã dừng
    stopped_count = 0
    stopped_size = 0
    for c in containers:
        if (c.get("State") or "").lower() != "running":
            stopped_count += 1
            stopped_size += max(0, int(c.get("SizeRw") or 0))

    # 3. Build Cache không sử dụng
    cache_count = 0
    cache_reclaimable = 0
    for b in build_cache:
        if not b.get("InUse"):
            cache_count += 1
            cache_reclaimable += max(0, int(b.get("Size") or 0))

    # 4. Volumes không có container tham chiếu
    unused_vol_count = 0
    unused_vol_size = 0
    for v in volumes:
        usage = v.get("UsageData") or {}
        ref = int(usage.get("RefCount") if usage.get("RefCount") is not None else -1)
        vsz = max(0, int(usage.get("Size") or 0))
        if ref == 0:
            unused_vol_count += 1
            unused_vol_size += vsz

    # Tổng dung lượng image thật sự trên đĩa (layer chung chỉ tính 1 lần) - giống `docker system df`
    layers_size = int(df.get("LayersSize") or 0)
    img_total_size = layers_size if layers_size > 0 else img_total_size + sum(
        max(0, int(i.get("SharedSize") or 0)) for i in images
    )

    total_reclaimable = unused_img_size + stopped_size + cache_reclaimable + unused_vol_size

    return {
        "total_reclaimable_bytes": total_reclaimable,
        "total_reclaimable": format_bytes(total_reclaimable),
        "images": {
            "total_count": len(images),
            "total_size": format_bytes(img_total_size),
            "dangling_count": dangling_count,
            "dangling_bytes": dangling_size,
            "dangling_size": format_bytes(dangling_size),
            "unused_count": unused_img_count,
            "unused_bytes": unused_img_size,
            "unused_size": format_bytes(unused_img_size),
        },
        "build_cache": {
            "count": cache_count,
            "reclaimable_bytes": cache_reclaimable,
            "reclaimable_size": format_bytes(cache_reclaimable),
        },
        "containers": {
            "total_count": len(containers),
            "stopped_count": stopped_count,
            "reclaimable_bytes": stopped_size,
            "reclaimable_size": format_bytes(stopped_size),
        },
        "volumes": {
            "total_count": len(volumes),
            "unused_count": unused_vol_count,
            "reclaimable_bytes": unused_vol_size,
            "reclaimable_size": format_bytes(unused_vol_size),
        },
    }


def prune_docker_resources(
    prune_images: bool = True,
    all_unused_images: bool = False,
    prune_build_cache: bool = True,
    prune_containers: bool = False,
    prune_volumes: bool = False,
) -> dict[str, Any]:
    client = get_docker_client()
    freed_total = 0
    details: dict[str, Any] = {}

    if prune_containers:
        res = client.containers.prune() or {}
        freed = int(res.get("SpaceReclaimed") or 0)
        freed_total += freed
        details["containers"] = {
            "removed": len(res.get("ContainersDeleted") or []),
            "freed": format_bytes(freed),
        }

    if prune_images:
        # dangling=True chỉ xoá layer rác <none>; dangling=False xoá toàn bộ image không gắn container
        res = client.images.prune(filters={"dangling": not all_unused_images}) or {}
        freed = int(res.get("SpaceReclaimed") or 0)
        freed_total += freed
        details["images"] = {
            "removed": len(res.get("ImagesDeleted") or []),
            "freed": format_bytes(freed),
        }

    if prune_build_cache:
        try:
            res = client.api.prune_builds() or {}
            freed = int(res.get("SpaceReclaimed") or 0)
            freed_total += freed
            details["build_cache"] = {"freed": format_bytes(freed)}
        except Exception as exc:
            details["build_cache"] = {"error": str(exc)[:120]}

    if prune_volumes:
        res = client.volumes.prune() or {}
        freed = int(res.get("SpaceReclaimed") or 0)
        freed_total += freed
        details["volumes"] = {
            "removed": len(res.get("VolumesDeleted") or []),
            "freed": format_bytes(freed),
        }

    return {
        "ok": True,
        "freed_bytes": freed_total,
        "freed_display": format_bytes(freed_total),
        "details": details,
        "storage": get_docker_disk_usage(),
    }
