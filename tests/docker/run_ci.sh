#!/usr/bin/env bash
# Các bộ test Docker chạy được trên GitHub Actions (không cần proxy / tắt-bật dockerd / trình duyệt).
# Thoát mã 1 nếu có dòng FAIL, Traceback thật của Python, thiếu dòng SUMMARY hoặc SUMMARY a / b với a != b. Chạy từ gốc repo, sau ci_setup.sh.
set -uo pipefail
: "${S:?set S}"
OUT="$S/ci.out"; : > "$OUT"
suite() {  # suite "<tên>" <lệnh...>
  local name="$1"; shift
  echo "=== $name" | tee -a "$OUT"
  local log="$S/suite.log"
  ( "$@" ) > "$log" 2>&1
  grep -E "^(PASS|FAIL|SKIP|SUMMARY)|Traceback|Error" "$log" | tee -a "$OUT" >/dev/null
  grep -E "^(FAIL|SUMMARY)|^Traceback \(most recent call last\)" "$log"
  # Traceback thật của Python luôn bắt đầu dòng bằng "Traceback (most recent call last)" (không bắt chữ trong tên test);
  # SUMMARY a / b với a != b cũng là hỏng
  if grep -qE "^FAIL|^Traceback \(most recent call last\)" "$log" || ! grep -q "^SUMMARY" "$log" \
     || grep -E "^SUMMARY" "$log" | awk '{ if ($2 != $4) bad = 1 } END { exit !bad }'; then
    echo "::error title=$name::failed — log:"; tail -60 "$log"; FAILED=1
  fi
}
FAILED=0
fresh() { rm -rf "$S/$1" && mkdir -p "$S/$1"; }
fresh d1;  suite "1. docker run: update / rollback / network / volume" env APP_DATA_DIR=$S/d1 LOGF=$S/run.log bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_run.py"
fresh d4;  suite "4. Edit Config (docker run)" env APP_DATA_DIR=$S/d4 bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_edit.py"
fresh d5;  suite "5. Locks, stopped / external / --rm, digest pin" env APP_DATA_DIR=$S/d5 S=$S bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_extra.py"
fresh d12; suite "12. Uninstall + shared image" env APP_DATA_DIR=$S/d12 APPDATA_DIR=$S/AppData CASAOS_APPS_DIR=$S/casa/apps bash -c "bash $S/setup2.sh >/dev/null 2>&1; timeout 900 python -u $S/t_uninst.py"
fresh d13; suite "13. API rate limits (mocked Docker Hub / GitHub)" env APP_DATA_DIR=$S/d13 timeout 300 python -u $S/t_net.py
fresh d14; suite "14. Real registry account (registry:2 + htpasswd)" env APP_DATA_DIR=$S/d14 S=$S timeout 600 python -u $S/t_net_real.py
fresh d15; suite "15. Notifications (real ntfy / Gotify / webhook)" env APP_DATA_DIR=$S/d15 S=$S bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_notify.py"
fresh d17; suite "17. API Tokens" env APP_DATA_DIR=$S/d17 S=$S bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_tokens.py"
fresh d19; suite "19. Multiple servers" env S=$S bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_servers.py"
fresh d21; suite "21. New notification channels (Mailpit, Apprise)" env APP_DATA_DIR=$S/d21 S=$S timeout 600 python -u $S/t_notify2.py
fresh d23; suite "23. Content encryption + private mode" env APP_DATA_DIR=$S/d23 S=$S timeout 300 python -u $S/t_notify3.py
fresh d26; suite "26. Auto-update rules per app" env APP_DATA_DIR=$S/d26 bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 600 python -u $S/t_policy.py"
fresh d30; suite "30. Logs, remote logs / restore, server offline alerts" env S=$S bash -c "bash $S/setup.sh >/dev/null 2>&1; timeout 900 python -u $S/t_v021.py"
fresh d25; suite "25. Release channels" env APP_DATA_DIR=$S/d25 timeout 300 python -u $S/t_channels.py
echo; echo "Result:"; grep -E "^(===|SUMMARY|FAIL)" "$OUT"
exit $FAILED
