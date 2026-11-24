# PRIVATE DRIVE: passenger sign-in for a closed pilot without SMS

The invitation path is an authenticated **passenger** sign-in for the existing
native app and isolated order API. It is off by default server-side and
client-side. It does not prove a phone number, create a staff identity, replace
dispatcher authentication, turn on SMS or enable payment. It is not the
previous offline guest/demo. No invitations are delivered automatically.

## Before enabling in isolated staging

- Confirm the existing auth, order and dispatcher services use the intended
  isolated database (database name `private_drive_test`). Before applying
  migrations to an existing database, verify an encrypted recoverable backup.
- In the isolated database only, apply the already reviewed native-session
  validation/revocation and order migrations, then
  `migrations/native_closed_pilot_invites.sql` as the database migration
  principal. The invite migration itself fails outside `private_drive_test`.
  It is never executed at application start or by a request.
- The web service must use its isolated native app WSGI and a restricted
  runtime principal. Grant that principal only the permissions already needed
  for other paths plus `EXECUTE` on
  `public.pd_redeem_closed_pilot_invite(text,text)`. Do not grant it access to
  the invite table, management commands, or DDL. `PUBLIC` has neither table
  access nor function execution. Keep the issuing principal separate. Review
  privilege changes and owner of the security-definer function before deploy.
- Keep `PD_NATIVE_SMS_ISOLATED=YES`, `PD_PAYMENT_MODE=disabled`, and
  `PD_NATIVE_SMS_LIVE` and `TWILIO_VERIFY_ENABLED` off. Explicitly set
  `PD_NATIVE_CLOSED_PILOT_INVITES=1` only on this isolated auth service, after
  all dependencies are installed. The app accepts only a direct PostgreSQL
  URL naming the test database without query-string overrides.
- In the **privately signed beta** only, use the usual staging auth API URL
  (`https://private-drive-drbd.onrender.com`) and
  `--dart-define=PD_CLOSED_PILOT_INVITE_ENTRY=true`. Do **not** enable
  `PD_INTERNAL_QA`, offline-preview or isolated demo flags. The special
  invitation form is only for the passenger cabin and is not a web preview.

## Operator scope

There is no HTTP endpoint to issue invitations. An authenticated staging DB
operator executes `pd_issue_closed_pilot_invite.py` from a trusted shell with
`PD_CLOSED_PILOT_OPERATOR_DATABASE_URL` supplied securely as an environment
secret and the same staging/no-payment/no-SMS flags above. Use `--output` with
a new file in a private directory outside any repository. Default expiry is
six hours; `--hours` allows one to 24. The file is mode 0600 and contains the
opaque user ID and one unique code. Use a recipient-verified private channel,
never embed the code in a web URL, and remove the file after delivery. Do not
share Bearer sessions, log codes, use a shared code, or use the code as identity
proof. Issue one test identity per consenting tester. There is no automatic
notification or contact with testers.

If the operator revalidates the tester, `--reissue-for-user` keeps their user
ID and history and voids outstanding unused invitations. It does not end an
already active session. For a lost device, also revoke the lost session using
the reviewed one-device revocation workflow before replacement. Access tokens
are stored as digests server-side and kept in the existing secure storage on the
device. An invite session lasts up to seven days; extend the pilot by issuing
a new code, not by sharing credentials. The ordinary server logout, restore
and order routes must use the same database and session contract.

The default passenger invitation path does not sign in pilots or administrators.
An independent, separately enabled [pilot invitation](native-pilot-invite-onboarding.md)
still requires approved account provisioning, a server-owned role and the
existing photo approval workflow. No invitation grants an administrator role. The dispatcher
continues to work in the website cabinet. Assignment, cross-device live
GPS, iOS signing and tester distribution are separate readiness checks.

## Acceptance before testing with people

On the signed build, verify that a single disposable invitation opens the
passenger through the normal app, relaunch restores the existing session,
logout revokes it, and the same code cannot be redeemed again. Verify that
one test order appears in native history and the existing web dispatcher
with the same ID, retrying it does not create a duplicate, and no payment
or phone confirmation is attempted. Use non-personal addresses and test data
for this check. Inspect only sanitized status/results, not authentication
codes, location or personal information in logs.
