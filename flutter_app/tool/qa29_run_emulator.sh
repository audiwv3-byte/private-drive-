#!/usr/bin/env bash
set -Eeuo pipefail
rm -f /tmp/qa29-order-id
python -u flutter_app/tool/qa29_gps_integration.py serve qa27_server > qa29-server.log 2>&1 &
SERVER_PID=$!
cleanup() {
  status=$?
  trap - EXIT
  adb logcat -d > qa29-android.log 2>&1 || true
  adb shell uiautomator dump /sdcard/qa29-final.xml >/dev/null 2>&1 || true
  adb pull /sdcard/qa29-final.xml qa29-ui.xml >/dev/null 2>&1 || true
  adb exec-out screencap -p > qa29-screen.png || true
  kill "$SERVER_PID" 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT
for i in $(seq 1 40); do
  test -s /tmp/qa29-order-id && break
  kill -0 "$SERVER_PID"
  sleep 1
done
test -s /tmp/qa29-order-id
python -u flutter_app/tool/qa29_gps_integration.py emulator qa29_apk/PRIVATE-DRIVE-GPS-QA29.apk 2>&1 | tee qa29-e2e.log
