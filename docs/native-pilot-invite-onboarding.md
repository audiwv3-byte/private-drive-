# Closed PRIVATE DRIVE pilot-account onboarding without SMS

This is opt-in support for a **pre-approved pilot's individual test account**,
not open pilot sign-up, identity proof, dispatcher sign-in, or production
deployment. The passenger invitation route is unchanged. No invite has been
issued or sent outside synthetic tests.

## Operator boundary

- A separately authorized operator creates or identifies the pilot's stable
  isolated account and confirms entitlement before issuance. The account must
  already exist with `native_auth_users.channel='invite'` and exact
  `native_auth_roles.role='pilot'`. The issue command cannot create or grant
  a pilot role, turn a passenger into a pilot, use an admin/dispatcher account,
  or issue an invite for a phone-backed account. Record approval outside the
  code and never extend it automatically when a code is presented.
- Reuse the previously verified identity when a device is replaced. Keep the
  authorized account review and invite delivery in a recipient-verified private
  channel, separate from support logs and the app. No shared code, no use of
  links with credentials, and no public HTTP invitation issuance.
- Existing verified staging operator only: use the guarded
  `pd_issue_closed_pilot_invite.py --for-approved-pilot <opaque-user-id>`
  with the original private output-file procedure and a single-use code.
  Default validity 6 hours; maximum 24 hours. The operator never discloses
  database URLs, codes, or Bearer tokens in logs or in the repository.
- The passenger endpoint `/native-auth/redeem-invite` remains passenger-only.
  The new pilot endpoint `/native-auth/redeem-pilot-invite` only accepts a
  pilot-purpose code. Both JSON bodies contain **only** `invite_code`;
  the API/SQL choose purpose and live role. Trying the wrong route cannot
  consume a code. Already-used/reissued codes and role-changed credentials
  do not work. A valid pilot invite authorizes the existing photo status
  and submission flow; it is **not** photo approval.

## Rehearsal and scope

1. Do not apply this from a runtime service or to an unreviewed live database.
   Verify the isolated target, actual prior migrations and a recoverable
   encrypted backup first. In the disposable PostgreSQL QA fixture, apply
   `native_auth_session_functions.sql`, `native_closed_pilot_invites.sql`,
   then `native_pilot_invite_onboarding.sql` as the migrations owner.
   The new migration refuses databases other than `private_drive_test`.
   The migration adds purpose/session binding and invalidates outstanding
   invite credentials on future role changes; it makes no grants or role changes.
2. As an explicit separate reviewed grant, allow only the isolated native API
   runtime to execute `public.pd_redeem_closed_pilot_account_invite(text,text)`.
   Preserve existing passenger, role-validator, order, and photo grants.
   No runtime direct reads/writes on invite tables, session bindings or role
   table, and no access to the internal redemption helper. The web dispatcher
   gets neither issuance permission nor direct photo-table access.
3. Keep both old and new switches default OFF. The new endpoint requires
   `PD_NATIVE_PILOT_INVITE_ONBOARDING=1`, in addition to
   `PD_NATIVE_CLOSED_PILOT_INVITES=1`, the isolated native service, no live
   SMS/Twilio flags, disabled payments, and the known test database.
   Requesting pilot invitations with contradictory settings stops isolated API
   startup before auth is mounted. A valid pilot-invite boot disables
   live SMS and skips even read-only Twilio provider probes. Existing behavior
   outside the pilot-invite opt-in remains unchanged. Assignment setup remains
   a separate scoped deployment.
4. For a later **privately signed internal beta** only, the existing staging
   HTTPS URL, `PD_CLOSED_PILOT_INVITE_ENTRY=true`,
   `PD_NATIVE_PILOT_INVITE_ONBOARDING=true`, and
   `PD_NATIVE_PILOT_ASSIGNMENT=true` are explicit Dart defines. Do not use a
   public debug key or enable `PD_INTERNAL_QA` / demo switches. The existing
   diagnostic debug artifact and one-time pilot feature switches are unchanged.
5. Test with a synthetic new pilot lacking a photo before testers: redeem only
   once, restore a server-authorized session, submit a synthetic photo and
   confirm pending/rejected or expired status does not allow assignment. A
   separate authorized reviewer must approve via the identity flow. Only
   then must the existing web dispatcher see the eligible pilot and only
   that pilot see the assigned order. No automatic role elevation or
   approval. The sole web dispatcher still needs its native photo review
   handoff verified; these changes do not add a second dispatcher or a reviewer.
6. The new server opt-in flag gates redemption, not all already issued Bearer
   sessions. For a rollback, disable issuance/redemption first, then separately
   revoke affected pilot invite sessions and outstanding codes under reviewed
   operator control. Do **not** drop purpose bindings or restore the older
   broad role validator while any affected tokens can still be used.
   Preserve passenger data and existing phone identities.

The local suites cover exact live roles, no public issue, wrong-purpose codes,
concurrent single-use redemption, per-role invalidation, existing passenger
compatibility, approved/rejected photo gating and Flutter invite/cabin routing.
They do not verify a live deployment, a signed binary, or a real tester's
identity and consent.
