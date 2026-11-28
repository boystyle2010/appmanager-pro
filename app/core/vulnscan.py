"""
Quét lỗ hổng image từng app bằng Trivy (0.26) — tuỳ chọn, mặc định TẮT.

- Cài đặt (Quản trị bấm "Cài Trivy"): binary lưu trong `<data>/trivy/trivy`, cơ sở dữ liệu lỗ hổng trong `<data>/trivy/cache`.
  amd64 / arm64: lấy binary từ image chính thức `aquasec/trivy` qua Docker (không cần GitHub; đổi bằng biến `TRIVY_IMAGE`).
  armv7 (image không có bản ARM 32-bit): tải `trivy_<v>_Linux-ARM.tar.gz` từ GitHub Releases + kiểm SHA-256 theo checksums.txt.
- Quét: `trivy image --image-src docker <image ID>` = đúng image app đang chạy (đọc qua Docker, không tải lại từ registry).
  Chạy lần lượt (khoá), bỏ qua nếu image không đổi và đã quét trong 24 giờ (trừ khi bấm quét lại).
- Kết quả bảng `vuln_scans` (mỗi app 1 dòng): số lỗi theo mức, số lỗi đã có bản vá, tối đa 500 lỗi chi tiết.
- Thông báo sự kiện `vuln_found` khi một lần quét tìm thấy lỗi MỚI (so với lần trước) ở các mức đã chọn.
- Lịch: hằng ngày / hằng tuần (giờ chọn) + tuỳ chọn quét lại app ngay sau khi cập nhật.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
from typing import Any, Optional

from app.core.database import DATA_DIR, get_connection, get_setting, set_setting

logger = logging.getLogger(__name__)

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
SETTING = "vuln_settings"
INFO_SETTING = "vuln_trivy"
DEFAULT = {"enabled": False, "schedule": "daily", "time": "04:40", "weekday": 6, "after_update": True,
           "severities": ["CRITICAL", "HIGH"], "fixable_only": False, "card_badge": True}
ACK_SETTING = "vuln_ack"   # {container: {"keys": ["CVE|pkg", ...], "at": ts, "by": user}} — lỗi đã "chấp nhận"
MAX_FINDINGS = 500
RESCAN_AFTER = 24 * 3600
TRIVY_DIR = DATA_DIR / "trivy"
BIN = TRIVY_DIR / "trivy"
CACHE = TRIVY_DIR / "cache"

_lock = threading.Lock()
state: dict[str, Any] = {"running": False, "current": "", "done": 0, "total": 0, "started": 0, "finished": 0,
                         "installing": False, "install_error": "", "install_step": ""}


# ---------------------------------------------------------------- cài đặt
def settings() -> dict[str, Any]:
    try:
        data = json.loads(get_setting(SETTING, "") or "{}")
    except Exception:
        data = {}
    out = {**DEFAULT, **(data if isinstance(data, dict) else {})}
    out["severities"] = [s for s in out.get("severities") or [] if s in SEVERITIES] or list(DEFAULT["severities"])
    return out


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    cur = settings()
    if "enabled" in data:
        cur["enabled"] = bool(data["enabled"])
    if data.get("schedule") in ("daily", "weekly", "manual"):
        cur["schedule"] = data["schedule"]
    if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(data.get("time") or "")):
        cur["time"] = data["time"]
    if "weekday" in data:
        cur["weekday"] = max(0, min(6, int(data["weekday"])))
    for k in ("after_update", "fixable_only", "card_badge"):
        if k in data:
            cur[k] = bool(data[k])
    if "severities" in data:
        sev = [s for s in data["severities"] or [] if s in SEVERITIES]
        if not sev:
            raise ValueError("Choose at least one severity")
        cur["severities"] = sev
    set_setting(SETTING, json.dumps(cur))
    return cur


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m.startswith("armv7") or m.startswith("armv6") or m == "armhf":
        return "arm"
    return m


def installed() -> bool:
    return BIN.is_file() and os.access(BIN, os.X_OK)


def trivy_info() -> dict[str, Any]:
    try:
        info = json.loads(get_setting(INFO_SETTING, "{}") or "{}")
    except Exception:
        info = {}
    info["installed"] = installed()
    info["arch"] = _arch()
    if info["installed"]:
        try:
            info["size"] = BIN.stat().st_size + sum(f.stat().st_size for f in CACHE.rglob("*") if f.is_file())
        except OSError:
            pass
    return info


def _run_version() -> dict[str, str]:
    out = subprocess.run([str(BIN), "--version", "--cache-dir", str(CACHE)], capture_output=True, text=True, timeout=60).stdout
    ver = re.search(r"^Version:\s*(\S+)", out, re.M)
    db = re.search(r"Vulnerability DB:.*?UpdatedAt:\s*(\S+ \S+)", out, re.S)
    return {"version": ver.group(1) if ver else "", "db_updated": (db.group(1)[:16] if db else "")}


def _from_image() -> str:
    """amd64 / arm64: chép binary từ image aquasec/trivy (pull qua Docker, xoá image sau khi chép)."""
    from app.core.docker_client import get_docker_client
    ref = os.getenv("TRIVY_IMAGE", "aquasec/trivy:latest")
    client = get_docker_client()
    state["install_step"] = "pull"
    repo, _, tag = ref.rpartition(":") if ":" in ref.rsplit("/", 1)[-1] else (ref, "", "latest")
    image = client.images.pull(repo, tag=tag or "latest")
    state["install_step"] = "extract"
    cont = client.containers.create(image.id, entrypoint=["/bin/true"])
    try:
        stream, _ = cont.get_archive("/usr/local/bin/trivy")
        data = io.BytesIO(b"".join(stream))
    finally:
        cont.remove(force=True)
    with tarfile.open(fileobj=data) as tar:
        member = tar.getmember("trivy")
        src = tar.extractfile(member)
        tmp = BIN.with_suffix(".new")
        with open(tmp, "wb") as fh:
            shutil.copyfileobj(src, fh)
    os.chmod(tmp, 0o755)
    os.replace(tmp, BIN)
    try:  # ~200 MB, không cần nữa (đã có binary)
        client.images.remove(image.id, force=False)
    except Exception:
        pass
    return ref


def _from_github() -> str:
    """armv7: binary Linux-ARM từ GitHub Releases, kiểm SHA-256 theo file checksums của chính bản đó."""
    import httpx
    with httpx.Client(timeout=120, follow_redirects=True) as c:
        rel = c.get("https://api.github.com/repos/aquasecurity/trivy/releases/latest", headers={"Accept": "application/vnd.github+json"})
        rel.raise_for_status()
        tag = rel.json()["tag_name"]
        ver = tag.lstrip("v")
        name = f"trivy_{ver}_Linux-ARM.tar.gz"
        base = f"https://github.com/aquasecurity/trivy/releases/download/{tag}/"
        state["install_step"] = "download"
        sums = c.get(base + f"trivy_{ver}_checksums.txt")
        sums.raise_for_status()
        want = next((ln.split()[0] for ln in sums.text.splitlines() if ln.strip().endswith(name)), "")
        blob = c.get(base + name)
        blob.raise_for_status()
    if not want or hashlib.sha256(blob.content).hexdigest() != want:
        raise RuntimeError("Checksum of the downloaded Trivy does not match — not installed")
    with tarfile.open(fileobj=io.BytesIO(blob.content)) as tar:
        src = tar.extractfile(tar.getmember("trivy"))
        tmp = BIN.with_suffix(".new")
        with open(tmp, "wb") as fh:
            shutil.copyfileobj(src, fh)
    os.chmod(tmp, 0o755)
    os.replace(tmp, BIN)
    return base + name


def install() -> dict[str, Any]:
    """Cài / cập nhật Trivy + tải cơ sở dữ liệu lỗ hổng. Chạy trong luồng nền (gọi từ API)."""
    if state["installing"]:
        return trivy_info()
    state.update(installing=True, install_error="", install_step="start")
    try:
        TRIVY_DIR.mkdir(parents=True, exist_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        source = _from_github() if _arch() == "arm" else _from_image()
        state["install_step"] = "database"
        r = subprocess.run([str(BIN), "image", "--download-db-only", "--cache-dir", str(CACHE), "--quiet"],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "Could not download the vulnerability database").strip()[-300:])
        info = {**_run_version(), "source": source, "installed_at": int(time.time())}
        set_setting(INFO_SETTING, json.dumps(info))
        return trivy_info()
    except Exception as exc:
        logger.exception("trivy install failed")
        state["install_error"] = str(exc)[:300]
        return trivy_info()
    finally:
        state.update(installing=False, install_step="")


def uninstall() -> None:
    shutil.rmtree(TRIVY_DIR, ignore_errors=True)
    set_setting(INFO_SETTING, "{}")


# ---------------------------------------------------------------- kết quả
def _ensure_table() -> None:
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS vuln_scans (
            container TEXT PRIMARY KEY, image TEXT, image_id TEXT, scanned_at INTEGER, duration REAL,
            counts TEXT, fixable TEXT, findings TEXT, error TEXT DEFAULT '')""")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vuln_scans)").fetchall()}
        if "allkeys" not in cols:  # 0.26.1: khoá của MỌI lỗi (findings chỉ giữ 500 lỗi nặng nhất) để chấp nhận / báo lỗi mới cho đúng
            conn.execute("ALTER TABLE vuln_scans ADD COLUMN allkeys TEXT DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


def acks() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(get_setting(ACK_SETTING, "") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _row_keys(r) -> list[tuple[str, str, bool]]:
    """[(severity, "CVE|pkg", có bản vá)] của MỌI lỗi; bản quét cũ (chưa có allkeys) thì lấy từ findings."""
    raw = r["allkeys"] if "allkeys" in r.keys() else ""
    if raw:
        out = []
        for x in json.loads(raw):
            sev, fx, key = x.split("|", 2)
            out.append((sev, key, fx == "1"))
        return out
    return [(f["severity"], f"{f['id']}|{f['pkg']}", bool(f["fixed"])) for f in json.loads(r["findings"] or "[]")]


def results(with_findings: bool = False) -> dict[str, dict[str, Any]]:
    """Kết quả mọi app. `open` / `open_fixable` = số lỗi CHƯA chấp nhận theo mức (huy hiệu + thông báo dùng số này),
    `accepted` = số lỗi hiện có đã được chấp nhận, `ack_at` / `ack_by` = lúc / người chấp nhận."""
    _ensure_table()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM vuln_scans").fetchall()
    finally:
        conn.close()
    ak = acks()
    out = {}
    for r in rows:
        d = {"image": r["image"], "image_id": r["image_id"], "scanned_at": r["scanned_at"], "duration": r["duration"],
             "counts": json.loads(r["counts"] or "{}"), "fixable": json.loads(r["fixable"] or "{}"), "error": r["error"] or ""}
        a = ak.get(r["container"]) or {}
        acked = set(a.get("keys") or [])
        if acked:
            op, opf, n = {s: 0 for s in SEVERITIES}, {s: 0 for s in SEVERITIES}, 0
            for sev, key, fx in _row_keys(r):
                if key in acked:
                    n += 1
                    continue
                op[sev] = op.get(sev, 0) + 1
                if fx:
                    opf[sev] = opf.get(sev, 0) + 1
            d.update(open=op, open_fixable=opf, accepted=n, ack_at=a.get("at"), ack_by=a.get("by", ""))
        else:
            d.update(open=d["counts"], open_fixable=d["fixable"], accepted=0, ack_at=None, ack_by="")
        if with_findings:
            d["findings"] = json.loads(r["findings"] or "[]")
            for f in d["findings"]:
                f["accepted"] = f"{f['id']}|{f['pkg']}" in acked
        out[r["container"]] = d
    return out


def accept(container: str, user: str = "") -> dict[str, Any]:
    """Chấp nhận mọi lỗi hiện có của app (image của bên thứ ba: chỉ nhà phát triển sửa được). Huy hiệu ẩn tới khi
    lần quét sau thấy lỗi MỚI; lỗi đã chấp nhận vẫn được chấp nhận khi image đổi (theo CVE + gói)."""
    _ensure_table()
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM vuln_scans WHERE container = ?", (container,)).fetchone()
    finally:
        conn.close()
    if not r:
        raise KeyError(container)
    ak = acks()
    keys = set((ak.get(container) or {}).get("keys") or []) | {k for _, k, _ in _row_keys(r)}
    ak[container] = {"keys": sorted(keys), "at": int(time.time()), "by": user}
    set_setting(ACK_SETTING, json.dumps(ak))
    return results().get(container) or {}


def unaccept(container: str) -> dict[str, Any]:
    ak = acks()
    ak.pop(container, None)
    set_setting(ACK_SETTING, json.dumps(ak))
    return results().get(container) or {}


def result(container: str) -> Optional[dict[str, Any]]:
    return results(with_findings=True).get(container)


def _save(container: str, image: str, image_id: str, duration: float, counts: dict, fixable: dict,
          findings: list, error: str = "", allkeys: Optional[list] = None) -> None:
    _ensure_table()
    conn = get_connection()
    try:
        conn.execute("INSERT OR REPLACE INTO vuln_scans (container, image, image_id, scanned_at, duration, counts, fixable, findings, error, allkeys) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (container, image, image_id, int(time.time()), round(duration, 1),
                                                      json.dumps(counts), json.dumps(fixable), json.dumps(findings), error,
                                                      json.dumps(allkeys) if allkeys else ""))
        conn.commit()
    finally:
        conn.close()


def forget(missing: set[str]) -> None:
    """Xoá kết quả của app không còn tồn tại."""
    if not missing:
        return
    conn = get_connection()
    try:
        conn.executemany("DELETE FROM vuln_scans WHERE container = ?", [(m,) for m in missing])
        conn.commit()
    finally:
        conn.close()
    ak = acks()
    if any(m in ak for m in missing):
        set_setting(ACK_SETTING, json.dumps({k: v for k, v in ak.items() if k not in missing}))


def all_keys(items: list[dict[str, Any]]) -> list[str]:
    """Khoá gọn của MỌI lỗi: "MỨC|1 (có bản vá) / 0|CVE|gói" (không trùng)."""
    seen, out = set(), []
    for f in items:
        k = f"{f['severity']}|{1 if f['fixed'] else 0}|{f['id']}|{f['pkg']}"
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def parse_report(data: dict[str, Any], limit: int = MAX_FINDINGS) -> tuple[dict[str, int], dict[str, int], list[dict[str, Any]]]:
    counts = {s: 0 for s in SEVERITIES}
    fixable = {s: 0 for s in SEVERITIES}
    seen, items = set(), []
    for res in data.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            key = (v.get("VulnerabilityID"), v.get("PkgName"), v.get("InstalledVersion"))
            if key in seen:
                continue
            seen.add(key)
            sev = v.get("Severity") if v.get("Severity") in SEVERITIES else "UNKNOWN"
            counts[sev] += 1
            if v.get("FixedVersion"):
                fixable[sev] += 1
            items.append({"id": v.get("VulnerabilityID", ""), "pkg": v.get("PkgName", ""), "installed": v.get("InstalledVersion", ""),
                          "fixed": v.get("FixedVersion", ""), "severity": sev, "title": (v.get("Title") or "")[:200],
                          "url": v.get("PrimaryURL", ""), "target": res.get("Target", "")[:120]})
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    items.sort(key=lambda x: (rank[x["severity"]], 0 if x["fixed"] else 1, x["id"]))
    return counts, fixable, items[:limit] if limit else items


def scan_one(app: dict[str, Any], force: bool = False) -> Optional[dict[str, Any]]:
    """Quét 1 app (đúng image đang chạy). Trả kết quả mới, None nếu bỏ qua (đã quét image này gần đây)."""
    name, image_id = app["name"], app.get("full_image_id") or app.get("image_id") or ""
    prev = results().get(name)
    if not force and prev and prev["image_id"] == image_id and not prev["error"] and time.time() - (prev["scanned_at"] or 0) < RESCAN_AFTER:
        return None
    t0 = time.time()
    cmd = [str(BIN), "image", "--cache-dir", str(CACHE), "--quiet", "--scanners", "vuln", "--format", "json",
           "--image-src", "docker", "--timeout", "15m", image_id or app.get("image", "")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "Trivy failed").strip().splitlines()[-1][:300])
        counts, fixable, items = parse_report(json.loads(r.stdout or "{}"), limit=0)
        _save(name, app.get("image", ""), image_id, time.time() - t0, counts, fixable, items[:MAX_FINDINGS], allkeys=all_keys(items))
    except Exception as exc:
        _save(name, app.get("image", ""), image_id, time.time() - t0, {}, {}, [], str(exc)[:300])
    return result(name)


