# PRIVATE DRIVE: isolated unified-order bridge (2026-11-26)

## Confirmed architecture break

The Telegram Mini App POST /api/order commits to core.ORDERS_DB (SQLite).
Its success path notifies Telegram users/admins and does not write
public.pd_dispatch_orders in the staging PostgreSQL dispatcher.

The existing Flutter passenger flow uses authenticated POST/GET
/native-orders and the existing staging dispatcher reads PostgreSQL.
The HTML website in staging is a preview, not yet a booking channel.
Do not claim Android/iOS/website end-to-end delivery before deployment tests.

## Safe bridge in this branch

- Keeps original Telegram order and its price unchanged.
- Server-side HMAC POST goes to existing /v1/dispatch/orders/import.
- The fixed source is telegram_miniapp and original local ID is stable.
- Converts existing DD.MM.YYYY departure date into API ISO format.
- Existing request_key persists across retries, including legacy booking form.
- In bridge mode, a missing central acknowledgement returns HTTP 503 with
  dispatch_received=false rather than a false confirmation.
- Existing payment routes are untouched; bridge is disabled unless payment
  mode is explicitly disabled. No payment credential travels in the envelope.
- Off by default, no deployment changes, no schema migrations.

## Staging-only configuration prerequisites

On the **isolated Mini App instance only**, not production:
PD_MINIAPP_DISPATCH_BRIDGE=1
PD_DISPATCH_STAGING_ONLY=1
PD_PAYMENT_MODE=disabled
PD_MINIAPP_DISPATCH_IMPORT_URL=https://<isolated-dispatcher-host>/v1/dispatch/orders/import
PD_DISPATCH_ORDERS_INGEST_SECRET=<private unique server-to-server secret, 32+ characters>

On the **isolated dispatcher** with reviewed PostgreSQL schema and account:
PD_DISPATCH_STAGING_ONLY=1
PD_DISPATCH_PERSISTENT_QUEUE=1
PD_PAYMENT_MODE=disabled
PD_DISPATCH_ORDERS_DATABASE_URL=<isolated PostgreSQL DSN>
PD_DISPATCH_ORDERS_INGEST_SECRET=<same private server-to-server secret>

Keep credentials in the platform secrets store. Never commit actual values.

## Acceptance test (not yet performed against running services)

1. Verify the isolated dispatcher with role authorization and its database.
2. Submit Telegram Mini App order with a stable request_key.
3. Require API response dispatch_received=true and central dispatch_order_id.
4. GET /dispatch/orders/state as an authenticated dispatcher and locate
   the exact central ID and source telegram_miniapp.
5. Retry the same Telegram order: the central ID must remain identical.
6. Force dispatcher outage: no success message; retry after recovery.
7. Submit native Android/iOS authenticated orders, check same dispatcher
   queue and passenger GET /native-orders, with no payment.
8. Check website booking only after website submit flow is connected.

No live/staging deployment or real-device acceptance is implied by CI tests.
