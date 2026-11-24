# Connected pilot, no payments

Scope: the existing signed-in passenger app submits to the existing staging
web dispatcher, and the passenger can reload the same order in «Мои заказы».
This first milestone does not enable pilot assignment, live GPS, chat, SMS
enrollment or any payment provider.

## Prepare staging before distributing the APK

1. Back up and verify the isolated PostgreSQL `private_drive_test` database.
   Confirm `current_database()` is `private_drive_test`. Do not run these
   steps against any other database or the active website.
2. Run the explicit versioned migrations as the isolated DB owner, with
   `psql -v ON_ERROR_STOP=1`, first
   `migrations/native_auth_session_functions.sql` then
   `migrations/native_dispatch_orders.sql`. No HTTP request migrates the
   schema. The native session migration needs the existing native auth tables
   (including `native_auth_sessions.revoked_at`).
3. In that database grant the roles in the snippets below. Replace the example
   role identifiers with the actual dedicated API and dispatcher logins. The
   API runtime authenticates against the existing native store; preserve its
   existing auth grants and permissions. The dispatcher requires only order
   read privileges. Do not use the DB owner as either runtime account.
4. Both services run the reviewed test-branch commit, not `main`. The existing
   dispatcher at `https://private-drive-dispatcher-staging.onrender.com/dispatch`
   installs `requirements-dispatcher-staging.txt`. Point its
   `PD_DISPATCH_ORDERS_DATABASE_URL` to the isolated DB using the dispatcher
   read-only login. Keep `PD_DISPATCH_STAGING_ONLY=1`.
5. On the isolated existing API at `https://private-drive-drbd.onrender.com`
   set `PD_DISPATCH_ORDERS_DATABASE_URL` to exactly its existing DB URL value
   (`DATABASE_URL`, API runtime login). On **both** set
   `PD_DISPATCH_STAGING_ONLY=1`, `PD_DISPATCH_PERSISTENT_QUEUE=1`, and
   `PD_PAYMENT_MODE=disabled`. Do not set
   `PD_DISPATCH_ORDERS_INGEST_SECRET` for this pilot: the unrelated import
   endpoint is not needed. Keep `PD_NATIVE_SMS_ISOLATED=YES` on the API and
   keep SMS sending disabled. Do not publish DSNs, login secrets or bearer tokens.
6. Verify API `/health` reports `sms_enabled: false`; a request without a
   session to `/native-orders` should return 401, not 404 or 503. Check that
   the authenticated dispatcher opens and reads the queue. Then check one
   synthetic passenger order by matching its server order ID in both histories
   and confirm repeating the same request ID does not create another row.
7. The exact test-branch workflow `PRIVATE DRIVE isolated no-payment QA`
   builds a connected, **internal debug** APK only when the tracked
   `flutter_app/tool/connected-pilot-apk.txt` manifest opts into staging.
   The `private-drive-connected-pilot-internal-debug-apk` artifact is separate
   from offline CI artifacts, and its package `lt.privatedrive.private_drive.pilot`
   does not replace the existing Android app. This also means existing
   sessions in other package IDs do **not** migrate. Do not publish the
   debug APK or give it to real testers before staging smoke verification,
   signing and a supported sign-in path are confirmed.

```sql
-- Order permission delta; substitute the dedicated runtime login identifiers.
GRANT USAGE ON SCHEMA public TO api_runtime, dispatcher_runtime;
GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint),
  public.pd_revoke_current_session(text,bigint) TO api_runtime;
GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners
  TO api_runtime;
GRANT SELECT ON public.pd_dispatch_orders TO dispatcher_runtime;
```
