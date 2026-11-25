cd /home/user/appmanager-pro
S=${S}
ln -sfn $S/tw/node_modules node_modules && ./node_modules/.bin/tailwindcss -i app/static/css/tailwind.input.css -o app/static/css/tailwind.css --minify >/dev/null 2>&1; rm -f node_modules
bash $S/build_amp.sh >/dev/null
bash $S/run_all.sh | grep -v ALLDONE
echo "=== 9. Phục hồi sau sự cố (kill giữa chừng + Docker khởi động lại)"; bash $S/setup.sh >/dev/null 2>&1; rm -rf $S/ampdata7 && mkdir -p $S/ampdata7; APP_DATA_DIR=$S/ampdata7 S=$S timeout 1200 python -u $S/t_recover.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo "=== 10. Mất điện khi AppManager tự cập nhật"; bash $S/setup2.sh >/dev/null 2>&1; S=$S timeout 1500 python -u $S/t_selfcrash.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo "=== 11. Kịch bản mới (registry riêng tư, app chậm, Postgres, macvlan, --link, tên dài, gỡ kèm AppData, 120 container)"; bash $S/setup2.sh >/dev/null 2>&1; rm -rf $S/ampdata8 && mkdir -p $S/ampdata8; APP_DATA_DIR=$S/ampdata8 APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps S=$S timeout 2400 python -u $S/t_more.py 2>&1 | grep -E "^(FAIL|SKIP|SUMMARY)|Traceback"
echo "=== 12. Gỡ app + image dùng chung"; bash $S/setup2.sh >/dev/null 2>&1; rm -rf $S/ampdata10 && mkdir -p $S/ampdata10; APP_DATA_DIR=$S/ampdata10 APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps timeout 900 python -u $S/t_uninst.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo "=== 13. Giới hạn API (giả lập Docker Hub / GitHub)"; rm -rf $S/ampnet && mkdir -p $S/ampnet; APP_DATA_DIR=$S/ampnet timeout 300 python -u $S/t_net.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo "=== 14. Tài khoản registry thật"; rm -rf $S/ampnet2 && mkdir -p $S/ampnet2; APP_DATA_DIR=$S/ampnet2 S=$S timeout 600 python -u $S/t_net_real.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo "=== 15. Thông báo (ntfy, Gotify thật, webhook, Telegram/Discord giả lập, sự kiện thật)"; bash $S/setup.sh >/dev/null 2>&1; rm -rf $S/ampnotify && mkdir -p $S/ampnotify; APP_DATA_DIR=$S/ampnotify S=$S timeout 900 python -u $S/t_notify.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
echo FINALDONE
