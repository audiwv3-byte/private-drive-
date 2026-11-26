#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="$PWD:$PWD/qa_android/flutter_app/tool"
export QA29_ORDER_FILE="$RUNNER_TEMP/dispatcher-map-order-id"
python -u -m qa29_gps_integration serve qa_server > "$RUNNER_TEMP/map-api.log" 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true; tail -n 35 "$RUNNER_TEMP/map-api.log"' EXIT
for attempt in {1..40}; do
  if curl -s -o /dev/null http://127.0.0.1:18729/dispatch/orders/state; then break; fi
  kill -0 "$server"
  sleep 1
done
test -s "$QA29_ORDER_FILE"
python -u ops/qa/dispatcher_order_gps_browser.py "$@"
