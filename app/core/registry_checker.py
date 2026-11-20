import asyncio
import platform
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.database import (
    get_app_pref,
    get_setting,
    get_update_cache_item,
    save_update_cache,
)
from app.core.docker_client import list_all_apps

MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)

SINGLE_MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)

_check_lock = asyncio.Lock()
_is_checking = False


def is_check_running() -> bool:
    return _is_checking


def _host_arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    if "armv7" in m:
        return "arm"
    return "amd64"


def parse_image_ref(image_ref: str) -> tuple[str, str, str]:
    """Tách image string thành (registry, repository, tag)."""
    ref = image_ref.strip()
    if "@sha256:" in ref:
        ref = ref.split("@sha256:", 1)[0]

    # Tách tag cẩn thận (tránh nhầm với port registry kiểu localhost:5000/app)
    last_slash = ref.rfind("/")
    last_colon = ref.rfind(":")
    if last_colon > last_slash:
        name_part = ref[:last_colon]
        tag = ref[last_colon + 1 :]
    else:
        name_part = ref
        tag = "latest"

    parts = name_part.split("/")
    if len(parts) == 1:
        return "registry-1.docker.io", f"library/{parts[0]}", tag

    first = parts[0]
    if "." in first or ":" in first or first == "localhost":
        registry = "registry-1.docker.io" if first in ("docker.io", "index.docker.io") else first
        repo = "/".join(parts[1:])
        if registry == "registry-1.docker.io" and "/" not in repo:
            repo = f"library/{repo}"
        return registry, repo, tag

    return "registry-1.docker.io", name_part, tag


