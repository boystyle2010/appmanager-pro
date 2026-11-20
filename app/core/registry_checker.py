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

PINNED_TAG_RE = re.compile(r"^(v?)(\d+(?:\.\d+)+)(-[a-zA-Z0-9._-]+)?$")
PRERELEASE_RE = re.compile(r"(alpha|beta|rc\d*|dev|nightly|canary|pre|test|snapshot)", re.I)

GENERIC_VERSION_WORDS = {
    "", "unknown", "none", "latest", "main", "master",
    "edge", "stable", "dev", "nightly", "beta", "alpine",
}

NON_TAG_CHANGELOG_SOURCES = {
    "CHANGELOG.md", "changelog.md", "HISTORY.md", "RELEASES.md", "NEWS", "Commits",
}

KNOWN_IMAGE_REPOS: dict[str, str] = {
    "library/php": "php/php-src",
    "library/nginx": "nginx/nginx",
    "library/redis": "redis/redis",
    "library/postgres": "postgres/postgres",
    "library/mariadb": "MariaDB/server",
    "library/mysql": "mysql/mysql-server",
    "library/mongo": "mongodb/mongo",
    "library/caddy": "caddyserver/caddy",
    "library/traefik": "traefik/traefik",
    "portainer/portainer-ce": "portainer/portainer",
    "cloudflare/cloudflared": "cloudflare/cloudflared",
    "filebrowser/filebrowser": "filebrowser/filebrowser",
    "nicolargo/glances": "nicolargo/glances",
    "henrygd/beszel": "henrygd/beszel",
    "koush/scrypted": "koush/scrypted",
    "zwavejs/zwave-js-ui": "zwave-js/zwave-js-ui",
    "louislam/uptime-kuma": "louislam/uptime-kuma",
    "syncthing/syncthing": "syncthing/syncthing",
    "linuxserver/syncthing": "syncthing/syncthing",
}

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
    ref = image_ref.strip()
    if "@sha256:" in ref:
        ref = ref.split("@sha256:", 1)[0]

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


def _parse_pinned_tag(tag: str) -> Optional[dict[str, Any]]:
    m = PINNED_TAG_RE.match(tag.strip())
    if not m:
        return None
    prefix, ver_str, suffix = m.group(1), m.group(2), m.group(3) or ""
    nums = tuple(int(p) for p in ver_str.split("."))
    return {
        "prefix": prefix,
        "ver_str": ver_str,
        "nums": nums,
        "suffix": suffix,
        "is_pre": bool(PRERELEASE_RE.search(suffix)),
    }


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
    method: str = "GET",
) -> httpx.Response:
    headers = {"Accept": accept}
    if scope_key in token_cache:
        headers["Authorization"] = f"Bearer {token_cache[scope_key]}"

    req_fn = client.head if method == "HEAD" else client.get
    resp = await req_fn(url, headers=headers, follow_redirects=True)
    if resp.status_code == 401 and "www-authenticate" in resp.headers:
        token = await _fetch_bearer_token(client, resp.headers["www-authenticate"])
        if token:
            token_cache[scope_key] = token
            headers["Authorization"] = f"Bearer {token}"
            resp = await req_fn(url, headers=headers, follow_redirects=True)
    return resp


def _slug_from_text(text: str) -> Optional[str]:
    s = (text or "").strip()
    if not s:
        return None
    for pat in (
        r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
        r"raw\.githubusercontent\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
    ):
        m = re.search(pat, s)
        if m:
            return m.group(1).removesuffix(".git").rstrip("/")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", s):
        return s.removesuffix(".git")
    return None


def extract_github_slug(
    source_url: str,
    image_ref: str,
    icon_url: str = "",
) -> Optional[str]:
    for candidate in (source_url, icon_url):
        slug = _slug_from_text(candidate)
        if slug:
            return slug

    if image_ref.startswith("ghcr.io/"):
        path = image_ref[len("ghcr.io/") :].split(":")[0].split("@")[0]
        parts = path.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"

    registry, repo, _ = parse_image_ref(image_ref)
    if registry == "registry-1.docker.io":
        mapped = KNOWN_IMAGE_REPOS.get(repo.lower())
        if mapped:
            return mapped

    return None


