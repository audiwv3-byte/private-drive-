# Issue #30 — offline integration contract (NOT a deployment)

Date: 2026-11-17. Scope: comparison against GitHub branch only. Live PythonAnywhere `pd_onboarding.py`, deployed HTML and SQLite schema were NOT fetched; no claim of live compatibility or executed integration tests.

## Observed GitHub code (feature/issue-30-document-review-offline-20261117)
- `pd_document_review.py`: separate per-document review + event audit; SHA-256 stale-photo comparison in `BEGIN IMMEDIATE`; no automatic pilot approval.
- `pd_onboarding.py`: original repository handles stage-1 uploads with `ACTIVE_SIDES`, permits UPSERT of uploaded photos and resets application to `pending`; existing admin decision checks presence of five stage-1 photos only. This is **not** the confirmed deployed two-stage onboarding.
- `pd_pilot_dispatch.py`: work and assignment access relies on `pd_driver_applications.status == 'approved'`; therefore guarding the actual server transition to `approved` is mandatory, not just greying out a UI button.

## Integration decisions — fail closed
1. First obtain GET-only *source* of deployed `pd_onboarding.py`, live route registration and deployed dispatcher UI; never copy GitHub `main` over deployed files. Compare route methods/paths, stage values and document side mappings and verify SQLite schema via read-only PRAGMA (no document BLOB export).
2. Add schema migration for `pd_document_reviews` and `pd_document_review_events` through a separately tested deployment step. Never auto-approve historical uploads. Migration must be backed up and read-back verified before any live operation.
3. Register document-review routes only after verifying `auth()` and `core.is_admin()` in deployed code. GET must remain side-effect-free; handle absent tables gracefully instead of a 500. Never expose SHA/doc metadata to unauthorized roles.
4. Implement per-document decisions only within verified **server-side** dispatcher authorization and allowed stage. Use expected SHA from inspected photo and `BEGIN IMMEDIATE` to block stale reviews; use audit. No pilot upload overwrites existing photos.
5. Insert `require_approved_documents(conn, applicant, 1)` on stage-1 acceptance and `require_approved_documents(conn, applicant, 2)` immediately before *every* transition to final `approved`, under the SAME write transaction; require stage-2 submission before final approval. Reject any code path that updates status outside this guard.
6. Preserve existing stage-1 -> stage-2 transition semantics; do not repurpose `approved` for stage-1. Retain approved pilots' status until a separately specified, explicitly approved migration policy exists; do not silently revoke or reapprove.
7. Dispatcher: image preview owner/admin only, status and reason per side, approve/reject controls, SHA refresh after changes. Final approve disabled in UI, but security enforced on server. Registration pilot view never receives dispatcher actions.
8. Registration: existing uploaded image cannot be replaced by pilot; authorized dispatcher replacement must reset that document to pending by SHA mismatch. Pay attention to repository's current UPSERT: it is incompatible with this requirement.
9. No changes to bookings, payments, live images, driver assignments or trips.

## Synthetic tests required before deploy
- Schema creation on temporary SQLite; no rewrite of historical rows and BLOBs.
- All five stage-1 required documents reviewed -> stage-1 transition permitted; missing/rejected/pending => blocked.
- All five stage-2 + five stage-1 approved, and actual stage2 submitted => final transition permitted; optional registration_back absent => permitted.
- Old document with no review => pending; changed BLOB SHA invalidates previous decision; stale expected SHA => reject and leave events unchanged.
- Replayed identical approve => unchanged audit count; rejection requires reason; unsupported side/action => error.
- Unauthorized pilot blocked by GET, POST, dispatcher decision, and replacement paths.
- Dispatcher may review own permission-scoped side; cross-role access blocked; no implicit status changes.
- Concurrent replacement/review serialized; any error => rollback, unchanged previous statuses.
- Previously approved historical pilots remain unchanged in migration; new approvals fail closed.

## Unresolved blocker
This is a **design/static code review only** until the deployed two-stage source, route registration, and synthetic test-run logs are available. Do not install or enable `register(...)` before server-side transition guards and stage-aware compatibility tests pass.
