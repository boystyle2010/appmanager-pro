# Lấy Docker CLI & Compose v2 binary chính chủ (tương thích hoàn hảo amd64 & arm64)
FROM docker:29.10.0-cli AS docker-cli

# Biên dịch Tailwind CSS v4 một lần trên máy build (CSS dùng chung cho mọi kiến trúc)
FROM --platform=$BUILDPLATFORM node:lts-slim AS css
ARG TAILWIND_VERSION=4.3.5
WORKDIR /src
RUN npm init -y >/dev/null \
    && npm install --no-audit --no-fund --loglevel=error tailwindcss@${TAILWIND_VERSION} @tailwindcss/cli@${TAILWIND_VERSION}
COPY app/templates ./app/templates
COPY app/static ./app/static
RUN npx @tailwindcss/cli -i app/static/css/tailwind.input.css -o /out/tailwind.css --minify \
    && test -s /out/tailwind.css

FROM python:3.15.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/app/data \
    CASAOS_APPS_DIR=/var/lib/casaos/apps \
    APPDATA_DIR=/DATA/AppData

WORKDIR /app

# Copy Docker CLI và Compose plugin sang Python image
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

# apt-get upgrade: nhận các bản vá bảo mật mới nhất của Debian (giảm lỗi Trivy báo "fixable")
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Nâng setuptools (bản đi kèm image dính CVE-2025-47273), cài thư viện, rồi GỠ pip: app không cần pip khi chạy,
# và pip tự đóng gói kèm pkg_resources của setuptools 70.3.0 (pip/_vendor/vendor.txt) -> Trivy báo lỗ hổng.
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall -y pip \
    && rm -rf /root/.cache

COPY app/ ./app/
COPY --from=css /out/tailwind.css ./app/static/css/tailwind.css
COPY assets/ ./assets/
# Giấy phép của mã nguồn & các thành phần bên thứ ba được đóng gói (xem THIRD_PARTY_NOTICES.md)
COPY LICENSE THIRD_PARTY_NOTICES.md ./
COPY licenses/ ./licenses/

# Tải sẵn Tailwind/Alpine/marked/DOMPurify/font về image để không phụ thuộc CDN lúc chạy
# (lỗi tải chỉ cảnh báo; trang tự dùng CDN dự phòng nếu thiếu file)
COPY scripts/ ./scripts/
RUN python scripts/fetch_vendor.py /app/app/static/vendor

RUN mkdir -p /app/data

EXPOSE 8000

# Không tin header X-Forwarded-For từ mọi nơi (chống giả IP để vượt khoá đăng nhập).
# App tự xử lý header proxy theo biến TRUSTED_PROXIES (xem README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
