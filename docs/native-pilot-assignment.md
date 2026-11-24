# Pilot assignment — first staging slice

Scope: a verified dispatcher assigns an Android/iOS native passenger order in the
existing `/dispatch` web queue. The passenger's history and the assigned pilot's
authenticated read endpoint see the same persisted order ID and new status.
There is no acceptance/decline transition, live GPS, SMS, payment or live release
in this change. An explicitly opted-in Flutter build projects the server
assignments into the existing pilot cabin without local demo controls.
Its map button opens the existing map with an independent, foreground-only
**Показать мою позицию** switch. Tapping that switch never sends the device
position to the dispatch server, changes the order, or starts sharing with a
passenger. Before GPS starts, the online map is removed and replaced with
an offline reference grid that shows the local fix. GPS cannot animate, center
or generate tile URLs on the online map. The original online map remains a
separate, manually explored view; normal map imagery requests still go to its
existing provider. Stopping GPS, leaving the map, or leaving the foreground
removes the position; after interruption another explicit tap is required.
Returning to the order list refreshes assignments with the same native session.

## Sequence

1. First verify the no-payment persistent passenger order flow (dispatcher and
   native API use one isolated `private_drive_test` database). On its own the old
   baseline would require the unrelated HMAC ingest secret even to read the queue.
2. Ensure the native account and photo tables plus the explicit
   `pd_validate_native_session` function exist. Verify the backup/restore plan
   before any staging migration. Run `migrations/native_pilot_assignment.sql`
   explicitly as the isolated DB owner. Do not use database owner DSNs at runtime.
3. Preserve the dispatcher queue reader connection/SELECT permissions. Add a
   separate login for assignment, with USAGE on `public` and only EXECUTE on its
   two wrappers. Its internal URL goes in `PD_PILOT_ASSIGNMENT_DATABASE_URL`
   on the dispatcher; it must match the queue reader's host, port and database.
   Native order API's existing runtime login receives only EXECUTE on the new
   native read wrapper. Replace the sample role names below; no public grants,
   no photo reads, no raw UPDATE privilege needed.
4. When the approved deployment is ready, opt in on both services with
   `PD_NATIVE_PILOT_ASSIGNMENT=1` and `PD_DISPATCH_STAGING_ONLY=1`.
   Existing no-payment flags remain required; keep real SMS off. Disable this flag to remove this
   path without dropping persisted data or granting extra privileges.
5. Sign in to the existing web cabinet. Only pilot-entitled, currently
   photo-approved users are eligible (latest decision, under seven days).
   Native pilot can read only orders assigned to their current Bearer account.
   On this first slice admin rights alone are not pilot entitlement. Verify
   permissions and deployment against synthetic accounts first, not users.
6. On a separate reviewed staging build only, use
   `--dart-define=PD_NATIVE_PILOT_ASSIGNMENT=true` with
   `--dart-define=PD_NATIVE_AUTH_API_URL=https://private-drive-drbd.onrender.com`.
   This mobile flag defaults off. Check Flutter tests and actual signed-device
   behavior before distribution. Real pilot account setup still needs an
   operator-approved pilot entitlement and current photo approval; the
   passenger-only invitation does not grant staff privileges.

If a pilot's role or latest photo decision changes, the pilot's read access
stops immediately. This slice deliberately does not release or reassign
the existing order automatically, nor can the UI take it over. The dispatcher
should stop that case, verify the pilot again before resuming, and report the
order for an audited recovery flow if the original pilot cannot return. Do not
accept test cases that require changing pilots until the explicit dispatcher
reassign/cancel operation is implemented and concurrency-tested.

```sql
GRANT USAGE ON SCHEMA public TO assignment_runtime;
GRANT EXECUTE ON FUNCTION public.pd_pilot_assignment_candidates(bigint),
  public.pd_assign_native_order(uuid,text,text,bigint) TO assignment_runtime;
GRANT EXECUTE ON FUNCTION public.pd_native_pilot_order_state(text,bigint)
  TO native_api_runtime;
```

The synthetic test `tests/test_native_pilot_assignment_postgres.py` exercises the
actual HTTP routes from a disposable loopback PostgreSQL using the preceding
native-session and order migrations. It must be run on the version which has
split independent queue reading from signed import. It requires
`PD_CI_FAKE_DB_ONLY=YES` and a freshly provisioned localhost test DB with URL
`postgresql://pd_assignment_owner:synthetic-only@127.0.0.1:<port>/private_drive_test`
passed via `PD_SYNTHETIC_ASSIGNMENT_DATABASE_URL`; never pass a staging URL.
