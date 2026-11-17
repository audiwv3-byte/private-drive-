# PRIVATE DRIVE — Issue #30: FINAL RELEASE CANDIDATE / staging verification

**Date:** 2026-11-17  
**Scope:** `audiwv3-byte/private-drive-` → `feature/issue-30-release-candidate-20261117`  
**Status:** **PASS for isolated staging verification; NOT APPROVED FOR PRODUCTION INSTALLATION**.  
**Strict non-production boundary:** PythonAnywhere was accessed via GET of *source files only*. No real SQLite DB access, documents/photos, applications/status changes, orders, payments, WSGI reloads, deployments or merges.

## Executive decision

Final hardened RC is **technically coherent under the tested source fingerprints** and closes two previously untested issues:

1. **Critical:** the deployed `pd_request_security.py` JSON-only `before_request` guard rejected the dispatcher document replacement multipart POST with HTTP 415. A fourth SHA-pinned source patch now permits **only** `POST /api/admin/driver-applications/<positive-id>/documents/<known-document-side>/replace` with multipart. It does not relax the original /api/driver/application exception, other POST paths, the Telegram-signed identity check or `core.is_admin` check in the endpoint.
2. **Resource/rollback:** deployed `core.db` returns raw `sqlite3.Connection`, and `with conn` does not close it. New `pd_issue30_connection.managed_core_db` commits/rolls back via original connection context, then **closes** the handle, including error paths, without breaking existing fake-core contextmanager testing.
3. **Migration stop gate:** `pd_document_review.states`, `decide` and `require_approved_documents` now fail closed when review/review-event tables are missing, instead of opportunistically creating missing tables while serving business requests.
4. **UI:** isolated Chromium tests now additionally check authenticated preview denial and rejected stale document replacement; mobile widths 390px and 320px continue to fit.

These patches are in the **feature branch only**, never installed on PythonAnywhere.

## Reproducible SHA-256 source baselines

| Live PythonAnywhere source obtained via GET only | Required SHA-256 |
|---|---|
| `pd_onboarding.py` | `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b` |
| `miniapp_server.py` | `f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4` |
| `miniapp/templates/index.html` | `d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0` |
| `pd_request_security.py` | `f1dfb0d78e3799ed0a5569986bcb811dfb71c9f8fc5504336d6365abc9789d24` |

Related deployed `Euro_Baltic_Transfer.py` core.db source SHA-256 `bf45ff7b4e097e13c2c5d12e7d22df7d8e6c274ea073867299ecfcc8d1649462` was GET-audited and AST-extracted for synthetic connection tests, **but is not overwritten by this release candidate**.

Any unexpected source SHA, mismatched import mapping, missing helper or failed test **blocks** rollout. Never copy GitHub main wholesale over deployed source.

## Manifest, provenance and evidence

