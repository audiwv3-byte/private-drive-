# Native pilot photo review in the existing web dispatcher

Local closed-pilot prototype only. This page never uses the old pilot
application/document intake, creates a native user, grants a reviewer role,
binds identities automatically, sends SMS, or changes payment or GPS settings.
A signed-in browser operator has no photo access by default.

## Binding is an authorization prerequisite, not a feature switch

- **The existing browser/native reviewer link is not established by this
  repository.** The browser's signed session proves control of the one
  configured credential/ID and current credential version. It does not infer
  the operator's native identity from a matching number, username, Telegram
  ID, phone, email, or the mere presence of a website login.
- A separately authorized human owner must verify the exclusive browser
  operator and the same person's existing native reviewer account through
  independent authoritative evidence. No shared password or unverified
  reviewer is acceptable. Require a current supported native role
  (`admin` or `dispatcher`, not a pilot/combined role) and confirm the
  reviewer is a different person from every assigned pilot, including people
  with multiple native identities. If this cannot be established, stop.
- The proposed admin-only binding store records browser operator ID to the
  canonical native reviewer ID, a domain-separated server HMAC proof of the
  current credential version, verification time, and optional revocation.
  The browser cookie version is not accepted as a DB proof and no proof
  is shown to the browser. A separate owner-approved per-pilot pair
  records independent distinct-person verification; different account IDs
  alone do not prove that. No setting, route, command or fixture in deployed
  code creates live bindings or grants roles. Fixtures are synthetic.
- Changing/recovering the browser password invalidates the link until a
  new verified binding is authorized. Loss of native role, explicit link or
  pair revocation, or failure of the separate credential store blocks access
  including decisions on already open cases. A web password recheck is
  step-up vs. a replayed cookie; it is not MFA or independent proof of person.

## Data handling and least privilege

One page under `/dispatch/native-photo-review`, linked from the existing
dispatcher cabinet, independent from `/dispatch/pilot-applications`.
An authorized operator must re-enter the current dispatcher password and pass
existing form CSRF on every view and decision. One current, owner-verified,
pending case is shown as the native pipeline's sanitized JPEG in an HTML POST
response; never the original upload, no raw account/check IDs or photos list,
no JSON/base64 API, no persistent media URL, no external scripts/images, no
automatic page refresh. The HTML is private/no-store with no referrer or
indexing, restrictive CSP and same-origin protection. A legitimate reviewer
can still copy a rendered image; operational controls and limited access
remain necessary.

The short random claim uses a server-side digest bound to the original
browser session's CSRF nonce, credential version and current reviewer's case.
It expires after at most three minutes and never beyond photo expiry. Only the
latest eligible native pilot case can be claimed; the live reviewer binding,
same-person exclusion, distinct-person pairing, current roles and case
status/expiry are checked again at decision. Approval/rejection atomically
stores the native reviewer and server time and deletes the photo, never
changes roles. Existing native eligibility still requires a current
approval (at most seven days). Existing expired-photo purge remains; web
reviews never show expired images even if the purge worker has not run.
Before real consent/testers, verify actual purge while free services sleep and
exclude photo data from logs, analysis, export and undue backup retention.
Encrypted backup/restore must not make expired photo bytes accessible again.

## Test-only rehearsal and future deployment blockers

- The exact database guard is `private_drive_test`. The migration
  `native_web_photo_review.sql` is owner-run explicitly, after the existing
  native account/photo migrations; no DDL in web requests, no default row or
  grant. Verify an encrypted rollback path before any live migration and
  never run this on a production database.
- A separate dedicated role gets only `USAGE` on the public schema and
  `EXECUTE` on `pd_open_web_native_photo_review(bigint,text,text)` and
  `pd_decide_web_native_photo_review(bigint,text,text,text)`. No reads or
  writes on raw photo, identity, roles, binding, pair, or claims tables.
  Do not use the dispatcher password, assignment writer, browser registry,
  native API or owner database credential for this connection.
- The existing browser staging cabinet reviews only when
  `PD_WEB_NATIVE_PHOTO_REVIEW=1`, staging-only, explicitly payments disabled,
  and the dedicated review DSN points to exactly the same test DB as the
  queue DSN. In the isolated native API, the separately reviewed
  `PD_NATIVE_PHOTO_REVIEW_WEB_ONLY=1` blocks the legacy native reviewer
  queue/image/decision endpoints and leaves pilot photo submit/status.
  The native flag fails startup without the isolated, no-SMS pilot-invite mode.
  Both flags default off. Keep the web flag off until real reviewer verification
  and the native reviewer path is verified disabled; do not create or rely on
  a second mobile dispatcher.
- Synthetic acceptance checks missing bindings/role mismatch, wrong DB and
  paid mode, bad CSRF/cross-origin payload and password, no UID/image lists,
  isolated one-case claim and expiry, invalidated credentials/pair/role,
  cross-session and concurrent duplicate decisions, photo deletion on approve,
  reject and scheduled purge, and no approval grant before the current review.
  The synthetic fixture selects only loopback, a fixed test port/credential
  and a start-empty database. The browser bridge does not qualify as ready
  for real users until independent binding and runtime gates are verified.