async def fetch_github_release(client: httpx.AsyncClient, slug: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppManager-Pro/0.3.2",
    }
    gh_token = get_setting("github_token", "").strip()
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    out = {
        "release_tag": "",
        "release_url": f"https://github.com/{slug}",
        "published_at": "",
        "changelog": "",
        "error": "",
    }

    try:
        resp = await client.get(
            f"https://api.github.com/repos/{slug}/releases/latest",
            headers=headers,
        )

        if resp.status_code == 403:
            out["error"] = "GitHub API rate limit reached (60/hr). Add a GitHub Token in Settings."
            return out

        data = None
        if resp.status_code == 200:
            data = resp.json()
        elif resp.status_code == 404:
            resp2 = await client.get(
                f"https://api.github.com/repos/{slug}/releases?per_page=1",
                headers=headers,
            )
            if resp2.status_code == 403:
                out["error"] = "GitHub API rate limit reached. Add a GitHub Token in Settings."
                return out
            if resp2.status_code == 200 and resp2.json():
                data = resp2.json()[0]

        if data:
            out["release_tag"] = str(data.get("tag_name") or "")
            out["release_url"] = str(data.get("html_url") or out["release_url"])
            out["published_at"] = str(data.get("published_at") or "")
            body = str(data.get("body") or "").strip()
            if body:
                out["changelog"] = body
                return out

        repo_resp = await client.get(f"https://api.github.com/repos/{slug}", headers=headers)
        if repo_resp.status_code == 404:
            out["error"] = f"GitHub repo '{slug}' not found or Private (add GitHub Token in Settings)."
            return out
        if repo_resp.status_code == 403:
            out["error"] = "GitHub API rate limit reached. Add a GitHub Token in Settings."
            return out
        default_branch = (repo_resp.json() if repo_resp.status_code == 200 else {}).get("default_branch", "main")

        raw_headers = {**headers, "Accept": "application/vnd.github.raw+json"}
        for fname in ("CHANGELOG.md", "changelog.md", "HISTORY.md", "RELEASES.md", "NEWS"):
            c_resp = await client.get(
                f"https://api.github.com/repos/{slug}/contents/{fname}",
                headers=raw_headers,
            )
            if c_resp.status_code == 200 and c_resp.text.strip():
                text = c_resp.text.strip()
                if len(text) > 7000:
                    text = text[:7000] + "\n\n---\n*Truncated — view full changelog on GitHub.*"
                out["release_tag"] = out["release_tag"] or fname
                out["release_url"] = f"https://github.com/{slug}/blob/{default_branch}/{fname}"
                out["changelog"] = text
                return out

        cm_resp = await client.get(
            f"https://api.github.com/repos/{slug}/commits?per_page=6",
            headers=headers,
        )
        if cm_resp.status_code == 200 and isinstance(cm_resp.json(), list) and cm_resp.json():
            lines = ["### Recent Commits"]
            for c in cm_resp.json():
                sha = str(c.get("sha") or "")[:7]
                commit_obj = c.get("commit") or {}
                msg = str(commit_obj.get("message") or "").splitlines()[0].strip()
                date_str = str((commit_obj.get("author") or {}).get("date") or "")[:10]
                lines.append(f"- `{sha}` {msg} *({date_str})*")
            out["release_tag"] = out["release_tag"] or "Commits"
            out["release_url"] = f"https://github.com/{slug}/commits/{default_branch}"
            out["changelog"] = "\n".join(lines)
            return out

    except Exception as exc:
        out["error"] = f"GitHub fetch error: {str(exc)[:120]}"

    return out


async def _fetch_remote_manifest_info(
    client: httpx.AsyncClient,
    registry: str,
    repo: str,
    manifest_data: dict[str, Any],
    arch_digest: Optional[str],
    token_cache: dict[str, str],
    scope_key: str,
) -> tuple[str, dict[str, str]]:
    """
    Trả về (remote_config_digest, remote_oci_labels).
    So sánh remote_config_digest với container.image.id giúp loại bỏ 100% báo update ảo trên GHCR/Buildx.
    """
    try:
        single_manifest = manifest_data
        if "manifests" in manifest_data and arch_digest:
            m_url = f"https://{registry}/v2/{repo}/manifests/{arch_digest}"
            m_resp = await _registry_request(
                client, m_url, SINGLE_MANIFEST_ACCEPT, token_cache, scope_key
            )
            if m_resp.status_code != 200:
                return "", {}
            single_manifest = m_resp.json()

        config_digest = str((single_manifest.get("config") or {}).get("digest") or "").strip()
        if not config_digest:
            return "", {}

        b_url = f"https://{registry}/v2/{repo}/blobs/{config_digest}"
        b_resp = await _registry_request(client, b_url, "*/*", token_cache, scope_key)
        if b_resp.status_code != 200:
            return config_digest, {}

        blob = b_resp.json()
        labels = (blob.get("config") or {}).get("Labels") or {}
        return config_digest, labels
    except Exception:
        return "", {}


