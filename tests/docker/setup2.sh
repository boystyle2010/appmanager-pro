set -e
M=mirror.gcr.io/library; S=${S}; A=$S/AppData; C=$S/casa/apps
docker rm -f $(docker ps -a --format "{{.Names}}" | grep -vE "^(registry|ntfy|gotify)$") >/dev/null 2>&1 || true
docker network prune -f >/dev/null 2>&1 || true; docker volume prune -af >/dev/null 2>&1 || true
rm -rf $A $S/casa; mkdir -p $A $C
for i in nginx:1.26-alpine nginx:1.27-alpine busybox:1.35 busybox:1.36 redis:7.2-alpine; do docker image inspect $M/$i >/dev/null 2>&1 || docker pull -q $M/$i >/dev/null; done
# --- compose cũ chạy ổn định: 2 service, bind ./config
mkdir -p $A/stableapp/config && echo '{"theme":"dark"}' > $A/stableapp/config/settings.json
cat > $A/stableapp/docker-compose.yml <<YML
name: stableapp
services:
  app:
    image: $M/busybox:1.35
    command: ["sh", "-c", "busybox | head -1 | grep -q v1.35 && sleep 3600"]
    volumes:
      - ./config:/config
    restart: unless-stopped
  cache:
    image: $M/redis:7.2-alpine
    restart: unless-stopped
YML
(cd $A/stableapp && docker compose up -d >/dev/null 2>&1)
# --- compose dễ cập nhật: container_name cố định
mkdir -p $A/cmpweb && cat > $A/cmpweb/docker-compose.yml <<YML
services:
  cmpweb:
    image: $M/nginx:1.26-alpine
    container_name: cmpweb
    ports: ["8282:80"]
YML
(cd $A/cmpweb && docker compose up -d >/dev/null 2>&1)
# --- app kiểu CasaOS (x-casaos) + file compose trùng khác nội dung trong AppData
mkdir -p $C/casaapp $A/casaapp
cat > $C/casaapp/docker-compose.yml <<YML
name: casaapp
services:
  casaapp:
    image: $M/busybox:1.35
    container_name: casaapp
    command: sleep 3600
    x-casaos:
      envs: []
x-casaos:
  main: casaapp
  title:
    en_US: Casa Demo App
  icon: https://cdn.jsdelivr.net/gh/IceWhaleTech/CasaOS-AppStore@main/Apps/Jellyfin/icon.png
  port_map: "8383"
YML
cp $C/casaapp/docker-compose.yml $A/casaapp/docker-compose.yml && echo "# edited copy" >> $A/casaapp/docker-compose.yml
(cd $C/casaapp && docker compose up -d >/dev/null 2>&1)
# --- CasaOS còn file cũ của app "oldcasa" (đã gỡ) nhưng người dùng chạy container cùng tên bằng docker run
mkdir -p $C/oldcasa && printf 'name: oldcasa\nservices:\n  oldcasa:\n    image: %s/busybox:1.35\n    container_name: oldcasa\nx-casaos:\n  main: oldcasa\n  title:\n    en_US: Old Casa\n' $M > $C/oldcasa/docker-compose.yml
docker run -d --name oldcasa $M/busybox:1.35 sleep 3600 >/dev/null
# --- docker run trùng tên project compose + cùng image với compose
docker run -d --name stableapp --restart unless-stopped $M/busybox:1.35 sleep 3600 >/dev/null
# --- docker run có file cài đặt trong AppData
mkdir -p $A/cfgapp/config/media $A/cfgapp/config/logs
echo '{"lang":"vi","port":1}' > $A/cfgapp/config/settings.json; printf 'a: 1\n' > $A/cfgapp/config/config.yaml
echo "old log" > $A/cfgapp/config/logs/app.log; head -c 2000000 /dev/urandom > $A/cfgapp/config/media/movie.mkv
docker run -d --name cfgapp --restart unless-stopped -p 8484:80 -e APP_MODE=prod -v $A/cfgapp/config:/config $M/nginx:1.26-alpine >/dev/null
# --- docker run: bản mới "chuyển đổi" dữ liệu rồi lỗi, bản cũ không đọc được dữ liệu mới
mkdir -p $A/cfgmig/config && echo '{"v":1}' > $A/cfgmig/config/settings.json
docker run -d --name cfgmig --restart unless-stopped -v $A/cfgmig/config:/config $M/busybox:1.35 sh -c 'if busybox | head -1 | grep -q v1.35; then [ -f /config/migrated.json ] && exit 3; sleep 3600; else echo "{}" > /config/migrated.json; exit 1; fi' >/dev/null
docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}'
