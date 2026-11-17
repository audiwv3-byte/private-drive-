# PRIVATE DRIVE — Issue #30: single coordinated release plan (PREPARATION ONLY)

Date: 2026-11-17. This is a **non-executable deployment plan**, not an authorization to update PythonAnywhere. Feature branch `feature/issue-30-document-review-offline-20261117` only. Do NOT merge this branch or run production steps without a separate, explicit rollout authorization.

## Baseline and invariants

- Production source observed via official PythonAnywhere **GET** API: `/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_onboarding.py`, SHA-256 `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b`. Any mismatch = **STOP**, redo comparison and approval. GitHub `main` is not the live release source.
- Source `miniapp_server.py` and `miniapp/templates/index.html` have **different** fingerprints from GitHub, and are outside this automated patch. Do not overwrite them. Changes to existing UI or any server import/registration need a separately reviewed release patch and test.
- No writes to live users, orders, documents, status, payment, existing DB schema or PythonAnywhere occurred in preparing this plan.
- Existing pilot status and previously approved pilot rights are retained; **no backfill of document approval**. Historical files without explicit review are `pending` only for new review decisions. Already approved pilots are not silently demoted.
- Explicit launch risk: deploying the guard **without** review schema + admin per-side decision UI would strand applications. All activation must occur in one controlled maintenance window, with validated rollback.

## Dependency map

1. `pd_document_review.py`: `ensure_tables` for `pd_document_reviews` + `pd_document_review_events`, `states`, `decide`, `register(app,core,auth)`; requires existing `pd_driver_applications`, `pd_driver_documents`; uses Flask only when opt-in register is called.
2. `pd_issue30_document_storage_guard.py`: `ensure_tables` for `pd_document_replacements`; `pilot_insert_missing`, `dispatcher_replace`; imports `pd_document_review`; caller owns `BEGIN IMMEDIATE`, commit/rollback.
3. `pd_issue30_stage_adapter.py`: imports `pd_document_review` and validates review schema/stage and required approved current SHA.
4. `pd_issue30_decision_bridge.py`: imports stage adapter + review module; `guard_admin_approval`; relies on authenticated core admin check.
5. `pd_issue30_patch_live_onboarding_offline.py`: SHA-pinned in-memory rewrite of deployed application handler, changes only image UPSERT to guarded insert after application row write, same transaction; adds storage guard import.
6. `pd_issue30_patch_live_dispatcher_offline.py`: composes onboarding patch; replaces existing *presence-only* approval logic with bridge guard while preserving existing `POST /api/admin/driver-applications/<int:applicant>/decision`, same transaction and decision journal.
7. Admin endpoints in `pd_document_review.register(app, core, auth)` and dispatcher replacement route require opt-in integration. The synthetic `pd_issue30_flask_integration.py` is **TESTING-only** and must never be exposed as production. Existing `auth()`, permissions and real JPEG normalization must be used. **No complete production dispatcher-replacement route patch is delivered yet**, so do not claim rollout-ready.

## Release phase gates — proposed future sequence (do NOT execute now)

**Gate 0: explicit scope approval + maintenance window.** Authorized operator identifies target process, exact deployed source root, DB path, webapp WSGI entry, customer-safe maintenance state, pilot/staff communication, and application restart plan. Freeze new pilot uploads, per-file decisions and dispatcher approvals for snapshot/migration. Leave other booking/payment flows unaffected; never block payments without authorization.

**Gate 1: baseline evidence and backups before writes.**
- GET-only refingerprint `pd_onboarding.py`; require exact SHA above; inspect the deployed importing/WSGI entry and other source dependencies via GET only.
- Read-only inventory of *filenames and schemas*, not user records, plus enumerate import bindings, existing role checks and all direct `INSERT OR REPLACE` / `UPSERT` BLOB writers. Refuse any unaccounted write path.
- Under a controlled maintenance freeze, take an encrypted, access-limited snapshot of database using SQLite **backup API** or `VACUUM INTO` (not a raw copy of a possibly active WAL DB); back up relevant source, WSGI and configuration with restrictive permissions. No secrets in GitHub, runner logs or artifacts.
- Verify SHA-256 for each backup, readback, `PRAGMA integrity_check` on the **offline backup copy**, restore the snapshot to a *separate* scratch path, verify expected table counts/schema and compare status/document hashes **in private offline environment**. This is an operational future action; it has **NOT** been carried out on live data.