async def _discover_newer_pinned_tag(
    client: httpx.AsyncClient,
    registry: str,
    repo: str,
    cur_parsed: dict[str, Any],
    github_release_tag: str,
    token_cache: dict[str, str],
    scope_key: str,
) -> Optional[tuple[str, str]]:
    cur_nums = cur_parsed["nums"]
    cur_prefix = cur_parsed["prefix"]
    cur_suffix = cur_parsed["suffix"]
    allow_pre = cur_parsed["is_pre"]

    candidates: list[tuple[tuple[int, ...], str]] = []

    if github_release_tag:
        gh_p = _parse_pinned_tag(github_release_tag)
        if gh_p and gh_p["nums"] > cur_nums and (allow_pre or not gh_p["is_pre"]):
            reconstructed = f"{cur_prefix}{gh_p['ver_str']}{cur_suffix}"
            candidates.append((gh_p["nums"], reconstructed))
            alt = f"{gh_p['prefix']}{gh_p['ver_str']}{cur_suffix}"
            if alt != reconstructed:
                candidates.append((gh_p["nums"], alt))

    tag_names: list[str] = []
    try:
        if registry == "registry-1.docker.io":
            hub_url = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=60&ordering=last_updated"
            r = await client.get(hub_url)
            if r.status_code == 200:
                tag_names = [t.get("name", "") for t in (r.json().get("results") or [])]
        else:
            t_url = f"https://{registry}/v2/{repo}/tags/list?n=100"
            r = await _registry_request(client, t_url, "application/json", token_cache, scope_key)
            if r.status_code == 200:
                tag_names = r.json().get("tags") or []
    except Exception:
        pass

    for tname in tag_names:
        tp = _parse_pinned_tag(tname)
        if not tp:
            continue
        if tp["suffix"].lower() != cur_suffix.lower():
            continue
        if tp["prefix"] != cur_prefix:
            continue
        if not allow_pre and tp["is_pre"]:
            continue
        if len(tp["nums"]) != len(cur_nums):
            continue
        if tp["nums"] > cur_nums:
            candidates.append((tp["nums"], tname))

    if not candidates:
        return None

    seen: set[str] = set()
    candidates.sort(key=lambda x: x[0], reverse=True)
    for _, cand_tag in candidates:
        if cand_tag in seen:
            continue
        seen.add(cand_tag)
        m_url = f"https://{registry}/v2/{repo}/manifests/{cand_tag}"
        check_resp = await _registry_request(
            client, m_url, MANIFEST_ACCEPT, token_cache, scope_key, method="HEAD"
        )
        if check_resp.status_code == 200:
            digest = check_resp.headers.get("docker-content-digest", "").strip()
            return cand_tag, digest

    return None


