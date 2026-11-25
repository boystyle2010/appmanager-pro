docker run -d --name ext-swarm -l com.docker.swarm.service.id=abc mirror.gcr.io/library/busybox:1.35 sleep 3600 >/dev/null
docker rm -f appmanager-pro >/dev/null 2>&1; rm -rf ${S}/selfdata2 && mkdir -p ${S}/selfdata2
docker tag localhost:5000/amp:1 localhost:5000/amp:latest && docker push -q localhost:5000/amp:latest >/dev/null
docker run -d --name appmanager-pro --restart unless-stopped --network host -e TZ=Asia/Ho_Chi_Minh -e HTTPS_PROXY=$HTTPS_PROXY -e HTTP_PROXY=$HTTPS_PROXY -e NO_PROXY=localhost,127.0.0.1 -e SSL_CERT_FILE=/ca.crt -v /root/.ccr/ca-bundle.crt:/ca.crt:ro -v /var/run/docker.sock:/var/run/docker.sock -v ${S}/selfdata2:/app/data -v ${S}/AppData:${S}/AppData -v ${S}/casa/apps:${S}/casa/apps -e APPDATA_DIR=${S}/AppData -e CASAOS_APPS_DIR=${S}/casa/apps localhost:5000/amp:latest >/dev/null
sleep 8
curl -s -X POST localhost:8000/api/auth/setup -H 'Content-Type: application/json' -H 'Origin: http://localhost:8000' -d '{"username":"admin","password":"Test-Passw0rd!x","confirm_password":"Test-Passw0rd!x"}'
