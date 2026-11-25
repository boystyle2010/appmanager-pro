cd /home/user/appmanager-pro
S=${S}
r() { echo "=== $1"; }
r "2. Đợt 2 + hồi quy compose/CasaOS"; bash $S/setup2.sh >/dev/null 2>&1; rm -rf $S/ampdata3 && mkdir -p $S/ampdata3; APP_DATA_DIR=$S/ampdata3 APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps timeout 1800 python $S/t_full.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
r "7. Giao diện đầy đủ (AppManager chạy trong container)"; bash $S/setup2.sh >/dev/null 2>&1; bash $S/start_amp.sh >/dev/null; sleep 6; rm -rf $S/e2e5/*; timeout 1700 node $S/e2e5.js $S/e2e5 2>&1 | grep -E "^(FAIL|SUMMARY)|Error"
echo "=== 15. Thông báo (ntfy, Gotify thật, webhook, Telegram/Discord giả lập, sự kiện thật)"; bash $S/setup.sh >/dev/null 2>&1; rm -rf $S/ampnotify && mkdir -p $S/ampnotify; APP_DATA_DIR=$S/ampnotify S=$S timeout 900 python -u $S/t_notify.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo REDONE
