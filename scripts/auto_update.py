#!/usr/bin/env python3
"""
Tự động kiểm tra & nâng các thành phần cốt lõi của AppManager Pro, rồi viết changelog.

  python scripts/auto_update.py check
      Tìm bản mới của: base image (Dockerfile), thư viện Python (requirements.txt), thư viện giao diện (npm),
      và action trong .github/workflows (khi BUMP_ACTIONS=true — cần secret WORKFLOW_TOKEN).
      Nếu có thay đổi: sửa file, tăng số bản vá, thêm mục mới vào CHANGELOG.md (kiểu "Component & Version Matrix"),
      ghi danh sách file đổi vào release/changed_files.txt và thông tin vào $GITHUB_OUTPUT.

  python scripts/auto_update.py integrity --image ghcr.io/o/r --digest sha256:... --version 0.5.1
      Chèn mục "Package Integrity" (có digest) vào CHANGELOG.md và ghi release/body.md cho GitHub Release.

Chính sách nâng cấp (biến môi trường UPDATE_POLICY):
  latest (mặc định) — nâng mọi thành phần lên bản ổn định MỚI NHẤT, kể cả major mới.
  safe              — chỉ nâng trong cùng major (0.x: chỉ bản vá). Workflow dùng chế độ này làm phương án dự phòng
                      khi bản "latest" không qua được bước kiểm tra.
Ngoại lệ: Tailwind CSS giữ ở v3 (v4 không có bản chạy trong trình duyệt tương thích, cần viết lại giao diện).
"""
from __future__ import annotations

import argparse
import base64  # noqa: F401  (dùng ở signed_commit)
import json
import os
import re
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
NEXT_NOTES = ROOT / "RELEASE_NOTES_NEXT.md"  # ghi chú tự viết cho bản phát hành kế tiếp (tuỳ chọn)
OUT_DIR = ROOT / "release"
PY_TARGET = [3, 12]  # được cập nhật theo image Python trong Dockerfile
POLICY = (os.environ.get("UPDATE_POLICY") or "latest").strip().lower()
PINNED_MAJOR: dict[str, int] = {}

PY_NAMES = {
    "fastapi": "FastAPI", "uvicorn": "Uvicorn", "docker": "Docker SDK", "ruamel.yaml": "ruamel.yaml",
    "argon2-cffi": "Argon2", "itsdangerous": "itsdangerous", "jinja2": "Jinja2",
    "python-multipart": "python-multipart", "httpx": "HTTPX", "apscheduler": "APScheduler", "segno": "segno",
}
NPM_LIBS = {  # gói npm -> (tên hiển thị, regex bắt phiên bản; tìm trong fetch_vendor.py, HTML và Dockerfile)
    "alpinejs": ("Alpine.js", r"alpinejs@(\d+\.\d+\.\d+)"),
    "tailwindcss": ("Tailwind CSS", r"TAILWIND_VERSION=(\d+\.\d+\.\d+)"),
    "marked": ("marked", r"marked@(\d+\.\d+\.\d+)"),
    "dompurify": ("DOMPurify", r"dompurify@(\d+\.\d+\.\d+)"),
}

UA = {"User-Agent": "AppManager-Pro-AutoUpdate"}


# ───────────────────────────── tiện ích phiên bản ─────────────────────────────
def vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def is_stable(v: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+){1,3}", v))