async def check_single_app(
    app_info: dict[str, Any],
    client: httpx.AsyncClient,
    fetch_changelog_always: bool = False,
) -> dict[str, Any]:
    name = app_info["name"]
    image_ref = app_info["image"]
    icon_url = app_info.get("icon") or ""
    local_digests: list[str] = app_info.get("local_digests") or []
    local_image_id: str = (app_info.get("image_id") or "").strip()
    current_version = app_info.get("version") or "latest"
    pref = get_app_pref(name)
    prev_cache = get_update_cache_item(name)
    now_iso = datetime.now(timezone.utc).isoformat()

    custom_repo = (pref.get("custom_repo") or "").strip()
    source_url = custom_repo or app_info.get("source_url") or ""

    result = {
        "container_name": name,
        "image": image_ref,
        "local_digest": local_digests[0] if local_digests else "",
        "remote_digest": "",
        "current_version": current_version,
        "remote_version": current_version,
        "target_tag": "",
        "has_update": 0,
        "source_url": source_url,
        "changelog": "" if fetch_changelog_always else (prev_cache.get("changelog") or ""),
        "release_tag": "" if fetch_changelog_always else (prev_cache.get("release_tag") or ""),
        "release_url": "" if fetch_changelog_always else (prev_cache.get("release_url") or ""),
        "published_at": "" if fetch_changelog_always else (prev_cache.get("published_at") or ""),
        "checked_at": now_iso,
        "error": "",
    }

    registry, repo, tag = parse_image_ref(image_ref)
    pinned_info = _parse_pinned_tag(tag)
    scope_key = f"{registry}/{repo}"
    token_cache: dict[str, str] = {}
    has_digest_update = False
    manifest_data: dict[str, Any] = {}
    arch_digest: Optional[str] = None
    remote_digest = ""
    remote_labels: dict[str, str] = {}

    # Bước 1: Kiểm tra Registry Digest + đối chiếu chắc chắn bằng Config ID (image_id)
    if local_digests:
        try:
            manifest_url = f"https://{registry}/v2/{repo}/manifests/{tag}"
            resp = await _registry_request(
                client, manifest_url, MANIFEST_ACCEPT, token_cache, scope_key
            )
            if resp.status_code == 200:
                top_digest = resp.headers.get("docker-content-digest", "").strip()
                manifest_data = resp.json() if resp.content else {}

                arch = _host_arch()
                if isinstance(manifest_data.get("manifests"), list):
                    for entry in manifest_data["manifests"]:
                        plat = entry.get("platform") or {}
                        if plat.get("os") == "linux" and plat.get("architecture") == arch:
                            arch_digest = entry.get("digest")
                            break

                remote_candidates = {d for d in (top_digest, arch_digest) if d}
                remote_digest = top_digest or arch_digest or ""
                result["remote_digest"] = remote_digest

                digest_differs = bool(remote_candidates) and not any(
                    d in remote_candidates for d in local_digests
                )

                if digest_differs:
                    # Đối chiếu tầng 2 bằng Config Digest (khớp tuyệt đối với container.image.id)
                    remote_cfg_digest, remote_labels = await _fetch_remote_manifest_info(
                        client, registry, repo, manifest_data, arch_digest, token_cache, scope_key
                    )
                    if local_image_id and remote_cfg_digest and local_image_id == remote_cfg_digest:
                        # Ảnh local và server thực chất giống hệt nhau -> không báo update ảo
                        has_digest_update = False
                    else:
                        has_digest_update = True
            else:
                result["error"] = f"Registry HTTP {resp.status_code}"
        except Exception as exc:
            result["error"] = str(exc)[:180]
    else:
        result["error"] = "Local build (no registry digest)"

    # Bước 2: Lấy Changelog từ GitHub (Releases -> CHANGELOG.md -> Commits)
    slug = extract_github_slug(source_url, image_ref, icon_url)
    if slug:
        result["source_url"] = f"https://github.com/{slug}"
        need_gh = (
            fetch_changelog_always
            or has_digest_update
            or bool(pinned_info)
            or not result["changelog"]
            or bool(custom_repo)
        )
        if need_gh:
            gh_info = await fetch_github_release(client, slug)
            if gh_info["changelog"]:
                result["release_tag"] = gh_info["release_tag"]
                result["release_url"] = gh_info["release_url"]
                result["published_at"] = gh_info["published_at"]
                result["changelog"] = gh_info["changelog"]
            elif gh_info["error"] and fetch_changelog_always:
                result["error"] = gh_info["error"]
    elif custom_repo and fetch_changelog_always:
        result["error"] = "Invalid GitHub URL format. Use https://github.com/owner/repo or owner/repo."

    # Bước 3: Xác định phiên bản mới cho Pinned Tag hoặc Rolling Tag
    if local_digests:
        try:
            newer_tag_match = None
            if pinned_info:
                newer_tag_match = await _discover_newer_pinned_tag(
                    client,
                    registry,
                    repo,
                    pinned_info,
                    result["release_tag"],
                    token_cache,
                    scope_key,
                )

            if newer_tag_match:
                new_tag, new_digest = newer_tag_match
                result["has_update"] = 1
                result["target_tag"] = new_tag
                result["remote_version"] = new_tag
                if new_digest:
                    result["remote_digest"] = new_digest
            elif has_digest_update:
                result["has_update"] = 1

                # Lọc bỏ các chữ chung chung kiểu "latest", "main" khi đọc OCI version
                found_real_ver = ""
                for key in (
                    "org.opencontainers.image.version",
                    "build_version",
                    "org.label-schema.version",
                    "version",
                ):
                    val = str(remote_labels.get(key) or "").strip()
                    if val and val.lower() not in GENERIC_VERSION_WORDS:
                        found_real_ver = val
                        break

                if not result["source_url"]:
                    found_src = (
                        remote_labels.get("org.opencontainers.image.source")
                        or remote_labels.get("org.opencontainers.image.url")
                        or ""
                    )
                    if found_src:
                        result["source_url"] = found_src

                if found_real_ver and found_real_ver.lstrip("v") != current_version.lstrip("v"):
                    result["remote_version"] = found_real_ver
                elif (
                    result["release_tag"]
                    and result["release_tag"] not in NON_TAG_CHANGELOG_SOURCES
                    and result["release_tag"].lstrip("v") != current_version.lstrip("v")
                ):
                    result["remote_version"] = result["release_tag"]
                elif remote_digest:
                    result["remote_version"] = f"build-{remote_digest[7:14]}"
                else:
                    result["remote_version"] = "New build"
        except Exception as exc:
            if not result["error"]:
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
