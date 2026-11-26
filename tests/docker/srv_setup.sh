# Dựng máy chính (:8793) + máy phụ (:8792) từ repo cho e2e14.js; Token quyền Cập nhật của máy phụ -> $S/srv.tok
pkill -f "port 879[23]" ; sleep 1
for x in 8793:srv_ui_main 8792:srv_ui_rem; do port=${x%%:*}; d=$S/${x#*:}; rm -rf $d && mkdir -p $d
  (APP_DATA_DIR=$d nohup python -m uvicorn app.main:app --port $port > $d.log 2>&1 &); done
sleep 7
for port in 8793 8792; do curl -s -X POST localhost:$port/api/auth/setup -H 'Content-Type: application/json' -H "Origin: http://localhost:$port" \
  -d '{"username":"admin","password":"Test-Passw0rd!x","confirm_password":"Test-Passw0rd!x"}' >/dev/null; done
curl -s -c $S/rem.ck -X POST localhost:8792/api/auth/login -H 'Content-Type: application/json' -H 'Origin: http://localhost:8792' -d '{"username":"admin","password":"Test-Passw0rd!x"}' >/dev/null
curl -s -b $S/rem.ck -X POST localhost:8792/api/tokens -H 'Content-Type: application/json' -H 'Origin: http://localhost:8792' \
  -d '{"name":"Main server","scope":"update","ips":"127.0.0.1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])' > $S/srv.tok
echo ready
