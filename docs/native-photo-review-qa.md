# PRIVATE DRIVE 0.2.27 — cabin selection before sign-in

Branch: feature/flutter-independent-auth. No production deployment, paid SMS,
real booking or payment activation is part of this change.

## Implemented

- The first screen is Passenger / Pilot / Dispatcher, before phone entry and
  optional location/notification onboarding. Pilot opens the photo notice;
  Passenger and Dispatcher are never routed through photo verification.
- Pilot upload requires a verified native session with server-authorized pilot
  entitlement. Pilot cabin navigation follows server-approved photo status.
  Dispatcher sign-in checks server entitlement and requires no photo.
- Internal QA photo skip returns to cabin choice and never approves identity.

- Internal QA only: explicit guest entry opens the passenger cabin without
  requesting an OTP, claiming phone verification or exposing staff roles.
  Guest state is stored in a separate local scope, not under an authenticated
  user's ID. Signed-in pilot/dispatcher access remains server-authorized.
- Phone sign-in errors preserve the server error code and explain disabled
  SMS, invalid phone numbers and request cooldown instead of a generic error.
- The emulator check taps through optional permissions and the guest button
  in the actual APK, then asserts the passenger Taxi/Transfer screen is visible.

- Still camera capture from an explicit user gesture; local preview and retake.
- Explicit authenticated HTTPS upload with redirect following disabled.
- Private PostgreSQL photo storage, image validation, JPEG re-encoding with
  metadata removed, bounded request size, one pending request per pilot.
- Server-authorized dispatcher/admin queue and manual approval or rejection.
- Reviewer cannot view or approve their own photo. Expired/revoked sessions and
  passenger accounts cannot upload or review. Every request rechecks DB roles.
- Sending, skipping or approving a photo never grants a role. Approval expires
  after seven days. Pending photo access expires after 72 hours; active-service
  cleanup removes expired bytes. Decision immediately removes photo bytes.
- Cabin choice remains based on the server role. QA navigation bypass is only
  compiled when PD_INTERNAL_QA=true and does not change verification status.

## Distribution and data preservation

This full native QA package uses lt.privatedrive.private_drive.photo_qa and the
visible label PRIVATE DRIVE QA. It installs alongside older QA applications.
It does not migrate, erase or import data from another Android package.
The older full_qa builds used ephemeral CI debug keys; those private keys
cannot be recovered from their APKs. Do not uninstall an older package to
force a signature-conflicting update. This QA series uses the repository's
public TEST debug key for consistent future QA updates, never for release.

## Validation boundaries

Flutter tests use synthetic camera images and mocked API transport. PostgreSQL
tests use a disposable CI database and cover upload, review, ACL, revoked
sessions, duplicate requests, expiry and deletion. Android emulator launch
tests install the assembled APK, start the real main.dart activity and check
for process survival and fatal Flutter/Android exceptions.

Physical Redmi camera operation and a real two-account review remain device
acceptance checks. No claim of biometric recognition or liveness detection.
This is manual photo review, with no automatic identity decision.

## Current isolated service prerequisites

Read-only inspection on 2026-11-21 found zero native-auth accounts and zero
assigned admin/pilot roles. The service /health returned sms_enabled=false.
Paid SMS remains disabled. Real phone sign-in therefore requires a separate
approved SMS setup and verified-account role assignment before real users can
exercise the photo workflow. The existing cabins still contain local test
trip behavior; this change does not make bookings, payments or cross-device
trip synchronization production-ready. Native sessions are currently held in
process memory; app restart requires sign-in again.
