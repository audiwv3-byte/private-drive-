#!/usr/bin/env bash
# Android emulator -> adb reverse -> real isolated Python server on runner.
# No external network exposure, production identities, or payment requests.
set -euo pipefail

export PD_DEMO_ISOLATED=YES
export PD_DEMO_HOST=127.0.0.1
export PD_DEMO_PORT=8765
export PD_DEMO_PASSENGER_TOKEN="$(printf 'p%.0s' {1..40})"
export PD_DEMO_PILOT_TOKEN="$(printf 'd%.0s' {1..40})"
export PD_DEMO_DISPATCHER_TOKEN="$(printf 'a%.0s' {1..40})"
export PD_DEMO_DB="$(mktemp -t private-drive-ci-chat-XXXXXX.sqlite)"

python3 test_sync_server/pd_demo_server.py &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  rm -f "$PD_DEMO_DB" "$PD_DEMO_DB-wal" "$PD_DEMO_DB-shm"
}
trap cleanup EXIT

# Seed one synthetic assigned trip using the same API as the actual clients.
python3 - <<'PY'
import http.client, json, os, time
port = int(os.environ["PD_DEMO_PORT"])
base = "127.0.0.1"
def req(method, path, token, body=None):
    conn = http.client.HTTPConnection(base, port, timeout=3)
    headers = {"Authorization": "Bearer " + token}
    encoded = json.dumps(body).encode() if body is not None else None
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=encoded, headers=headers)
        reply = conn.getresponse()
        status = reply.status
        data = json.loads(reply.read())
        return status, data
    finally:
        conn.close()
for i in range(50):
    try:
        status, _ = req("GET", "/v1/me", os.environ["PD_DEMO_PASSENGER_TOKEN"])
        if status == 200:
            break
    except OSError:
        pass
    time.sleep(0.1)
else:
    raise RuntimeError("Isolated chat backend did not start")
status, created = req("POST", "/v1/trips", os.environ["PD_DEMO_PASSENGER_TOKEN"],
    {"from":"Synthetic A","to":"Synthetic B","payment":"Карта"})
assert status == 201, (status, created)
trip = created["trip"]
status, assigned = req("POST", "/v1/trips/" + trip["id"] + "/assign",
    os.environ["PD_DEMO_DISPATCHER_TOKEN"],
    {"pilot":"pilot_test","version":trip["version"]})
assert status == 200, (status, assigned)
print("Synthetic test trip assigned; no real orders created")
PY

adb reverse tcp:8765 tcp:8765
adb reverse --list
(cd private_drive_build && flutter test \
  integration_test/android_chat_delivery_smoke_test.dart \
  -d emulator-5554 --reporter expanded --timeout 4m)
