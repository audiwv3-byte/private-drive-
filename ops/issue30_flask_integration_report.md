# PRIVATE DRIVE issue #30 — Flask route integration, SQLite concurrency, and launch gates

Date: 2026-11-17. **Test-only feature branch; nothing deployed.**

## Verified files

- `pd_issue30_document_storage_guard.py`: pilot insert-only + admin SHA checked transactional replacement, audit and return to pending (from prior work).
- `pd_issue30_flask_integration.py`: explicit TESTING-only Flask integration harness. It does NOT register endpoints in production: `register_offline_routes` raises unless both an explicit synthetic opt-in and `app.config["TESTING"] is True`. The pilot route is a test surrogate, not an overlay on the live existing `POST /api/driver/application` route.
- `test_pd_issue30_flask_integration.py`: independent temporary SQLite file, separate connections, Flask test clients, artificial authenticated identities, concurrent threaded requests and failure-trigger rollback. The test-only header `X-Synthetic-User` MUST NEVER be used for production authentication.
- `.github/workflows/issue30-readonly-check.yml`: checks all offline unit tests; PythonAnywhere auditing remains GET-only.

## Test evidence

GitHub Actions workflow run `43977162552` — `59 tests ... OK`, including the Flask/SQLite integration suite. GET-only PythonAnywhere audit job also succeeded. Production DB and application data were not accessed by the tests.

Tested: pilot first upload succeeds; second upload rejected even with different bytes; stage restrictions; admin permission enforced server-side; SHA lease and stale hash reject; review invalidation to pending; approved pilot protected; bad/missing file; failed audit insert rolls back updated image; concurrent first uploads one 201 and one 409; concurrent replacements one 200 and one 409; application status unchanged. Static legacy UPSERT detector rejects the known `ON CONFLICT(telegram_id,side) DO UPDATE SET image=...` SQL.

## Known production blocker — old UPSERT

GET-only source audit observed live `pd_onboarding.py` still contains `ON CONFLICT(telegram_id,side) DO UPDATE SET image=excluded.image` in the existing registration route. This means merely adding new guarded routes would NOT prevent the pilot from using the original unsafe endpoint.

**Release integration plan (NOT performed):**
1. Compare deployed `pd_onboarding.py` SHA-256 against the verified baseline; abort if changed.
2. In the original registration handler, preserve all existing input and stage-validation logic. Perform application row creation/update first, then invoke `pilot_insert_missing(conn, applicant=uid, side=side, image=normalized_bytes)` *within the same existing* `BEGIN IMMEDIATE` SQLite transaction, replacing **every** old document UPSERT with the insert-only guard. Because deployed code currently inserts/upserts application row after saving photos, transaction ordering must be refactored carefully to avoid changing the intended stage or resetting status on an error. The entire operation must roll back atomically on any denied photo.
3. Do not allow an old route, helper, or import to retain direct document UPSERT. Use both code search and a runtime test of the original route; the current regex scanner is an extra guard, not proof that every dynamic SQL route was found.
4. For dispatcher replacement, reuse **existing Telegram server auth** `auth()`, `core.is_admin(uid)`, and deployed, decoded and size-checked `read_photos` pipeline; never trust any header, role, `uid` or image bytes from the synthetic test app. Include an appropriate CSRF/replay policy. Validate existing document and expected current SHA inside the same `BEGIN IMMEDIATE` transaction, then replace, invalidate the review and append audit atomically. Review/action endpoints are not installed.
5. Before enabling, test concurrent requests across **different SQLite connections**, all existing legacy endpoints, read permissions, same-stage resubmissions without a new image, malformed photo uploads, rejected reviews, dispatcher replacement, and end-to-end stage transitions.
6. Schema migration and rollout require a verified backup, readback, rollback procedure, and explicit deployment approval; no live migration is permitted by this task.

## Scope and caveats

- The TESTING-only Flask harness is a behavioral integration prototype, not a deployable source patch to PythonAnywhere.
- The synthetic validator accepts fake bytes; production image validation is not implemented here.
- The existing production route is **not protected yet**. Current real photos, pilot status, schema, payment and bookings are unchanged.
- All GitHub modifications are in `feature/issue-30-document-review-offline-20261117`, with no main merge.
