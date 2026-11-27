#!/usr/bin/env bash
# Dựng môi trường test trên máy có Docker sẵn (GitHub Actions / máy dev). Biến S = thư mục làm việc tạm.
# Giống mục 1 của tests/docker/README.md nhưng không cần khởi động dockerd và không cần proxy của sandbox.
set -euo pipefail
: "${S:?set S to a scratch directory}"
mkdir -p "$S"
M=mirror.gcr.io/library
pull() { for i in 1 2 3; do docker pull -q "$1" >/dev/null && return 0; sleep 20; done; echo "pull failed: $1"; return 1; }
for i in nginx:1.26-alpine nginx:1.27-alpine busybox:1.35 busybox:1.36 busybox:1.38 busybox:latest redis:7.2-alpine registry:2 httpd:2; do pull "$M/$i"; done
pull mirror.gcr.io/binwiederhier/ntfy:latest
pull mirror.gcr.io/gotify/server:latest
pull mirror.gcr.io/keycloak/keycloak:26.4   # SSO thật (bộ 35)
for n in registry ntfy gotify; do docker rm -f "$n" >/dev/null 2>&1 || true; done
docker run -d --name registry --restart unless-stopped -p 5000:5000 "$M/registry:2" >/dev/null
docker run -d --name ntfy --restart unless-stopped -p 8091:80 mirror.gcr.io/binwiederhier/ntfy:latest serve >/dev/null
docker run -d --name gotify --restart unless-stopped -p 8092:80 -e GOTIFY_DEFAULTUSER_PASS=adminpw mirror.gcr.io/gotify/server:latest >/dev/null
for _ in $(seq 30); do curl -fs localhost:8092/health >/dev/null 2>&1 && break; sleep 1; done
APPTOK=$(curl -s -u admin:adminpw -X POST localhost:8092/application -H 'Content-Type: application/json' -d '{"name":"amp"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
CLITOK=$(curl -s -u admin:adminpw -X POST localhost:8092/client -H 'Content-Type: application/json' -d '{"name":"reader"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
echo "$APPTOK $CLITOK" > "$S/gotify.tok"
cp tests/docker/* "$S/"
echo "ready"
