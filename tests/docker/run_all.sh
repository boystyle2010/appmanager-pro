cd /home/user/appmanager-pro
S=${S}
r() { echo "=== $1"; }
r "1. Đợt 1 (docker run: cập nhật/rollback/mạng/volume)"; bash $S/setup.sh >/dev/null 2>&1; rm -rf $S/ampdata && mkdir -p $S/ampdata; APP_DATA_DIR=$S/ampdata LOGF=$S/run.log timeout 900 python $S/t_run.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
r "2. Đợt 2 + hồi quy compose/CasaOS"; bash $S/setup2.sh >/dev/null 2>&1; rm -rf $S/ampdata3 && mkdir -p $S/ampdata3; APP_DATA_DIR=$S/ampdata3 APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps timeout 1800 python $S/t_full.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
r "3. P4 (khôi phục khi image cũ đã bị xoá)"; APP_DATA_DIR=$S/ampdata3 APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps timeout 600 python $S/t_p4.py 2>&1 | grep -E "^(PASS|FAIL)"
r "4. Đợt 3A (sửa cấu hình docker run)"; bash $S/setup.sh >/dev/null 2>&1; rm -rf $S/ampdata5 && mkdir -p $S/ampdata5; APP_DATA_DIR=$S/ampdata5 timeout 900 python $S/t_edit.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
r "5. Kịch bản phụ (xung đột khoá, container dừng, ngoài, compose, khôi phục sau sửa)"; bash $S/setup.sh >/dev/null 2>&1; rm -rf $S/ampdata6 && mkdir -p $S/ampdata6; APP_DATA_DIR=$S/ampdata6 S=$S timeout 900 python $S/t_extra.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
r "6. Đợt 3B (AppManager tự cập nhật / sửa khi chạy docker run + compose)"; bash $S/setup2.sh >/dev/null 2>&1; S=$S timeout 1500 python $S/t_self.py 2>&1 | grep -E "^(FAIL|SUMMARY)|Traceback"
r "7. Giao diện đầy đủ (AppManager chạy trong container)"; bash $S/setup2.sh >/dev/null 2>&1; bash $S/start_amp.sh >/dev/null; sleep 6; rm -rf $S/e2e5/*; timeout 1700 node $S/e2e5.js $S/e2e5 2>&1 | grep -E "^(FAIL|SUMMARY)|Error"
r "8. Phần đầu cửa sổ sau cập nhật"; timeout 400 node $S/e2e6.js $S/e2e5 2>&1 | grep -E "PASS|FAIL"
echo ALLDONE