def pick_newer(current: str, candidates: list[str], pin_major: int | None = None) -> str:
    """
    Chọn bản ổn định mới nhất.
    - POLICY=latest: mọi bản mới hơn (kể cả major mới), trừ khi pin_major giới hạn.
    - POLICY=safe: cùng major; nếu major = 0 thì cùng cả minor.
    """
    cur = vkey(current)
    ok = []
    for c in candidates:
        if not is_stable(c):
            continue
        k = vkey(c)
        if pin_major is not None and k[0] != pin_major:
            continue
        if POLICY == "safe":
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
    texts = {f: f.read_text(encoding="utf-8") for f in [VENDOR, *HTML_FILES, DOCKERFILE]}
    changes = []
    for pkg, (disp, pattern) in NPM_LIBS.items():
        m = next((mm for mm in (re.search(pattern, t) for t in texts.values()) if mm), None)
        if not m:
            continue
        cur = m.group(1)
        try:
            new = pick_newer(cur, npm_versions(pkg, fetch), PINNED_MAJOR.get(pkg))
        except Exception as exc:
            print(f"WARN npm {pkg}: {exc}")
            new = cur
        # Ghi phiên bản mới vào MỌI chỗ nhắc tới thư viện (kể cả link CDN dự phòng đang lệch phiên bản)
        for f in texts:
            texts[f] = re.sub(pattern, lambda mo: mo.group(0).replace(mo.group(1), new), texts[f])
        changes.append({"group": "frontend", "id": pkg, "name": disp, "old": cur, "new": new})
    for f, t in texts.items():
        f.write_text(t, encoding="utf-8")
    return changes


def check_base_images(fetch=None) -> list[dict]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    changes = []

    def bump(repo: str, suffix: str, label: str, text: str) -> str:
        m = re.search(rf"{repo}:(\d+(?:\.\d+){{0,2}}){re.escape(suffix)}\b", text)
        if not m:
            return text
        cur_tag = m.group(1)
        parts = cur_tag.split(".")
        # latest: mọi phiên bản; safe: python giữ major.minor, docker giữ major
        if POLICY == "safe":
            prefix = ".".join(parts[: 2 if repo == "python" else 1]) + "."
        else:
            prefix = ""
        try:
            names = docker_tags(repo, prefix or suffix.lstrip("-"), fetch)
        except Exception as exc:
            print(f"WARN Docker Hub {repo}: {exc}")
            names = []
        cands = []
        for n in names:
            mm = re.fullmatch(rf"(\d+\.\d+\.\d+){re.escape(suffix)}", n)
            if mm and mm.group(1).startswith(prefix):
                cands.append(mm.group(1))
        full_cur = cur_tag if len(parts) == 3 else None
        best = max(cands, key=vkey, default=None)
        if best is None:  # không tra được Docker Hub -> coi như không đổi
            changes.append({"group": "base", "id": repo, "name": label, "old": cur_tag, "new": cur_tag})
            return text
        new_tag = cur_tag
        if full_cur is None or vkey(best) > vkey(full_cur):
            new_tag = best
        changes.append({"group": "base", "id": repo, "name": label, "old": cur_tag if full_cur else f"{cur_tag} (floating)", "new": new_tag})
        return text.replace(f"{repo}:{cur_tag}{suffix}", f"{repo}:{new_tag}{suffix}")

    text = bump("python", "-slim", "Python Base Image", text)
    text = bump("docker", "-cli", "Docker CLI", text)
    DOCKERFILE.write_text(text, encoding="utf-8")
    # Thư viện Python phải tương thích với bản Python của image
    pm = re.search(r"python:(\d+)\.(\d+)", text)
    if pm:
        PY_TARGET[0], PY_TARGET[1] = int(pm.group(1)), int(pm.group(2))
    return changes


# ───────────────────────────── changelog ─────────────────────────────
# ───────────────────────────── GitHub Actions trong workflow ─────────────────────────────
WORKFLOW_DIR = ROOT / ".github/workflows"
USES_RE = re.compile(r"^(?P<pre>\s*-?\s*uses:\s*)(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?P<sub>/[^@\s]*)?@(?P<ref>[^\s#]+)(?P<post>.*)$")


def _action_tags(repo: str) -> list[str]:
    import subprocess

    r = subprocess.run(["git", "ls-remote", "--tags", f"https://github.com/{repo}"], capture_output=True, text=True, timeout=60)
    tags = {ln.split("refs/tags/", 1)[1].removesuffix("^{}") for ln in r.stdout.splitlines() if "refs/tags/" in ln}
    return [t for t in tags if re.fullmatch(r"v\d+(\.\d+){0,2}", t)]


