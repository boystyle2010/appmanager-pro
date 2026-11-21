#!/usr/bin/env python3
"""
Tự động kiểm tra & nâng các thành phần cốt lõi của AppManager Pro, rồi viết changelog.

  python scripts/auto_update.py check
      Tìm bản mới của: base image (Dockerfile), thư viện Python (requirements.txt), thư viện giao diện (npm).
      Nếu có thay đổi: sửa file, tăng số bản vá, thêm mục mới vào CHANGELOG.md (kiểu "Component & Version Matrix"),
      ghi danh sách file đổi vào release/changed_files.txt và thông tin vào $GITHUB_OUTPUT.

  python scripts/auto_update.py integrity --image ghcr.io/o/r --digest sha256:... --version 0.5.1
      Chèn mục "Package Integrity" (có digest) vào CHANGELOG.md và ghi release/body.md cho GitHub Release.

Quy tắc an toàn: chỉ nâng trong cùng major; với bản 0.x chỉ nâng bản vá (0.115.x -> 0.115.y).
"""
from __future__ import annotations

import argparse
import base64  # noqa: F401  (dùng ở signed_commit)
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "requirements.txt"
DOCKERFILE = ROOT / "Dockerfile"
VENDOR = ROOT / "scripts/fetch_vendor.py"
HTML_FILES = [ROOT / "app/templates/index.html", ROOT / "app/templates/auth.html"]
VERSION_FILE = ROOT / "app/core/docker_client.py"
CHANGELOG = ROOT / "CHANGELOG.md"
OUT_DIR = ROOT / "release"
PY_TARGET = (3, 12)

PY_NAMES = {
    "fastapi": "FastAPI", "uvicorn": "Uvicorn", "docker": "Docker SDK", "ruamel.yaml": "ruamel.yaml",
    "argon2-cffi": "Argon2", "itsdangerous": "itsdangerous", "jinja2": "Jinja2",
    "python-multipart": "python-multipart", "httpx": "HTTPX", "apscheduler": "APScheduler",
}
NPM_LIBS = {  # gói npm -> (tên hiển thị, regex bắt phiên bản trong fetch_vendor.py)
    "alpinejs": ("Alpine.js", r"alpinejs@(\d+\.\d+\.\d+)"),
    "tailwindcss": ("Tailwind CSS", r"cdn\.tailwindcss\.com/(\d+\.\d+\.\d+)"),
    "marked": ("marked", r"marked@(\d+\.\d+\.\d+)"),
    "dompurify": ("DOMPurify", r"dompurify@(\d+\.\d+\.\d+)"),
}

UA = {"User-Agent": "AppManager-Pro-AutoUpdate"}


# ───────────────────────────── tiện ích phiên bản ─────────────────────────────
def vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def is_stable(v: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+){1,3}", v))


def pick_newer(current: str, candidates: list[str]) -> str:
    """Bản mới nhất được phép nâng: cùng major; nếu major = 0 thì cùng cả minor (chỉ nâng bản vá)."""
    cur = vkey(current)
    ok = []
    for c in candidates:
        if not is_stable(c):
            continue
        k = vkey(c)
        if k[0] != cur[0]:
            continue
        if cur[0] == 0 and k[:2] != cur[:2]:
            continue
        ok.append(c)
    best = max(ok, key=vkey, default=current)
    return best if vkey(best) > cur else current


def fetch_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


# ───────────────────────────── nguồn phiên bản ─────────────────────────────
def pypi_versions(name: str, fetch=None) -> list[str]:
    fetch = fetch or fetch_json
    data = fetch(f"https://pypi.org/pypi/{name}/json")
    try:
        from packaging.specifiers import SpecifierSet
    except Exception:
        SpecifierSet = None  # noqa: N806
    out = []
    for ver, files in data.get("releases", {}).items():
        if not files or all(f.get("yanked") for f in files):
            continue
        req = files[0].get("requires_python")
        if req and SpecifierSet:
            try:
                if not SpecifierSet(req).contains(f"{PY_TARGET[0]}.{PY_TARGET[1]}.0"):
                    continue
            except Exception:
                pass
        out.append(ver)
    return out


def npm_versions(pkg: str, fetch=None) -> list[str]:
    fetch = fetch or fetch_json
    return list(fetch(f"https://registry.npmjs.org/{pkg}")["versions"].keys())


def docker_tags(repo: str, name_filter: str, fetch=None) -> list[str]:
    fetch = fetch or fetch_json
    url = f"https://hub.docker.com/v2/repositories/library/{repo}/tags?name={name_filter}&page_size=100&ordering=last_updated"
    return [r["name"] for r in fetch(url).get("results", [])]


