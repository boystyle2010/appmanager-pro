"""
Khởi động thử app (không cần Docker daemon) và gọi các trang/API chính.
Chạy bên trong image: python scripts/smoke_test.py  — thoát mã khác 0 nếu có lỗi.
"""
import os
import sys
import tempfile

os.environ.setdefault("APP_DATA_DIR", tempfile.mkdtemp(prefix="amp-smoke-"))
# Chạy được cả trong image (code ở thư mục làm việc /app) lẫn trong repo
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app, base_url="http://localhost")
failures = []


def check(method, path, expect, **kw):
    r = client.request(method, path, follow_redirects=False, **kw)
    ok = r.status_code in expect
    print(f"{'OK ' if ok else 'ERR'} {method} {path} -> {r.status_code}")
    if not ok:
        failures.append(f"{method} {path}: {r.status_code} {r.text[:300]}")
    return r


check("GET", "/login", {200})                       # trang thiết lập lần đầu (render template)
check("GET", "/", {200, 302, 303, 307})             # chưa đăng nhập -> chuyển về /login
check("GET", "/api/apps", {401})                    # API cần đăng nhập
r = check("POST", "/api/auth/setup", {200},
          json={"username": "smoke", "password": "smoke-test-1", "confirm_password": "smoke-test-1"})
check("GET", "/", {200})                            # đã đăng nhập -> render dashboard
check("GET", "/api/auth/security", {200})
check("GET", "/api/settings", {200})
check("GET", "/api/audit", {200})
check("POST", "/api/auth/logout", {403}, headers={"Origin": "http://evil.example"})  # chống CSRF phải chặn
check("GET", "/static/js/app.js", {200})

if failures:
    print("\nSMOKE TEST FAILED:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("\nSmoke test passed")