def _keys(container: str, sev: list[str], fixable_only: bool) -> dict[str, str]:
    """{"CVE|gói": mức} của mọi lỗi hiện có ở các mức đang báo (đọc cả allkeys, không chỉ 500 lỗi lưu chi tiết)."""
    _ensure_table()
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM vuln_scans WHERE container = ?", (container,)).fetchone()
    finally:
        conn.close()
    if not r or r["error"]:
        return {}
    return {k: s for s, k, fx in _row_keys(r) if s in sev and (fx or not fixable_only)}


def scan_apps(names: Optional[list[str]] = None, force: bool = False, notify_new: bool = True) -> dict[str, Any]:
    """Quét nhiều app lần lượt (khoá: chỉ 1 lượt quét một lúc). Gửi MỘT thông báo cho các lỗi mới tìm thấy."""
    if not installed():
        raise RuntimeError("Trivy is not installed")
    if not _lock.acquire(blocking=False):
        return {"busy": True}
    try:
        from app.core.docker_client import list_all_apps
        apps = [a for a in list_all_apps(include_cache=False).get("apps", []) if not names or a["name"] in names]
        if not names:
            forget(set(results()) - {a["name"] for a in apps})
        cfg = settings()
        state.update(running=True, done=0, total=len(apps), started=int(time.time()), current="")
        news = []
        for a in apps:
            state["current"] = a.get("title") or a["name"]
            before = _keys(a["name"], cfg["severities"], cfg["fixable_only"])
            after = scan_one(a, force=force)
            state["done"] += 1
            if after and not after["error"]:
                now = _keys(a["name"], cfg["severities"], cfg["fixable_only"])
                accepted = set((acks().get(a["name"]) or {}).get("keys") or [])
                new = set(now) - set(before) - accepted  # lỗi đã chấp nhận không báo lại
                if new:
                    sev = {s: 0 for s in cfg["severities"]}
                    for k in new:
                        sev[now[k]] += 1
                    news.append({"name": a["name"], "title": a.get("title") or a["name"], "new": len(new), "by_severity": sev})
        if news and notify_new:
            _notify(news)
        return {"scanned": len(apps), "new": news}
    finally:
        state.update(running=False, current="", finished=int(time.time()))
        _lock.release()


