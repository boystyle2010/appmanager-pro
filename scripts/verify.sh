#!/usr/bin/env bash
# Kiểm tra một phiên bản mã nguồn trước khi commit:
#   1) cú pháp & import nội bộ  2) build image Docker thật  3) (tuỳ chọn) khởi động thử app trong image
# Cách dùng: scripts/verify.sh <tag> [smoke]
set -euo pipefail
TAG="${1:-amp-verify}"
SMOKE="${2:-}"

python -m compileall -q app scripts
python -m pip install --quiet jinja2 >/dev/null
python scripts/check_project.py
node --check app/static/js/app.js
node --check app/static/js/i18n.js

# BUILDX_CACHE_FROM (vd "type=gha" trên GitHub Actions): dùng lại các lớp đã build ở lần phát hành trước
CACHE_ARGS=()
if [ -n "${BUILDX_CACHE_FROM:-}" ]; then CACHE_ARGS=(--cache-from "$BUILDX_CACHE_FROM"); fi

docker buildx build "${CACHE_ARGS[@]}" --load --quiet -t "$TAG" . >/dev/null
echo "Image $TAG built"

if [ "$SMOKE" = "smoke" ]; then
  # 1) Chạy app thật bằng uvicorn (lệnh CMD của image) và mở trang đăng nhập
  CID=$(docker run -d -e APP_DATA_DIR=/tmp/amp-data -p 127.0.0.1:18080:8000 "$TAG")
  ok=""
  for i in $(seq 1 30); do
    if curl -fsS -o /dev/null http://127.0.0.1:18080/login; then ok=1; break; fi
    sleep 1
  done
  if [ -z "$ok" ]; then
    echo "App did not start with uvicorn:"; docker logs "$CID" | tail -40; docker rm -f "$CID" >/dev/null; exit 1
  fi
  echo "uvicorn boot OK"; docker rm -f "$CID" >/dev/null
  # 2) Gọi các trang/API chính
  docker run --rm -e APP_DATA_DIR=/tmp/amp-data -v "$PWD/scripts/smoke_test.py:/smoke_test.py:ro" \
    --entrypoint python "$TAG" /smoke_test.py
fi

# 3) Build thử bản arm64 (bắt lỗi thư viện thiếu bản dựng sẵn cho ARM) — cần QEMU/buildx
if [ "${VERIFY_ARM64:-}" = "1" ]; then
  docker buildx build "${CACHE_ARGS[@]}" --platform linux/arm64 -t "$TAG-arm64" . >/dev/null
  echo "arm64 image built"
fi
