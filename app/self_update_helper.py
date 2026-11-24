"""
Container phụ tự cập nhật / tạo lại AppManager Pro, có kiểm tra sức khoẻ và tự rollback.

Chạy bằng IMAGE CŨ (bản đang chạy ổn) trong một container riêng, vì container AppManager sẽ bị
thay thế giữa chừng. Không import gì từ app.core để không đụng database / scheduler.

Đọc việc cần làm từ <data>/self-update-job.json (AppManager ghi trước khi gọi), ghi kết quả + nhật ký vào
<data>/self-update-result.json; AppManager (bản mới hoặc bản đã rollback) đọc và ghi vào Lịch sử.

Các bước:
  1. (mode=update) docker compose pull <service>   — lỗi: trả compose về như cũ, không đụng container.
  2. docker compose up -d --force-recreate --no-deps <service>  (luôn container mới -> đếm restart chính xác)
  3. Chờ container mới chạy ổn: đang chạy, không restart, healthcheck không "unhealthy",
     và trang /login trả lời trong chính container.
  4. Hỏng -> lưu log container hỏng -> trả compose cũ + gắn lại tag image cũ (GIỮ database) -> tạo lại -> kiểm tra;
     bản cũ vẫn không chạy (database đã bị bản mới đổi) -> trả database sao lưu -> tạo lại -> kiểm tra.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/app/data"))
JOB_FILE = DATA_DIR / "self-update-job.json"
RESULT_FILE = DATA_DIR / "self-update-result.json"
PROBE = (
    "import urllib.request,sys\n"
    "try:\n"
    "    r=urllib.request.urlopen('http://127.0.0.1:8000/login',timeout=5)\n"
    "    sys.exit(0 if r.status<500 else 1)\n"
    "except Exception:\n"
    "    sys.exit(1)\n"
)

_log: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    _log.append(line)
    print(line, flush=True)


def run(cmd: list[str], cwd: str, timeout: int = 900) -> int:
    log("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        log(f"[ERROR] {exc}")
        return 1
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        log(out[-4000:])
    return proc.returncode


def split_ref(ref: str) -> tuple[str, str]:
    if not ref or "@" in ref:
        return "", ""
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = ref.rsplit(":", 1)
        return repo, tag
    return ref, "latest"


def wait_healthy(client, name: str, window: int) -> tuple[bool, str]:
    """Ổn khi trang /login trả lời 2 lần liên tiếp (cách nhau ≥ 5 giây) mà container không restart."""
    start = time.time()
    first_ok = 0.0
    last = "unknown"
    while time.time() - start < window:
        time.sleep(3)
        try:
            c = client.containers.get(name)
            c.reload()
        except Exception as exc:
            last = f"container not found ({exc})"
            continue
        st = c.attrs.get("State", {}) or {}
        health = (st.get("Health") or {}).get("Status") or ""
        last = f"status={st.get('Status')} health={health or '-'} restarts={c.attrs.get('RestartCount', 0)}"
        if st.get("Restarting") or (c.attrs.get("RestartCount") or 0) > 0:
            return False, f"Container keeps restarting ({last})"
        if st.get("Status") in ("exited", "dead"):
            return False, f"Container stopped with exit code {st.get('ExitCode')}"
        if health == "unhealthy":
            return False, "Healthcheck reports unhealthy"
        if st.get("Status") != "running":
            continue
        try:
            code = c.exec_run(["python", "-c", PROBE]).exit_code
        except Exception:
            code = 1
        if code == 0:
            if not first_ok:
                first_ok = time.time()
            elif time.time() - first_ok >= 5:
                return True, "Web UI answers"
        else:
            first_ok = 0.0
    return False, f"Web UI did not answer within {window}s ({last})"


def diagnostics(client, name: str) -> None:
    try:
        c = client.containers.get(name)
        st = c.attrs.get("State", {}) or {}
        log(f"--- State: status={st.get('Status')} exit_code={st.get('ExitCode')} error={st.get('Error') or '-'}")
        for entry in ((st.get("Health") or {}).get("Log") or [])[-3:]:
            log(f"--- Healthcheck exit {entry.get('ExitCode')}: {str(entry.get('Output') or '').strip()[:500]}")
        logs = c.logs(tail=60).decode("utf-8", errors="replace").rstrip()
        log("--- Last 60 log lines:\n" + (logs or "(empty)"))
    except Exception as exc:
        log(f"--- Cannot collect diagnostics: {exc}")


def write_result(job: dict[str, Any], status: str, message: str) -> None:
    result = {**{k: job.get(k) for k in ("container", "title", "from_version", "to_version", "mode", "history_mode")},
              "status": status, "message": message, "finished": int(time.time()), "log": "\n".join(_log)}
    tmp = RESULT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(result), encoding="utf-8")
    tmp.replace(RESULT_FILE)
    JOB_FILE.unlink(missing_ok=True)


def restore_compose(job: dict[str, Any]) -> None:
    text = job.get("compose_original")
    if text is None:
        return
    try:
        Path(job["compose_path"]).write_text(text, encoding="utf-8")
        log("==> docker-compose.yml restored to the previous content")
    except Exception as exc:
        log(f"[ERROR] Cannot restore docker-compose.yml: {exc}")


def restore_db(client, job: dict[str, Any]) -> None:
    """Dừng bản hỏng rồi trả database về bản sao lưu ngay trước khi cập nhật (kèm xoá -wal/-shm cũ)."""
    bak = DATA_DIR / (job.get("db_backup") or "")
    db = DATA_DIR / (job.get("db_name") or "")
    if not job.get("db_backup") or not bak.is_file() or not job.get("db_name"):
        return
    try:
        client.containers.get(job["container"]).stop(timeout=20)
    except Exception:
        pass
    try:
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        tmp = db.with_name(db.name + ".restore")
        tmp.write_bytes(bak.read_bytes())
        tmp.replace(db)
        log("==> AppManager database restored to the copy taken before the update")
    except Exception as exc:
        log(f"[ERROR] Cannot restore the database: {exc}")


def edit_compose(job: dict[str, Any], service: str) -> None:
    """Thêm volume (cùng đường dẫn host:container) và biến môi trường vào service của AppManager."""
    from ruamel.yaml import YAML  # có sẵn trong image

    path = Path(job["compose_path"])
    text = path.read_text(encoding="utf-8")
    if job.get("compose_original") is None:
        job["compose_original"] = text  # để rollback trả lại đúng file trước khi sửa
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096  # không tự xuống dòng chuỗi dài
    data = y.load(text)
    svcs = data.get("services") or {}
    svc = svcs.get(service) if service in svcs else next(
        (v for v in svcs.values() if isinstance(v, dict) and (v.get("container_name") == job.get("container"))), None)
    if svc is None and len(svcs) == 1:
        svc = next(iter(svcs.values()))
    if not isinstance(svc, dict):
        raise RuntimeError("Cannot find the AppManager service in docker-compose.yml")
    vols = svc.get("volumes")
    if vols is None:
        svc["volumes"] = vols = []
    existing = set()
    for v in vols:
        if isinstance(v, str):
            existing.add(v.split(":")[0])
        elif isinstance(v, dict):
            existing.add(str(v.get("source") or ""))
    for p in job.get("add_volumes") or []:
        if p not in existing:
            vols.append(f"{p}:{p}")
            log(f"==> Added volume {p}:{p}")
    for key, val in (job.get("set_env") or {}).items():
        env = svc.get("environment")
        if env is None:
            svc["environment"] = env = []
        if isinstance(env, list):
            idx = next((i for i, e in enumerate(env) if isinstance(e, str) and e.split("=", 1)[0] == key), None)
            if idx is None:
                env.append(f"{key}={val}")
            else:
                env[idx] = f"{key}={val}"
        elif isinstance(env, dict):
            env[key] = val
        log(f"==> Set environment {key}={val}")
    import io

    buf = io.StringIO()
    y.dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


def main() -> int:
    import docker  # có sẵn trong image

    try:
        job = json.loads(JOB_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERROR] Cannot read {JOB_FILE}: {exc}", flush=True)
        return 1

    client = docker.from_env()
    name = job["container"]
    service = job.get("service") or ""
    compose = job["compose_path"]
    cwd = str(Path(compose).parent)
    window = int(job.get("window") or 120)
    svc_args = [service] if service else []
    time.sleep(2)  # để AppManager kịp trả lời trình duyệt

    if job.get("add_volumes") or job.get("set_env"):
        try:
            edit_compose(job, service)
        except Exception as exc:
            log(f"[ERROR] Cannot edit docker-compose.yml: {exc}")
            restore_compose(job)
            write_result(job, "failed", f"Cannot edit docker-compose.yml: {exc}")
            return 1

    if job.get("mode") == "update":
        if run(["docker", "compose", "-f", compose, "pull", *svc_args], cwd) != 0:
            restore_compose(job)
            write_result(job, "failed", "docker compose pull failed; nothing was changed")
            return 1

    rc = run(["docker", "compose", "-f", compose, "up", "-d", "--force-recreate", "--no-deps", *svc_args], cwd)
    if rc == 0:
        log(f"==> Checking the new container for up to {window}s...")
        ok, reason = wait_healthy(client, name, window)
    else:
        ok, reason = False, f"docker compose up failed (exit {rc})"
    log(f"==> {reason}")

    if ok:
        old_id = job.get("old_image_id") or ""
        if job.get("prune_old_image") and old_id:
            try:
                if client.containers.get(name).image.id != old_id:
                    client.images.remove(image=old_id, force=False)
                    log(f"==> Removed old image {old_id[:19]}")
            except Exception:
                pass  # image còn được dùng (vd container phụ này) -> để lần dọn sau
        write_result(job, "success", "Updated" if job.get("mode") == "update" else "Recreated")
        return 0

    # ---- Rollback: trước hết chỉ compose + image (giữ database); bản cũ vẫn hỏng mới trả database ----
    diagnostics(client, name)
    log("==> Rolling back to the previous version (database is kept)...")
    restore_compose(job)
    repo, tag = split_ref(job.get("image_ref") or "")
    if repo and job.get("old_image_id"):
        try:
            client.images.get(job["old_image_id"]).tag(repo, tag=tag)
            log(f"==> Previous image {job['old_image_id'][:19]} re-tagged as {repo}:{tag}")
        except Exception as exc:
            log(f"[ERROR] Cannot re-tag previous image: {exc}")

    def recreate_and_check() -> tuple[bool, str]:
        rc = run(["docker", "compose", "-f", compose, "up", "-d", "--force-recreate", "--no-deps", *svc_args], cwd)
        if rc != 0:
            return False, f"docker compose up failed (exit {rc})"
        return wait_healthy(client, name, window)

    rb_ok, rb_reason = recreate_and_check()
    log(f"==> Rollback: {rb_reason}")
    if not rb_ok and job.get("db_backup"):
        diagnostics(client, name)
        log("==> Previous version does not start with the current database; restoring the database backup...")
        restore_db(client, job)
        rb_ok, rb_reason = recreate_and_check()
        log(f"==> Rollback with restored database: {rb_reason}")
    if rb_ok:
        write_result(job, "rolled_back", f"{reason}; previous version restored")
        return 1
    diagnostics(client, name)
    write_result(job, "failed", f"{reason}; rollback failed: {rb_reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