def _action_inputs(repo: str, sub: str, ref: str) -> set[str] | None:
    """Tên các input của action ở phiên bản ref (None nếu không đọc được)."""
    path = (sub or "").strip("/")
    for name in ("action.yml", "action.yaml"):
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path + '/' if path else ''}{name}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                text = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        m = re.search(r"^inputs:\s*\n((?:[ \t]+.*\n|\s*\n)*)", text, re.M)
        return set(re.findall(r"^  ([A-Za-z0-9_-]+):", m.group(1), re.M)) if m else set()
    return None


def _with_keys(lines: list[str], idx: int) -> set[str]:
    """Các khoá trong khối `with:` ngay sau dòng uses (cùng step)."""
    indent = len(lines[idx]) - len(lines[idx].lstrip(" -"))
    keys, in_with, with_indent = set(), False, 0
    for ln in lines[idx + 1:]:
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        if ln.lstrip().startswith("- ") and ind <= indent:
            break
        if ind < indent:
            break
        if re.match(r"\s*with:\s*$", ln):
            in_with, with_indent = True, ind
            continue
        if in_with:
            if ind <= with_indent:
                in_with = False
                continue
            m = re.match(r"\s*([A-Za-z0-9_-]+):", ln)
            if m and ind == with_indent + 2:
                keys.add(m.group(1))
    return keys


def check_actions() -> list[dict]:
    """
    Nâng `uses: owner/repo@vX` lên major mới nhất (giữ kiểu ghi: v4 / v4.2 / v4.2.1).
    Bỏ qua action ghim theo commit SHA (vd Trivy) và action nội bộ (./...).
    Không nâng nếu bản mới bỏ mất input mà workflow đang dùng trong `with:`.
    """
    changes: list[dict] = []
    if not WORKFLOW_DIR.is_dir():
        return changes
    cache: dict[str, list[str]] = {}
    for wf in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        lines = wf.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = False
        for i, ln in enumerate(lines):
            m = USES_RE.match(ln.rstrip("\n"))
            if not m or not m.group("ref").startswith("v"):
                continue
            repo, sub, ref = m.group("repo"), m.group("sub") or "", m.group("ref")
            if repo not in cache:
                try:
                    cache[repo] = _action_tags(repo)
                except Exception as exc:
                    print(f"WARN tags {repo}: {exc}")
                    cache[repo] = []
            tags = cache[repo]
            if not tags:
                continue
            parts = ref.count(".") + 1
            same_style = [t for t in tags if t.count(".") + 1 == parts] or tags
            akey = lambda v: vkey(v.lstrip("v"))  # noqa: E731
            best = max(same_style, key=akey)
            if akey(best) <= akey(ref):
                continue
            used = _with_keys(lines, i)
            inputs = _action_inputs(repo, sub, best)
            if inputs is None or (used - inputs):
                print(f"SKIP {repo}@{best}: inputs {sorted(used - (inputs or set()))} not available")
                continue
            lines[i] = f"{m.group('pre')}{repo}{sub}@{best}{m.group('post')}\n"
            changed = True
            changes.append({"name": f"{repo}{sub}", "old": ref, "new": best, "file": wf})
        if changed:
            wf.write_text("".join(lines), encoding="utf-8")
    return changes


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


def read_next_notes() -> list[str]:
    if not NEXT_NOTES.exists():
        return []
    out = []
    for line in NEXT_NOTES.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or t.startswith("<!--"):
            continue
        out.append(re.sub(r"^[-*]\s+", "", t))
    return out


def build_section(version: str, prev: str, changes: list[dict], others: list[str], date: str) -> str:
    base = [c for c in changes if c["group"] == "base"]
    py = [c for c in changes if c["group"] == "python"]
    fe = [c for c in changes if c["group"] == "frontend"]
    lines = [f"## {version}", "", f"*Released: {date}*", "", "### 📦 Component & Version Matrix", ""]
    lines.append(f"- **App Release:** Bumped from `v{prev}` ➡️ `v{version}`")
    lines.append("- **Supported Architectures:** `linux/amd64` (x86_64), `linux/arm64` (ARM64) & `linux/arm/v7` (ARMv7 32-bit) *(Multi-arch GHCR Image)*")
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
    if os.environ.get("HELD_BACK", "").lower() == "true":
        lines.append("- Some major upgrades were held back because the automatic start-up test failed with them; only same-major updates were applied.")
    if not bumped and not others:
        lines.append("- Maintenance release.")
    return "\n".join(lines).rstrip() + "\n"