**Final code CI run:** [GitHub Actions #44013417124](https://github.com/audiwv3-byte/private-drive-/actions/runs/44013417124); **all 5 jobs successful**.

| Offline suite | Verified |
|---|---|
| SQLite, migration, backup, audit, connection lifecycle | **76/76 pass** |
| SHA-pinned live-source integration, roles, multipart guard and synthetic Telegram HMAC | **63/63 pass** |
| Reproducible release manifest fail-closed tests | **7/7 pass** |
| Headless Chromium/Playwright desktop and 390/320px mobile | **10/10 pass** |
| Independent PythonAnywhere source fingerprint GET-only audit | **success** |
| **Total independently counted tests** | **156/156 pass** |

RC generator `pd_issue30_rc_build.py`: **4 source fingerprints**, **13 repository component SHA-256 entries**, **9 structural/compatibility gates**. Only `issue30_rc_manifest.json` (hashes, byte lengths and declared gates, no source contents or personal data) is uploaded as a CI artifact.

**Final SHA-256 of generated manifest at #44013417124:**  
`1a7b4bd6f5ba8e9c4b9c1988536b79703916febd9010659f94e21bb9dce67a0c`

## Complete staged deployment inventory (not installed)

**Rewritten, SHA-checked copies of four existing live source files:**
- `pd_onboarding.py`: original two-stage registration and admin decision handlers remain, with old photo UPSERT replaced by insert-only guard; document-based approval bridge inserted before original status UPDATE and audit INSERT.
- `pd_request_security.py`: surgical multipart HTTP 415 allowlist for exact admin file-replacement path only.
- `miniapp_server.py`: opt-in admin review and replacement route registration after existing onboarding register.
- `miniapp/templates/index.html`: per-side review button, server-review-dependent final approve control, stylesheet and panel JS imports.

**8 deployable new helper/asset files:**
- `pd_issue30_connection.py`
- `pd_document_review.py`
- `pd_issue30_stage_adapter.py`
- `pd_issue30_decision_bridge.py`
- `pd_issue30_document_storage_guard.py`
- `pd_issue30_admin_review_routes.py`
- `miniapp/static/pd_issue30_admin_review.js`
- `miniapp/static/pd_issue30_admin_review.css`

The remaining **5?** offline patchers are recorded in the manifest for reproducibility but **must NOT be imported in the deployed request handling path**: `pd_issue30_patch_live_onboarding_offline.py`, `pd_issue30_patch_live_dispatcher_offline.py`, `pd_issue30_patch_live_wsgi_offline.py`, `pd_issue30_patch_live_admin_html_offline.py`, `pd_issue30_patch_live_request_guard_offline.py`. Total repository components = **8 deployable files + 5 patchers = 13**. Never mount `pd_issue30_flask_integration.py` in production (TESTING-only).

## Controlled release order (future; no production action)

1. **Authorize maintenance window and freeze pilot writes:** inventory every document/photo mutation route and active WSGI/imports. Confirm expected live source SHA and correct DB target, disk space, secrets handling and rollback ownership. Booking/payment data and processes stay untouched unless separately authorized.
2. **Consistent verified backup:** with authorized write freeze, SQLite backup API snapshot including WAL state; privately save previously deployed code and WSGI/static assets; verify backup integrity, SHA-256, expected table/schema, restore a copy into a *separate* scratch DB. Do not place user images, DB bytes or tokens into GitHub artifacts.
3. **Build candidate offline:** GET-read and fingerprint four source files; apply source patchers deterministically in memory; verify manifest against reviewed SHA, syntax and all component checks; stop on drift.
4. **Transactional additive migration:** caller-owned `BEGIN IMMEDIATE`, `pd_document_review.ensure_tables(conn)` then `pd_issue30_document_storage_guard.ensure_tables(conn)`, schema readback and COMMIT. Existing pilot documents remain pending until individually reviewed; previously approved pilots are not revoked.
5. **Coordinated file staging and activation:** stage four patched originals plus eight deployable helpers/assets; verify readback hashes, module compatibility, file permissions, WSGI import routing and HTTP guards. Then controlled WSGI reload. **Never enable approval gating without admin review UI/API and migrated tables**.
6. **Smoke tests:** source/schema read-only checks first. Perform the stage1→stage2→approved workflow and failure paths only in a private staging DB with synthetic identities/photos; verify signed test Telegram initData in integrated staging, HTTP 415 not returned for permitted admin multipart, HTTP 415 returned for unrelated uploads, stale SHA denied with safe error text, non-admin denied, no unrelated permission leaks, document replacement audit and return to pending, no layout overflow on mobile.
7. **Release/rollback decision:** controlled progressive enabling only after operator approves all checks and recovery procedure. On any failure stop new pilot document actions, roll back prior application code/config and WSGI, reload and compare verified old SHA. Preserve additive review/audit tables unless separately authorized; never overwrite an active DB with a stale full snapshot, since it can discard legitimate bookings/payments.

## Remaining blockers before production

1. **Authentic integrated staging session:** tests verify Telegram HMAC mathematically using synthetic signed data, but have NOT checked a real Telegram client's initData in a separately hosted full staged application (login expiration, replay, CSRF and multipart from the target UI).
2. **HTTP error status mapping:** isolated browser mocks use 409 for stale SHA and 403 for forbidden access. Deployed `miniapp_server.py` currently handles `ValueError` (including `ReviewError`/`DocumentStorageError`) as HTTP **400**, and `PermissionError` as **401**. The UI uses non-2xx status/error text so this should remain functional, but production-compatible status mapping and error messages must be tested in integrated staging; do not claim browser mocks verified those exact deployed codes.\n3. **Full live HTML and mobile device QA:** Playwright uses the real opt-in panel JS in an isolated synthetic dispatcher HTML with mocked API semantics; it is not the entire patched production template on real Android/iPhone.
4. **Production procedure:** no authorized maintenance freeze, live DB backup, actual WSGI import/path verification after install, actual schema migration or rollback rehearsal using a private copy of production schema has been performed. Those operations remain prohibited by this request.
5. **Alternate BLOB writers/legacy application compatibility:** offline AST/code checks cover identified onboarding routes and replacement endpoint, but a comprehensive operator-reviewed inventory of every deployed upload pathway is still required. Website-only registration without Telegram initData is separate and not validated by Issue #30.
6. **Approval operator workflow:** a rejected file is not replaceable by a pilot; only authenticated dispatcher replacement is permitted by this policy. Operator procedures for correction, notice and verified image viewing must be validated before enabling applications.

### Verdict

**RC2 (hardened, staging-only) is verified and reproducible.** It is **NOT** certified for production installation and no production changes were made. The next permissible action is a separately authorized **isolated full staging** with real test Telegram credentials, synthetic pilot files, and a real browser, followed by an explicit launch decision.