def _notify(news: list[dict[str, Any]]) -> None:
    from app.core import notify
    lab = {s: notify.tr("sev_" + s) for s in SEVERITIES}
    lines = []
    for n in news[:20]:
        parts = [f"{c} {lab[s]}" for s, c in n["by_severity"].items() if c]
        lines.append(f"{n['title']}: {', '.join(parts) or n['new']}")
    title = f"{notify.tr('vuln_found')} ({len(news)})"
    notify.notify("vuln_found", title, "\n".join(lines), {"vulns": news})


def summary() -> dict[str, Any]:
    return {"settings": settings(), "trivy": trivy_info(), "state": dict(state), "apps": results()}


# ---------------------------------------------------------------- lịch
def configure(scheduler) -> None:
    from apscheduler.triggers.cron import CronTrigger
    if scheduler.get_job("vuln_scan"):
        scheduler.remove_job("vuln_scan")
    cfg = settings()
    if not cfg["enabled"] or cfg["schedule"] == "manual":
        return
    h, m = [int(x) for x in cfg["time"].split(":")]
    kw: dict[str, Any] = {"hour": h, "minute": m}
    if cfg["schedule"] == "weekly":
        kw["day_of_week"] = cfg["weekday"]
    scheduler.add_job(run_scheduled, trigger=CronTrigger(**kw), id="vuln_scan", replace_existing=True, max_instances=1, coalesce=True)


async def run_scheduled() -> None:
    import asyncio
    if settings()["enabled"] and installed():
        try:
            await asyncio.to_thread(scan_apps)
        except Exception:
            logger.exception("scheduled vulnerability scan failed")


def after_update(container: str) -> None:
    """Gọi sau khi cập nhật app thành công: quét lại image mới (luồng nền)."""
    cfg = settings()
    if not (cfg["enabled"] and cfg["after_update"] and installed()):
        return
    threading.Thread(target=lambda: _safe_scan([container]), daemon=True).start()


def _safe_scan(names: list[str]) -> None:
    try:
        time.sleep(5)
        scan_apps(names, force=True)
    except Exception:
        logger.exception("vulnerability scan after update failed")