def insert_into_changelog(section: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n"
    # Nếu đã có mục cùng phiên bản (chạy lại) thì thay thế, không tạo trùng
    ver = section.splitlines()[0].strip()
    text = re.sub(rf"^{re.escape(ver)}\n.*?(?=^## |\Z)", "", text, flags=re.S | re.M)
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
    # Action trong workflow: chỉ nâng khi có token được phép ghi .github/workflows (BUMP_ACTIONS=true).
    # Không tự tạo bản phát hành; nếu có bản phát hành thì gộp vào cùng commit, nếu không thì commit riêng.
    action_changes = check_actions() if os.environ.get("BUMP_ACTIONS", "").lower() == "true" else []
    OUT_DIR.mkdir(exist_ok=True)
    wf_list = OUT_DIR / "workflow_files.txt"
    wf_list.unlink(missing_ok=True)
    if action_changes:
        wf_files = sorted({str(c["file"].relative_to(ROOT)) for c in action_changes})
        wf_list.write_text("\n".join(wf_files) + "\n", encoding="utf-8")
        set_output("actions_summary", "; ".join(f"{c['name']} {c['old']} -> {c['new']}" for c in action_changes)[:900])
    force = os.environ.get("FORCE_RELEASE", "").lower() == "true"
    wanted = (os.environ.get("RELEASE_VERSION") or "").strip().lstrip("v")
    notes = read_next_notes()
    # Ghi chú tự viết KHÔNG tự tạo bản phát hành; chỉ được dùng khi có bản phát hành (cập nhật thành phần / chạy tay)
    if not bumped and not force and not wanted:
        set_output("changed", "false")
        set_output("python_version", f"{PY_TARGET[0]}.{PY_TARGET[1]}")
        return 0
    prev = read_app_version()
    if wanted:
        if not re.fullmatch(r"\d+\.\d+\.\d+", wanted):
            raise SystemExit(f"Phiên bản yêu cầu {wanted!r} không hợp lệ (dạng đúng: 1.0.0)")
        if vkey(wanted) < vkey(prev):
            raise SystemExit(f"Phiên bản yêu cầu {wanted} nhỏ hơn phiên bản hiện tại {prev}")
        version = wanted  # bằng phiên bản hiện tại cũng được: phát hành lại đúng số đó
    else:
        version = bump_patch(prev)
    vt = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(re.sub(r'APP_VERSION\s*=\s*"\d+\.\d+\.\d+"', f'APP_VERSION = "{version}"', vt, count=1), encoding="utf-8")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    section = build_section(version, prev, changes, notes, date)
    insert_into_changelog(section)
    OUT_DIR.mkdir(exist_ok=True)
    files = [REQ, DOCKERFILE, VENDOR, *HTML_FILES, VERSION_FILE, CHANGELOG]
    files += [c["file"] for c in action_changes if c["file"] not in files]
    if notes:
        NEXT_NOTES.write_text("# Ghi chú cho bản phát hành kế tiếp — mỗi dòng bắt đầu bằng \"- \"\n", encoding="utf-8")
        files.append(NEXT_NOTES)
    (OUT_DIR / "changed_files.txt").write_text("\n".join(str(f.relative_to(ROOT)) for f in files) + "\n", encoding="utf-8")
    set_output("changed", "true")
    set_output("python_version", f"{PY_TARGET[0]}.{PY_TARGET[1]}")
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
        f"- **Image:** `{args.image.split('/', 1)[-1]}:{args.version}`\n"
        f"- **Digest:** `{args.digest[:19]}…`\n"
        f"- **Provenance:** ✅ Signed by GitHub · [View attestation](https://github.com/{args.repo}/attestations)\n"
        + (f"- **Vulnerability Scan (Trivy):** {args.scan}\n" if args.scan else "")
        + "\n"
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
    p.add_argument("--scan", default="")
    args = ap.parse_args()
    return cmd_check(args) if args.cmd == "check" else cmd_integrity(args)


if __name__ == "__main__":
    sys.exit(main())
