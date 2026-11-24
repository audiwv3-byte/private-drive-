# Closed pilot photo identity: no runtime DDL

The isolated staging API keeps the existing photo-review endpoints and session
roles. Once its closed pilot or persistent staging queue is enabled,
`isolated_sms_wsgi` selects the restricted identity runtime automatically.
For a staged rehearsal without turning on invitations or the queue, the isolated
native API can opt in with `PD_NATIVE_IDENTITY_NO_RUNTIME_DDL=1`. The old
initialization and health behavior are unchanged outside this mode.

## Review before staging deployment

- Confirm the existing isolated database, operator ownership and recoverable
  encrypted backup before applying anything. Explicitly apply the reviewed
  `native_auth_session_functions.sql` migration before enabling the checked
  photo flow. Apply `migrations/native_pilot_identity.sql` as the migrations
  owner, never as an HTTP runtime. It is additive and reuses the existing
  `public.native_identity_checks` table without rewriting photo data, changing
  roles, or starting notification/SMS. If in-place schema differs, inspect
  metadata and stop instead of applying unreviewed ALTER statements.
- Keep the API login low privilege. Pilot photo ACLs are derived from the
  existing server-owned role on the validated Bearer token. The staged API
  needs exactly the object grants shown below for the photo routes; existing
  auth/order grants are separate. Keep schema CREATE, database ownership,
  unrestricted session reads, direct role writes, and identity table DELETE
  out of the runtime account. Do not weaken existing auth grants.
- Keep the web dispatcher queue reader and assignment-writer PostgreSQL roles
  without direct photo table access, including individual column privileges.
  Pilot assignment needs only its reviewed eligibility/assignment wrappers,
  not the identity table or its photo bytes.
- Restricted `/health` is delegated to the underlying native-auth readiness
  check. It does **not** assert photo storage readiness. With synthetic accounts
  and a synthetic image test pilot status, upload, authorized review, denial for
  unrelated roles, and one-device session restoration. An approved photo is
  retained only until a decision or existing expiry cleanup; the role is never
  upgraded by photo review. Confirm storage/ACL failures return 503 without
  exposing data or creating schema.
- Never replace the actual HTTP role with an owner account to make startup
  succeed. Do not run with production credentials, request SMS or change
  eligibility rules for this migration.

| Principal | Identity access |
|---|---|
| Dedicated isolated DB migration owner | Explicit table/index creation and grant management |
| Existing isolated native API runtime | Column-scoped photo reads/writes, existing SQL session validator; no runtime DDL |
| Dispatcher queue reader | No identity/photo access |
| Assignment writer | Assignment and eligibility wrappers only; no identity/photo access |
| `PUBLIC` | None |

```sql
-- Example: substitute the actual isolated native API runtime role name.
GRANT USAGE ON SCHEMA public TO api_runtime;

GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint)
  TO api_runtime;

GRANT SELECT (id,user_id,status,photo,created_at,expires_at,decided_at),
      INSERT (id,user_id,status,photo,created_at,expires_at),
      UPDATE (status,photo,reviewer_id,decided_at)
  ON public.native_identity_checks TO api_runtime;
```
