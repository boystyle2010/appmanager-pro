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

docker build --quiet -t "$TAG" . >/dev/null
echo "Image $TAG built"

if [ "$SMOKE" = "smoke" ]; then
  docker run --rm -e APP_DATA_DIR=/tmp/amp-data -v "$PWD/scripts/smoke_test.py:/smoke_test.py:ro" \
    --entrypoint python "$TAG" /smoke_test.py
fi
