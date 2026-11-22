# Lấy Docker CLI & Compose v2 binary chính chủ (tương thích hoàn hảo amd64 & arm64)
FROM docker:29.10.0-cli AS docker-cli

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

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY assets/ ./assets/

# Tải sẵn Tailwind/Alpine/marked/DOMPurify/font về image để không phụ thuộc CDN lúc chạy
# (lỗi tải chỉ cảnh báo; trang tự dùng CDN dự phòng nếu thiếu file)
COPY scripts/ ./scripts/
RUN python scripts/fetch_vendor.py /app/app/static/vendor

RUN mkdir -p /app/data

EXPOSE 8000

# Không tin header X-Forwarded-For từ mọi nơi (chống giả IP để vượt khoá đăng nhập).
# App tự xử lý header proxy theo biến TRUSTED_PROXIES (xem README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