**Gate 2: prepare release from exact matching production code.**
- Generate both patched application and dispatcher logic from SHA-verified deployed `pd_onboarding.py` in a private staging environment. Review the diff. Never copy GitHub `main` in place of production.
- Install mutually compatible helper modules at version-pinned paths; verify import resolution; run `compileall` or `py_compile` on the release payload. **No production code** should import `test_pd_issue30_*` or the synthetic Flask fixture.
- Review every writer of document BLOBs: remove/bypass unsafe original UPSERT, ensure no unguarded route remains, ensure normalized image size/type and per-side authorization. Add production admin replacement and review routes with auth `auth()`, `core.is_admin`, SHA stale rejection, atomic review invalidation and audit. The current synthetic registration of the replacement route is not a production endpoint.

**Gate 3: migrate while paused, then activate together.**
- Database transaction `BEGIN IMMEDIATE` owned by one migration process; run `pd_document_review.ensure_tables(conn)` and `pd_issue30_document_storage_guard.ensure_tables(conn)`, schema readback, `COMMIT`; on failure `ROLLBACK` and STOP. Never automatically approve historical documents.
- Prepare and validate new admin routes and necessary admin UI **before** enabling review gating; ensure review API is reachable, session/admin authorized, forbidden to pilot, private media preview restricted.
- Stage all files atomically with SHA readback and controlled restart: replace the production source **only as an approved unit** after prerequisites and isolated tests succeed. No partial enablement of guard without review tooling.
- Maintain service pause until every Gate 4 smoke test passes.

**Gate 4: smoke tests without real business mutations.**
- Existing `GET` route registrations and stage enum compatibility; pilot/public attempts to use admin routes denied; dispatcher can list review metadata, but no photo bytes leaked by metadata API.
- In a staging copy with fake accounts/files: complete stage1 five files -> individual admin approval -> stage2; stage2 five required files -> per-file approval -> final status; `registration_back` optional; refusal for missing/rejected/current SHA mismatch; no duplicate image or unauthorized replacement.
- In production only non-mutating status and route diagnostics against internal allowlisted test identities **if preauthorized**. Do not create actual applications, modify real statuses, trigger notifications or payments merely for smoke testing.
- Confirm live app logs, controlled reload and healthy response. If any release gate fails, activate rollback.

**Gate 5: rollback rules (future operation only).**
- Pause new review decisions/uploads, preserve immutable audit evidence. Stop/restart only the target service with authorized procedures.
- Restore code/WSGI/config from **verified backups** and check original SHA-256. If schema migration has been applied but only additional nullable/new tables exist, prefer *additive schema retention* and old application code rollback, rather than dropping any table; any restoration of a full DB snapshot would discard new legitimate writes and needs explicit, separate recovery approval. **Never blindly overwrite an active DB**.
- Verify access control, existing pilot applications, booking/payment endpoints (read-only checks), process health and integrity. Record incident and recovery log, unfreeze when cleared.

## Hard blockers / remaining implementation

- Actual production dispatcher replacement endpoint and its frontend flows/CSRF policy are not yet integrated with the verified live onboarding source. Existing synthetic-only route is not deployable.
- Per-side admin UI and error mapping need end-to-end validation against real deployed HTML; no change to live HTML is authorized here.
- The live `core.db` transaction context manager's failure/rollback behavior needs inspection/compatibility validation. Synthetic fixture rollback is not enough.
- Live WSGI import mapping, all alternate document write paths, backup destination, rollback permissions, maintenance plan and migrations are not confirmed. Do not execute release without closing these gaps.
- Any SHA mismatch or unverified dependency = fail closed.

## Offline evidence

GitHub Actions workflow includes GET-only source verification, SHA-pinned ephemeral Flask testing (82 passing cases in prior run `44008144034`) and new synthetic-only backup/migration/rollback tests in `test_pd_issue30_release_readiness_offline.py`. Run status for the new tests must be checked separately; prior test counts must not be represented as a new result.

**This document and all code modifications are feature-branch only. No production deployment or database read/write.**
