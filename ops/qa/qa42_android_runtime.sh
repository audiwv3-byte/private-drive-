#!/usr/bin/env bash
set -euo pipefail
adb shell cmd location set-location-enabled true
adb shell dumpsys location > "${RUNNER_TEMP}/qa42-location-before.txt"
(
  while true; do
    adb emu geo fix 25.2797 54.6872
    sleep 2
    adb emu geo fix 25.2800 54.6875
    sleep 2
  done
) &
gps_pid=$!
trap 'kill "$gps_pid" 2>/dev/null || true; wait "$gps_pid" 2>/dev/null || true; adb shell dumpsys location > "${RUNNER_TEMP}/qa42-location-after.txt" || true' EXIT
cd qa_android
flutter test integration_test/qa42_device_runtime_test.dart -d emulator-5554 --dart-define=PD_NATIVE_AUTH_API_URL=https://qa.invalid --reporter expanded
