M=mirror.gcr.io/library; S=${S}
# fixture: trang tĩnh cho bind mount của "web" + stack compose "demo" (dựng lại mỗi lần vì test sửa file này)
mkdir -p $S/bind $S/stack/demo && echo hello-from-bind > $S/bind/index.html
printf 'services:\n  demo:\n    image: %s/busybox:1.35\n    command: sleep 3600\n' $M > $S/stack/demo/docker-compose.yml; rm -f $S/stack/demo/*.bak
docker rm -f $(docker ps -a --format "{{.Names}}" | grep -vE "^(registry|ntfy|gotify)$") >/dev/null 2>&1; docker network rm appnet backnet demo_default >/dev/null 2>&1; docker volume rm webdata >/dev/null 2>&1; docker volume prune -af >/dev/null 2>&1
docker network create --subnet 172.30.0.0/24 appnet >/dev/null && docker network create backnet >/dev/null && docker volume create webdata >/dev/null
docker run -d --name web --restart unless-stopped -p 8181:80 -p 8443:443/tcp -e TZ=Asia/Ho_Chi_Minh -e MYVAR=keep   -v $S/bind:/usr/share/nginx/html:ro -v webdata:/data -v /cachevol --network appnet --ip 172.30.0.50 --network-alias webalias   -l com.example.owner=me --cap-add NET_ADMIN --tmpfs /run/tmpx --hostname myweb   --health-cmd "wget -qO- http://127.0.0.1/ >/dev/null || exit 1" --health-interval 3s $M/nginx:1.26-alpine >/dev/null
docker network connect --alias webback backnet web
sleep 1; docker exec web sh -c 'echo persisted > /data/file.txt; echo anon > /cachevol/a.txt'
docker run -d --name bb-sidecar --network container:web $M/busybox:1.35 sleep 3600 >/dev/null
docker run -d --name bb-fail --restart unless-stopped $M/busybox:1.35 sh -c 'busybox | head -1 | grep -q "v1.35" && sleep 3600' >/dev/null
docker run -d --name bb-stopped $M/busybox:1.35 sleep 3600 >/dev/null && docker stop -t 1 bb-stopped >/dev/null
docker run -d --name bb-none --network none $M/busybox:1.35 sleep 3600 >/dev/null
docker run -d --name ext-swarm -l com.docker.swarm.service.id=abc $M/busybox:1.35 sleep 3600 >/dev/null
docker run -d --name redis $M/redis:7.2-alpine >/dev/null && docker create --name redis-amp-old $M/busybox:1.35 >/dev/null
(cd $S/stack/demo && docker compose up -d >/dev/null 2>&1)