def _parse_www_authenticate(header_val: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for match in re.finditer(r'(\w+)="([^"]*)"', header_val or ""):
        params[match.group(1)] = match.group(2)
    return params


async def _fetch_bearer_token(client: httpx.AsyncClient, www_auth: str) -> Optional[str]:
    params = _parse_www_authenticate(www_auth)
    realm = params.get("realm")
    if not realm:
        return None
    query = {}
    if params.get("service"):
        query["service"] = params["service"]
    if params.get("scope"):
        query["scope"] = params["scope"]
    resp = await client.get(realm, params=query)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("token") or data.get("access_token")


async def _registry_request(
    client: httpx.AsyncClient,
    url: str,
    accept: str,
    token_cache: dict[str, str],
    scope_key: str,
) -> httpx.Response:
    headers = {"Accept": accept}
    if scope_key in token_cache:
        headers["Authorization"] = f"Bearer {token_cache[scope_key]}"

    resp = await client.get(url, headers=headers, follow_redirects=True)
    if resp.status_code == 401 and "www-authenticate" in resp.headers:
        token = await _fetch_bearer_token(client, resp.headers["www-authenticate"])
        if token:
            token_cache[scope_key] = token
            headers["Authorization"] = f"Bearer {token}"
            resp = await client.get(url, headers=headers, follow_redirects=True)
    return resp


def extract_github_slug(source_url: str, image_ref: str) -> Optional[str]:
    """Trích xuất 'owner/repo' từ OCI source URL, custom repo, hoặc ghcr.io image."""
    for candidate in (source_url,):
        if not candidate:
            continue
        m = re.search(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", candidate)
        if m:
            slug = m.group(1).removesuffix(".git").rstrip("/")
            return slug

    # Fallback thông minh cho image lưu trên ghcr.io
    if image_ref.startswith("ghcr.io/"):
        path = image_ref[len("ghcr.io/") :].split(":")[0].split("@")[0]
        parts = path.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    return None


async def fetch_github_release(
    client: httpx.AsyncClient, slug: str
) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppManager-Pro/0.2.0",
    }
    gh_token = get_setting("github_token", "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    try:
        resp = await client.get(
            f"https://api.github.com/repos/{slug}/releases/latest",
            headers=headers,
        )
        data = None
        if resp.status_code == 200:
            data = resp.json()
        elif resp.status_code == 404:
            # Nếu repo chỉ dùng pre-release hoặc không đánh dấu latest
            resp2 = await client.get(
                f"https://api.github.com/repos/{slug}/releases?per_page=1",
                headers=headers,
            )
            if resp2.status_code == 200 and resp2.json():
                data = resp2.json()[0]

        if data:
            return {
                "release_tag": str(data.get("tag_name") or ""),
                "release_url": str(data.get("html_url") or ""),
                "published_at": str(data.get("published_at") or ""),
                "changelog": str(data.get("body") or "").strip(),
            }
    except Exception:
        pass

    return {"release_tag": "", "release_url": "", "published_at": "", "changelog": ""}


async def _fetch_remote_oci_labels(
    client: httpx.AsyncClient,
    registry: str,
    repo: str,
    manifest_data: dict[str, Any],
    arch_digest: Optional[str],
    token_cache: dict[str, str],
    scope_key: str,
) -> dict[str, str]:
    """Đọc config blob của image trên Registry để lấy phiên bản thực và link GitHub."""
    try:
        single_manifest = manifest_data
        if "manifests" in manifest_data and arch_digest:
            m_url = f"https://{registry}/v2/{repo}/manifests/{arch_digest}"
            m_resp = await _registry_request(
                client, m_url, SINGLE_MANIFEST_ACCEPT, token_cache, scope_key
            )
            if m_resp.status_code != 200:
                return {}
            single_manifest = m_resp.json()

        config_digest = (single_manifest.get("config") or {}).get("digest")
        if not config_digest:
            return {}

        b_url = f"https://{registry}/v2/{repo}/blobs/{config_digest}"
        b_resp = await _registry_request(
            client, b_url, "*/*", token_cache, scope_key
        )
        if b_resp.status_code != 200:
            return {}

        blob = b_resp.json()
        return (blob.get("config") or {}).get("Labels") or {}
    except Exception:
        return {}


async def check_single_app(
    app_info: dict[str, Any],
    client: httpx.AsyncClient,
    fetch_changelog_always: bool = False,
) -> dict[str, Any]:
    name = app_info["name"]
    image_ref = app_info["image"]
    local_digests: list[str] = app_info.get("local_digests") or []
    current_version = app_info.get("version") or "latest"
    pref = get_app_pref(name)
    prev_cache = get_update_cache_item(name)
    now_iso = datetime.now(timezone.utc).isoformat()

    source_url = pref.get("custom_repo") or app_info.get("source_url") or ""

    result = {
        "container_name": name,
        "image": image_ref,
        "local_digest": local_digests[0] if local_digests else "",
        "remote_digest": "",
        "current_version": current_version,
        "remote_version": current_version,
        "has_update": 0,
        "source_url": source_url,
        "changelog": prev_cache.get("changelog") or "",
        "release_tag": prev_cache.get("release_tag") or "",
        "release_url": prev_cache.get("release_url") or "",
        "published_at": prev_cache.get("published_at") or "",
        "checked_at": now_iso,
        "error": "",
    }

    if not local_digests:
        result["error"] = "Local build (no registry digest)"
        save_update_cache(result)
        return result

    registry, repo, tag = parse_image_ref(image_ref)
    scope_key = f"{registry}/{repo}"
    token_cache: dict[str, str] = {}

    try:
        manifest_url = f"https://{registry}/v2/{repo}/manifests/{tag}"
        resp = await _registry_request(
            client, manifest_url, MANIFEST_ACCEPT, token_cache, scope_key
        )
        if resp.status_code != 200:
            result["error"] = f"Registry HTTP {resp.status_code}"
            save_update_cache(result)
            return result

        top_digest = resp.headers.get("docker-content-digest", "").strip()
        manifest_data = resp.json() if resp.content else {}

        # Tìm digest khớp kiến trúc máy nếu là multi-arch manifest list
        arch = _host_arch()
        arch_digest = None
        if isinstance(manifest_data.get("manifests"), list):
            for entry in manifest_data["manifests"]:
                plat = entry.get("platform") or {}
                if plat.get("os") == "linux" and plat.get("architecture") == arch:
                    arch_digest = entry.get("digest")
                    break

        remote_candidates = {d for d in (top_digest, arch_digest) if d}
        remote_digest = top_digest or arch_digest or ""
        result["remote_digest"] = remote_digest

        has_update = bool(remote_candidates) and not any(
            d in remote_candidates for d in local_digests
        )
        result["has_update"] = 1 if has_update else 0

        # Nếu có bản cập nhật mới, đọc OCI Labels trên server để lấy phiên bản thực
        remote_labels: dict[str, str] = {}
        if has_update:
            remote_labels = await _fetch_remote_oci_labels(
                client, registry, repo, manifest_data, arch_digest, token_cache, scope_key
            )
            for key in (
                "org.opencontainers.image.version",
                "build_version",
                "org.label-schema.version",
                "version",
            ):
                val = remote_labels.get(key)
                if val and str(val).lower() not in ("unknown", "none", ""):
                    result["remote_version"] = str(val).strip()
                    break

            if not source_url:
                source_url = (
                    remote_labels.get("org.opencontainers.image.source")
                    or remote_labels.get("org.opencontainers.image.url")
                    or ""
                )
                result["source_url"] = source_url

        # Lấy Changelog từ GitHub khi có update hoặc khi mở chi tiết app
        slug = extract_github_slug(source_url, image_ref)
        if slug:
            if not result["source_url"]:
                result["source_url"] = f"https://github.com/{slug}"
            need_gh = (
                fetch_changelog_always
                or has_update
                or not result["changelog"]
                or pref.get("custom_repo")
            )
            if need_gh:
                gh_info = await fetch_github_release(client, slug)
                if gh_info["release_tag"]:
                    result["release_tag"] = gh_info["release_tag"]
                    result["release_url"] = gh_info["release_url"]
                    result["published_at"] = gh_info["published_at"]
                    result["changelog"] = gh_info["changelog"]

        # Nếu image có digest mới nhưng không gắn OCI version label -> dùng GitHub tag hoặc short digest
        if has_update and result["remote_version"] == current_version:
            if result["release_tag"] and result["release_tag"].lstrip("v") != current_version.lstrip("v"):
                result["remote_version"] = result["release_tag"]
            elif remote_digest:
                result["remote_version"] = f"{tag} ({remote_digest[7:14]})"

    except Exception as exc:
        result["error"] = str(exc)[:180]

    save_update_cache(result)
    return result


async def check_all_updates() -> dict[str, Any]:
    global _is_checking
    if _check_lock.locked():
        return {"ok": True, "already_running": True}

    async with _check_lock:
        _is_checking = True
        try:
            apps_data = await asyncio.to_thread(list_all_apps, False)
            apps = apps_data["apps"]
            sem = asyncio.Semaphore(6)

            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0)) as client:
                async def _bounded(app_item):
                    async with sem:
                        return await check_single_app(app_item, client)

                results = await asyncio.gather(*(_bounded(a) for a in apps), return_exceptions=True)

            updates_found = sum(
                1 for r in results if isinstance(r, dict) and r.get("has_update") == 1
            )
            return {
                "ok": True,
                "checked": len(apps),
                "updates_found": updates_found,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            _is_checking = False


async def check_one_app_by_name(container_name: str) -> Optional[dict[str, Any]]:
    apps_data = await asyncio.to_thread(list_all_apps, True)
    target = next((a for a in apps_data["apps"] if a["name"] == container_name), None)
    if not target:
        return None
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0)) as client:
        return await check_single_app(target, client, fetch_changelog_always=True)