# ───────────────────────────── các bước kiểm tra ─────────────────────────────
def check_python_packages(fetch=None) -> list[dict]:
    changes = []
    lines = REQ.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]+\])?==([0-9][0-9.]*)\s*$", line.strip())
        if not m:
            new_lines.append(line)
            continue
        name, extras, cur = m.group(1), m.group(2) or "", m.group(3)
        try:
            new = pick_newer(cur, pypi_versions(name, fetch))
        except Exception as exc:
            print(f"WARN PyPI {name}: {exc}")
            new = cur
        changes.append({"group": "python", "id": name.lower(), "name": PY_NAMES.get(name.lower(), name), "old": cur, "new": new})
        new_lines.append(f"{name}{extras}=={new}")
    REQ.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return changes


def check_npm_libs(fetch=None) -> list[dict]:
    texts = {f: f.read_text(encoding="utf-8") for f in [VENDOR, *HTML_FILES]}
    changes = []
    for pkg, (disp, pattern) in NPM_LIBS.items():
        m = re.search(pattern, texts[VENDOR])
        if not m:
            continue
        cur = m.group(1)
        try:
            new = pick_newer(cur, npm_versions(pkg, fetch))
        except Exception as exc:
            print(f"WARN npm {pkg}: {exc}")
            new = cur
        if new != cur:
            for f in texts:
                texts[f] = re.sub(pattern.replace(r"(\d+\.\d+\.\d+)", re.escape(cur)), lambda mo: mo.group(0).replace(cur, new), texts[f])
        changes.append({"group": "frontend", "id": pkg, "name": disp, "old": cur, "new": new})
    for f, t in texts.items():
        f.write_text(t, encoding="utf-8")
    return changes


def check_base_images(fetch=None) -> list[dict]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    changes = []

    def bump(repo: str, suffix: str, label: str, keep_minor: bool, text: str) -> str:
        m = re.search(rf"{repo}:(\d+(?:\.\d+){{0,2}}){re.escape(suffix)}\b", text)
        if not m:
            return text
        cur_tag = m.group(1)
        parts = cur_tag.split(".")
        prefix = ".".join(parts[: 2 if keep_minor else 1])
        try:
            names = docker_tags(repo, prefix + ".", fetch)
        except Exception as exc:
            print(f"WARN Docker Hub {repo}: {exc}")
            names = []
        cands = []
        for n in names:
            mm = re.fullmatch(rf"({re.escape(prefix)}\.\d+(?:\.\d+)?){re.escape(suffix)}", n)
            if mm and len(mm.group(1).split(".")) == (3 if keep_minor else 3):
                cands.append(mm.group(1))
        full_cur = cur_tag if len(parts) == 3 else None
        best = max(cands, key=vkey, default=None)
        new_tag = cur_tag
        if best and (full_cur is None or vkey(best) > vkey(full_cur)):
            new_tag = best
        changes.append({"group": "base", "id": repo, "name": label, "old": cur_tag if full_cur else f"{cur_tag} (floating)", "new": new_tag})
        return text.replace(f"{repo}:{cur_tag}{suffix}", f"{repo}:{new_tag}{suffix}")

    text = bump("python", "-slim", "Python Base Image", True, text)
    text = bump("docker", "-cli", "Docker CLI", False, text)
    DOCKERFILE.write_text(text, encoding="utf-8")
    return changes


# ───────────────────────────── changelog ─────────────────────────────
def read_app_version() -> str:
    m = re.search(r'APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("Không tìm thấy APP_VERSION trong docker_client.py")
    return m.group(1)


def bump_patch(v: str) -> str:
    a, b, c = (int(x) for x in v.split("."))
    return f"{a}.{b}.{c + 1}"


def _fmt(item: dict, code_prefix: str = "") -> str:
    old = item["old"].replace(" (floating)", "")
    if item["old"].split(" ")[0] == item["new"] and "floating" not in item["old"]:
        return f"`{code_prefix}{item['new']}`"
    return f"`{code_prefix}{old}` ➡️ `{code_prefix}{item['new']}`"


def git_other_changes() -> list[str]:
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True, cwd=ROOT)
        rng = f"{tag.stdout.strip()}..HEAD" if tag.returncode == 0 and tag.stdout.strip() else "HEAD"
        log = subprocess.run(["git", "log", rng, "--no-merges", "--pretty=%s", "-n", "30"], capture_output=True, text=True, cwd=ROOT).stdout
    except Exception:
        return []
    out = []
    for s in log.splitlines():
        s = s.strip()
        if not s or re.match(r"^(chore\((deps|release)\)|chore: release)", s):
            continue
        s = re.sub(r"^(feat|fix|perf|refactor|docs|ci|chore|style|test)(\([^)]*\))?!?:\s*", "", s)
        out.append(s[:1].upper() + s[1:])
    return out[:12]


