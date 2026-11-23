import asyncio
import json
import logging
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
from app.core.docker_client import GENERIC_VERSIONS, list_all_apps, version_from_labels

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

# Tag ghim phiên bản: [chữ-]v?X.Y[.Z...][-biến_thể]  vd 8.5.12-apache, v3.1.0, version-1.2.3, 1.2.3-ls45
PINNED_TAG_RE = re.compile(r"^((?:[a-z]+-)?v?)(\d+(?:\.\d+)+)(-[a-zA-Z0-9._-]+)?$")
PRERELEASE_RE = re.compile(r"(alpha|beta|rc\d*|dev|nightly|canary|pre|test|snapshot)", re.I)

GENERIC_VERSION_WORDS = {
    "", "unknown", "none", "latest", "main", "master",
    "edge", "stable", "dev", "nightly", "beta", "alpine",
}

NON_TAG_CHANGELOG_SOURCES = {
    "CHANGELOG.md", "changelog.md", "HISTORY.md", "RELEASES.md", "RELEASE_NOTES", "RELEASE_NOTES.md", "CHANGES.md", "NEWS", "Commits",
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

logger = logging.getLogger("appmanager.registry")
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
        # Biến thể bỏ số (vd "-ls45" -> "-ls#", "-alpine3.20" -> "-alpine#.#"): số build / bản OS gốc đổi
        # theo từng lần phát hành nhưng vẫn là cùng một biến thể
        "variant": re.sub(r"\d+", "#", suffix.lower()),
        "build": tuple(int(x) for x in re.findall(r"\d+", suffix)),
        "is_pre": bool(PRERELEASE_RE.search(suffix)),
    }


def _same_line(cur: dict[str, Any], cand: dict[str, Any]) -> bool:
    """
    Có được đề xuất cand thay cho cur không: cùng tiền tố, cùng biến thể, cùng số thành phần phiên bản,
    và CÙNG PHIÊN BẢN LỚN (nhảy major thường phá vỡ tương thích / cần chuyển đổi dữ liệu, vd postgres 16 -> 17).
    Phiên bản theo lịch (major là năm, vd Home Assistant 2026.11.2) thì cho qua năm mới.
    """
    if cand["prefix"] != cur["prefix"] or cand["variant"] != cur["variant"]:
        return False
    if len(cand["nums"]) != len(cur["nums"]):
        return False
    if cand["is_pre"] and not cur["is_pre"]:
        return False
    if cur["nums"][0] < 1900 and cand["nums"][0] != cur["nums"][0]:
        return False
    return (cand["nums"], cand["build"]) > (cur["nums"], cur["build"])


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


_HASH_RE = re.compile(r"[a-f0-9]{40,}", re.I)
_CHECKSUM_HEAD_RE = re.compile(
    r"^[#>*_\s-]*(sha-?\d*\s*)?(sha-?256|sha-?512|md5)?\s*(checksums?|hashes|digests?)[\s:*_]*$", re.I
)


_ONLY_HASH_RE = re.compile(r"^[\s`*>|-]*(?:[\w./+@-]+\s*[:=]?\s*)?`?(?:sha(?:256|512):)?[a-f0-9]{40,}`?(?:\s+\*?[\w./+@-]+)?[\s`|]*$", re.I)


def strip_checksums(md: str) -> str:
    """Bỏ phần 'SHA256 Checksums' (danh sách hash) khỏi release notes; trả về '' nếu không còn nội dung thật."""
    out: list[str] = []
    skipping = False
    for line in (md or "").splitlines():
        t = line.strip()
        if _CHECKSUM_HEAD_RE.match(t) or re.match(r"^[#>*_\s-]*sha-?(256|512)(\s*(sums?|checksums?|hashes))?[\s:*_]*$", t, re.I):
            skipping = True
            continue
        if skipping:
            if t == "" or t.startswith("```") or t.startswith("|") or _HASH_RE.search(t):
                continue
            skipping = False
        # Chỉ bỏ dòng CHỈ gồm mã hash (+ tên file); không đụng tới ghi chú có link commit
        if _ONLY_HASH_RE.match(t):
            continue
        out.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    # Chỉ còn tiêu đề kiểu "Release 2026.5.0" (không có nội dung thật) -> coi như rỗng
    meaningful = [l for l in text.splitlines() if l.strip() and not re.match(r"^[#\s]*release\s+v?[\d.]+\s*$", l.strip(), re.I)]
    return text if meaningful else ""


