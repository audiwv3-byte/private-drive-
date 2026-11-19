# PRIVATE DRIVE — chat delivery audit (test branch)

## Confirmed implementation

- Ordinary passenger and pilot cabins use one in-memory `DemoTripStore`. Messages are persisted only as device-local demo state; there is no cross-device transport in these cabinets.
- `PilotPassengerChatDemo` and `PassengerOrdersDemo` explicitly describe their chat as local/offline.
- The separate `RemoteSyncDemo` screen connects to the isolated `test_sync_server` via HTTPS, authenticates tokens through `/v1/me`, POSTs to `/v1/trips/{id}/messages`, and polls `?after={seq}`.
- The isolated server stores messages in SQLite and determines role from the server-side bearer-token mapping, not from UI labels. It checks trip owner / assigned pilot / dispatcher access.
- Existing synthetic tests: `test_sync_server/test_chat_delivery.py`, `flutter_app/test/remote_sync_demo_test.dart`, and `flutter_app/test/pilot_passenger_delivery_test.dart`.

## Fixed in this branch

When a refresh batch contained an incoming message followed by an echoed message from the current user, remote voice notification previously used `chatMessages.last['role']`. This incorrectly announced the current user's own role. The new `newestIncomingChatRole` helper selects the latest *incoming* role from only newly received records. Regression coverage includes mixed pilot/dispatcher/passenger batches and own-message-only batches.

## Still required before cross-device chat can be marked fixed

1. Wire the *actual* pilot/passenger order screens to an authenticated, per-trip, cross-device transport instead of `DemoTripStore`; keep the isolated demo server separate from production.
2. Verify stable, unique server identities for passenger, pilot and dispatcher and a single order-room ID; do not infer duplicated admin identities from UI labels alone.
3. Exercise bidirectional delivery, retry, persistence, and notification after background/reconnect on two test devices using synthetic orders only.
4. Run Flutter and Python test suites in CI, then validate the corresponding Android APK on a device before distributing it.

This audit makes no live bookings, sends no SMS, performs no payments and does not modify PythonAnywhere.