def build_section(version: str, prev: str, changes: list[dict], others: list[str], date: str) -> str:
    base = [c for c in changes if c["group"] == "base"]
    py = [c for c in changes if c["group"] == "python"]
    fe = [c for c in changes if c["group"] == "frontend"]
    lines = [f"## {version}", "", f"*Released: {date}*", "", "### 📦 Component & Version Matrix", ""]
    lines.append(f"- **App Release:** Bumped from `v{prev}` ➡️ `v{version}`")
    lines.append("- **Supported Architectures:** `linux/amd64` (x86_64) & `linux/arm64` (ARM64) *(Multi-arch GHCR Image)*")
    for b in base:
        lines.append(f"- **{b['name']}:** {_fmt(b, b['id'] + ' ')}")
    if py:
        lines.append("- **Core Python Stack:** " + " • ".join(f"{c['name']} {_fmt(c)}" if c['old'] != c['new'] else f"`{c['name']} {c['new']}`" for c in py))
    if fe:
        lines.append("- **Frontend Libraries:** " + " • ".join(f"{c['name']} {_fmt(c)}" if c['old'] != c['new'] else f"`{c['name']} {c['new']}`" for c in fe))
    lines += ["", "### 🚀 What's Changed", ""]
    bumped = [c for c in changes if c["old"].split(" ")[0] != c["new"] or "floating" in c["old"]]
    for c in bumped:
        lines.append(f"- Upgraded **{c['name']}** to `{c['new']}`.")
    for o in others:
        lines.append(f"- {o}")
    if not bumped and not others:
        lines.append("- Maintenance release.")
    return "\n".join(lines).rstrip() + "\n"


def insert_into_changelog(section: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n"
    if text.startswith("# Changelog"):
        head, _, rest = text.partition("\n")
        new = head + "\n\n" + section + "\n" + rest.lstrip("\n")
    else:
        new = "# Changelog\n\n" + section + "\n" + text
    CHANGELOG.write_text(new, encoding="utf-8")


def set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    print(f"{key}={value}")


def cmd_check(args) -> int:
    changes = check_base_images() + check_python_packages() + check_npm_libs()
    bumped = [c for c in changes if c["old"].split(" ")[0] != c["new"] or "floating" in c["old"]]
    force = os.environ.get("FORCE_RELEASE", "").lower() == "true"
    if not bumped and not force:
        set_output("changed", "false")
        return 0
    prev = read_app_version()
    version = bump_patch(prev)
    vt = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(re.sub(r'APP_VERSION\s*=\s*"\d+\.\d+\.\d+"', f'APP_VERSION = "{version}"', vt, count=1), encoding="utf-8")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    section = build_section(version, prev, changes, git_other_changes(), date)
    insert_into_changelog(section)
    OUT_DIR.mkdir(exist_ok=True)
    files = [REQ, DOCKERFILE, VENDOR, *HTML_FILES, VERSION_FILE, CHANGELOG]
    (OUT_DIR / "changed_files.txt").write_text("\n".join(str(f.relative_to(ROOT)) for f in files) + "\n", encoding="utf-8")
    set_output("changed", "true")
    set_output("version", version)
    set_output("prev_version", prev)
    set_output("summary", "; ".join(f"{c['name']} {c['old']} -> {c['new']}" for c in bumped)[:900] or "maintenance")
    return 0


def cmd_integrity(args) -> int:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(args.version)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        raise SystemExit(f"Không thấy mục {args.version} trong CHANGELOG.md")
    section = m.group(0)
    block = (
        "### 🔐 Package Integrity (GHCR Multi-Arch)\n\n"
        f"- **Version Tag:** `{args.image}:{args.version}` (`{args.digest}`)\n"
        f"- **Latest Tag:** `{args.image}:latest`\n"
        f"- **Provenance:** signed by GitHub — verify with `gh attestation verify oci://{args.image}@{args.digest} -R {args.repo}`\n\n"
    )
    if "Package Integrity" in section:
        new_section = re.sub(r"### 🔐 Package Integrity.*?(?=### )", block, section, flags=re.S)
    else:
        new_section = section.replace("### 🚀 What's Changed", block + "### 🚀 What's Changed", 1)
    CHANGELOG.write_text(text.replace(section, new_section, 1), encoding="utf-8")
    OUT_DIR.mkdir(exist_ok=True)
    body = re.sub(r"^## .*\n+", "", new_section, count=1)  # Release đã có tiêu đề riêng
    (OUT_DIR / "body.md").write_text(body.strip() + "\n", encoding="utf-8")
    (OUT_DIR / "changed_files.txt").write_text("CHANGELOG.md\n", encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("integrity")
    p.add_argument("--image", required=True)
    p.add_argument("--digest", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--repo", required=True)
    args = ap.parse_args()
    return cmd_check(args) if args.cmd == "check" else cmd_integrity(args)


if __name__ == "__main__":
    sys.exit(main())