_VERSION_LINE_RE = re.compile(r"^v?\d+(?:\.\d+){1,3}[A-Za-z0-9.+-]*$")


def summarize_release_notes(text: str, max_blocks: int = 3) -> str:
    """
    Với file kiểu cloudflared RELEASE_NOTES / CHANGES.md (dòng phiên bản đứng riêng, bên dưới là các dòng '- ...'),
    chỉ lấy vài phiên bản mới nhất và đổi thành Markdown gọn: '### 2026.11.1' + danh sách gạch đầu dòng.
    Nếu file không có dạng này thì trả nguyên văn.
    """
    lines = (text or "").splitlines()
    first = next((l.strip() for l in lines if l.strip()), "")
    if not _VERSION_LINE_RE.match(first):
        return text
    blocks: list[list[str]] = []
    for line in lines:
        t = line.strip()
        if _VERSION_LINE_RE.match(t):
            if len(blocks) >= max_blocks:
                break
            blocks.append([f"### {t}", ""])
        elif t and blocks:
            blocks[-1].append(t if t.startswith(("-", "*")) else f"- {t}")
    return "\n\n".join("\n".join(b).strip() for b in blocks)


async def fetch_github_release(client: httpx.AsyncClient, slug: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppManager-Pro/0.4.0",
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
            body = strip_checksums(str(data.get("body") or "").strip())
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
        for fname in ("CHANGELOG.md", "changelog.md", "HISTORY.md", "RELEASES.md", "RELEASE_NOTES", "RELEASE_NOTES.md", "CHANGES.md", "NEWS"):
            c_resp = await client.get(
                f"https://api.github.com/repos/{slug}/contents/{fname}",
                headers=raw_headers,
            )
            if c_resp.status_code == 200 and c_resp.text.strip():
                text = summarize_release_notes(c_resp.text.strip())
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

    candidates: list[tuple[tuple, str]] = []

    if github_release_tag and not cur_parsed["build"]:
        # Tag từ GitHub Release ghép với biến thể hiện tại (vd release 8.5.13 -> thử "8.5.13-apache");
        # tag có số build trong đuôi (vd -ls45) thì không đoán được -> chỉ dựa vào danh sách tag
        gh_p = _parse_pinned_tag(github_release_tag)
        if gh_p and not gh_p["is_pre"] or (gh_p and allow_pre):
            for pre in dict.fromkeys((cur_prefix, gh_p["prefix"])):
                guess = _parse_pinned_tag(f"{pre}{gh_p['ver_str']}{cur_suffix}")
                if guess and _same_line(cur_parsed, guess):
                    candidates.append(((guess["nums"], guess["build"]), f"{pre}{gh_p['ver_str']}{cur_suffix}"))

    tag_names: list[str] = []
    try:
        if registry == "registry-1.docker.io":
            # Repo lớn (vd php: >16.000 tag): ngoài các tag mới cập nhật, truy vấn thêm có lọc theo biến thể
            # (vd "-apache", "-ls") hoặc theo phiên bản lớn (vd "16.") để chắc chắn thấy bản mới cùng dòng.
            hub_base = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&ordering=last_updated"
            name_filter = re.sub(r"\d.*$", "", cur_suffix) if cur_suffix else f"{cur_prefix}{cur_nums[0]}."
            urls = [hub_base]
            if len(name_filter) > 1:
                urls.append(f"{hub_base}&name={name_filter}")
            for hub_url in urls:
                for _page in range(3):
                    try:
                        r = await client.get(hub_url)
                    except httpx.TransportError:
                        r = await client.get(hub_url)
                    if r.status_code != 200:
                        break
                    body = r.json()
                    tag_names += [t.get("name", "") for t in (body.get("results") or [])]
                    hub_url = body.get("next") or ""
                    if not hub_url:
                        break
        else:
            # Registry chuẩn (GHCR, lscr.io, quay...): đọc hết các trang (tag xếp theo chữ cái, bản mới thường ở cuối)
            t_url = f"https://{registry}/v2/{repo}/tags/list?n=1000"
            for _page in range(10):
                try:
                    r = await _registry_request(client, t_url, "application/json", token_cache, scope_key)
                except httpx.TransportError:
                    r = await _registry_request(client, t_url, "application/json", token_cache, scope_key)
                if r.status_code != 200:
                    break
                tag_names += r.json().get("tags") or []
                link = r.headers.get("link") or ""
                m = re.search(r"<([^>]+)>\s*;\s*rel=\"?next\"?", link)
                if not m:
                    break
                nxt = m.group(1)
                t_url = nxt if nxt.startswith("http") else f"https://{registry}{nxt}"
    except Exception as exc:  # giữ các tag đã đọc được; lỗi mạng giữa chừng không làm mất cả lần kiểm tra
        logger.warning("Tag listing for %s/%s stopped early: %s", registry, repo, exc)

    for tname in dict.fromkeys(tag_names):
        tp = _parse_pinned_tag(tname)
        if tp and _same_line(cur_parsed, tp):
            candidates.append(((tp["nums"], tp["build"]), tname))

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


# ---------------- Kênh phát hành (latest / beta ...) ----------------
STABLE_CHANNELS = ("latest", "stable", "release", "lts")
PRE_CHANNELS = ("beta", "next", "rc", "preview", "testing", "edge", "unstable", "nightly", "dev", "develop", "canary")
_CHANNEL_WORDS = STABLE_CHANNELS + PRE_CHANNELS


def channel_format(tag: str) -> Optional[tuple[str, str]]:
    """
    Tag kênh -> (mẫu, kênh). Vd "latest" -> ("{}", "latest"), "latest-full" -> ("{}-full", "latest"),
    "ubuntu-latest" -> ("ubuntu-{}", "latest"), "beta" -> ("{}", "beta"). Tag phiên bản / tag khác -> None.
    """
    t = (tag or "").strip()
    for w in _CHANNEL_WORDS:
        if t == w:
            return "{}", w
        if t.startswith(w + "-"):
            return "{}" + t[len(w):], w
        if t.endswith("-" + w):
            return t[: -len(w)] + "{}", w
    return None


def _channel_kind(word: str) -> str:
    return "stable" if word in STABLE_CHANNELS else "pre"


async def _detect_channels(
    client: httpx.AsyncClient, registry: str, repo: str, tag: str, token_cache: dict[str, str], scope_key: str
) -> list[dict[str, Any]]:
    """
    Các kênh phát hành cùng biến thể với tag đang dùng. Chỉ giữ kênh thử nghiệm khi nó khác bản ổn định
    và mới hơn (phiên bản cao hơn hoặc được đẩy sau) -> tag beta bỏ quên không được đề xuất.
    """
    fmt = channel_format(tag)
    if not fmt:
        return []
    pattern = fmt[0]
    wanted = {pattern.format(w): w for w in _CHANNEL_WORDS}
    found: dict[str, dict[str, Any]] = {}
    digest_versions: dict[str, tuple[tuple, str]] = {}

    if registry == "registry-1.docker.io":
        base = f"https://hub.docker.com/v2/repositories/{repo}/tags"
        url = f"{base}?page_size=100&ordering=last_updated"
        try:
            for _page in range(2):
                r = await client.get(url)
                if r.status_code != 200:
                    break
                body = r.json()
                for t in body.get("results") or []:
                    name, dg = str(t.get("name") or ""), str(t.get("digest") or "")
                    if name in wanted:
                        found[name] = {"digest": dg, "updated": str(t.get("last_updated") or "")[:19]}
                    p = _parse_pinned_tag(name)
                    if dg and p:  # tag phiên bản cùng digest -> biết kênh đó đang là phiên bản nào
                        key = (p["nums"], f"{p['prefix']}{p['ver_str']}")
                        if dg not in digest_versions or key[0] > digest_versions[dg][0]:
                            digest_versions[dg] = key
                url = body.get("next") or ""
                if not url:
                    break
            # Tag đang dùng / tag ổn định có thể không nằm trong các tag mới cập nhật -> hỏi trực tiếp
            for name in dict.fromkeys([tag, pattern.format("latest")]):
                if name in wanted and name not in found:
                    r = await client.get(f"{base}/{name}")
                    if r.status_code == 200:
                        t = r.json()
                        found[name] = {"digest": str(t.get("digest") or ""), "updated": str(t.get("last_updated") or "")[:19]}
        except Exception as exc:
            logger.warning("Channel detection for %s failed: %s", repo, exc)
    else:
        try:
            t_url = f"https://{registry}/v2/{repo}/tags/list?n=1000"
            for _page in range(10):
                r = await _registry_request(client, t_url, "application/json", token_cache, scope_key)
                if r.status_code != 200:
                    break
                for name in r.json().get("tags") or []:
                    if name in wanted:
                        found[name] = {"digest": "", "updated": ""}
                m = re.search(r"<([^>]+)>\s*;\s*rel=\"?next\"?", r.headers.get("link") or "")
                if not m:
                    break
                nxt = m.group(1)
                t_url = nxt if nxt.startswith("http") else f"https://{registry}{nxt}"
            # Registry chuẩn không trả digest trong danh sách tag -> hỏi digest + nhãn phiên bản của từng kênh
            for name in list(found)[:8]:
                m_url = f"https://{registry}/v2/{repo}/manifests/{name}"
                resp = await _registry_request(client, m_url, MANIFEST_ACCEPT, token_cache, scope_key)
                if resp.status_code != 200:
                    continue
                dg = resp.headers.get("docker-content-digest", "").strip()
                manifest = resp.json() if resp.content else {}
                arch_dg = None
                for entry in manifest.get("manifests") or []:
                    plat = entry.get("platform") or {}
                    if plat.get("os") == "linux" and plat.get("architecture") == _host_arch():
                        arch_dg = entry.get("digest")
                        break
                _cfg, labels = await _fetch_remote_manifest_info(
                    client, registry, repo, manifest, arch_dg, token_cache, scope_key
                )
                found[name]["digest"] = dg
                ver = version_from_labels(labels)
                p = _parse_pinned_tag(ver.split("-")[0]) if ver else None
                if dg and ver:
                    digest_versions[dg] = (p["nums"] if p else (), ver)
        except Exception as exc:
            logger.warning("Channel detection for %s/%s failed: %s", registry, repo, exc)

    if tag not in found:
        found[tag] = {"digest": "", "updated": ""}
    channels: list[dict[str, Any]] = []
    for name, info in found.items():
        word = wanted.get(name, "")
        ver = digest_versions.get(info["digest"]) if info["digest"] else None
        channels.append({
            "tag": name, "channel": word, "kind": _channel_kind(word),
            "version": ver[1] if ver else "", "nums": list(ver[0]) if ver else [],
            "digest": info["digest"], "updated": info["updated"],
        })

    stable = next((c for c in channels if c["channel"] == "latest"), None) \
        or next((c for c in channels if c["kind"] == "stable"), None)
    cur = next((c for c in channels if c["tag"] == tag), None)
    kept: list[dict[str, Any]] = []
    for c in channels:
        if c["kind"] == "stable" and c["tag"] != tag and cur and c["digest"]:
            # Kênh ổn định khác (vd lts) trùng hẳn với bản đang dùng / latest -> không phải lựa chọn mới
            if c["digest"] == cur["digest"] or (stable and c is not stable and c["digest"] == stable["digest"]):
                continue
        if c["kind"] == "pre" and stable and c["tag"] != tag:
            if c["digest"] and c["digest"] == stable["digest"]:
                continue  # trùng bản ổn định
            if c["nums"] and stable["nums"] and c["nums"] <= stable["nums"]:
                continue  # cũ hơn / bằng bản ổn định
            if not c["nums"] and c["updated"] and stable["updated"] and c["updated"] < stable["updated"]:
                continue  # tag thử nghiệm bỏ quên
        kept.append(c)
    order = {w: i for i, w in enumerate(_CHANNEL_WORDS)}
    kept.sort(key=lambda c: (c["kind"] != "stable", order.get(c["channel"], 99)))
    pre = [c for c in kept if c["kind"] == "pre"][:3]  # tối đa 3 kênh thử nghiệm
    stables = [c for c in kept if c["kind"] == "stable"]
    if not pre and len(stables) <= 1:
        return []  # chỉ có một kênh -> không có gì để chuyển
    return [{k: c[k] for k in ("tag", "channel", "kind", "version", "updated")} for c in stables + pre]


async def _hub_version_for_digest(client: httpx.AsyncClient, repo: str, digests: list[str]) -> str:
    """
    Image dùng tag chung (latest, full...) không ghi phiên bản -> tìm tag có phiên bản (vd v0.147.0-noble-full)
    trỏ cùng digest trên Docker Hub (API của Hub, không tốn lượt pull). Trả về "v0.147.0" hoặc "".
    """
    want = {d for d in digests if d}
    if not want:
        return ""
    url = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&ordering=last_updated"
    best: Optional[tuple[tuple[int, ...], str]] = None
    try:
        for _page in range(2):
            r = await client.get(url)
            if r.status_code != 200:
                break
            body = r.json()
            for t in body.get("results") or []:
                if t.get("digest") not in want:
                    continue
                parsed = _parse_pinned_tag(str(t.get("name") or ""))
                if parsed and not parsed["is_pre"]:
                    cand = (parsed["nums"], f"{parsed['prefix']}{parsed['ver_str']}")
                    if best is None or cand[0] > best[0]:
                        best = cand
            url = body.get("next") or ""
            if best or not url:
                break
    except Exception:
        return ""
    return best[1] if best else ""


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
            # HEAD trước: Docker Hub không tính HEAD vào hạn mức pull. Nếu digest khớp bản local thì dừng ở đây.
            head_digest = ""
            try:
                head = await _registry_request(
                    client, manifest_url, MANIFEST_ACCEPT, token_cache, scope_key, method="HEAD"
                )
                if head.status_code == 200:
                    head_digest = head.headers.get("docker-content-digest", "").strip()
            except Exception:
                head_digest = ""
            if head_digest and head_digest in local_digests:
                resp = None
                result["remote_digest"] = head_digest
                remote_digest = head_digest
            else:
                resp = await _registry_request(
                    client, manifest_url, MANIFEST_ACCEPT, token_cache, scope_key
                )
            if resp is None:
                pass
            elif resp.status_code == 200:
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

    # Phiên bản thật của image đang chạy khi tag là chữ chung (latest...) / nhãn chỉ là của hệ điều hành gốc
    if registry_ok_for_hub := (registry == "registry-1.docker.io"):
        if current_version.lower() in GENERIC_VERSIONS and local_digests:
            resolved = await _hub_version_for_digest(client, repo, local_digests)
            if resolved:
                current_version = resolved
                result["current_version"] = resolved
                if not result.get("has_update"):
                    result["remote_version"] = resolved

    # Kênh phát hành (latest / beta...) cho app chạy theo tag kênh
    if not pinned_info and channel_format(tag):
        try:
            result["channels"] = json.dumps(
                await _detect_channels(client, registry, repo, tag, token_cache, scope_key)
            )
        except Exception as exc:
            logger.warning("Channel detection for %s failed: %s", name, exc)

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

                # Phiên bản từ nhãn (bỏ chữ chung chung và nhãn thừa hưởng của hệ điều hành gốc);
                # không có thì tìm tag có phiên bản cùng digest trên Docker Hub
                found_real_ver = version_from_labels(remote_labels)
                if not found_real_ver and registry_ok_for_hub and remote_digest:
                    found_real_ver = await _hub_version_for_digest(client, repo, [remote_digest])

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
