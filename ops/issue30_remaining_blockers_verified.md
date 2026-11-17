# PRIVATE DRIVE / Issue #30 — final predeployment blocker audit (2026-11-17)

Scope: GitHub feature branch **only**. The only PythonAnywhere operations were GET of source files. **No production migrations, reloads, photo reads, database connections, status changes, payments, or installations.**

## Verified source fingerprints

| Deployed source | SHA-256 pinned in offline patches |
| --- | --- |
| `pd_onboarding.py` | `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b` |
| `Euro_Baltic_Transfer.py` (core) | `bf45ff7b4e097e13c2c5d12e7d22df7d8e6c274ea073867299ecfcc8d1649462` |
| `miniapp_server.py` (WSGI) | `f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4` |
| `miniapp/templates/index.html` | `d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0` |

All SHA-pinned generator functions abort if their live-source input differs. **Do not deploy any GitHub-main file over a different deployed file.**

## Finding 1 — live authentication and admin replacement route

The deployed `miniapp_server.auth()` uses server-side Telegram `X-Telegram-Init-Data` verification. Admin checks use `core.is_admin(uid)`. The deployed `POST /api/admin/driver-applications/<int:applicant>/decision` remains intact.

New opt-in, **not registered on PythonAnywhere**, `pd_issue30_admin_review_routes.py` provides:
- `GET /api/admin/driver-applications/<int:applicant>/document-reviews`: admin-only document status and current SHA (metadata only, no BLOB).
- `POST /api/admin/driver-applications/<int:applicant>/document-reviews/<side>`: admin-only per-file approval/rejection via `pd_document_review.register`.
- `POST /api/admin/driver-applications/<int:applicant>/documents/<side>/replace`: admin-only exact-SHA checked replacement; calls deployed PIL `read_photos((side,))` after admin authentication, then `pd_issue30_document_storage_guard.dispatcher_replace` in existing SQLite `BEGIN IMMEDIATE`, stores audit and invalidates prior review. No request-supplied identity or role is trusted.
- Source-pinned `pd_issue30_patch_live_wsgi_offline.py` adds a single opt-in registration call after existing `pd_onboarding.register(app,core,auth)` in an **in-memory patched copy** of deployed `miniapp_server.py`.
- Synthetic Flask tests verify permitted/forbidden roles, metadata privacy, stale SHA denial, audit, rollback on failed audit, and full stage1→stage2→approved sequence.

## Finding 2 — actual `core.db` transaction behavior

From GET-only source inspection, deployed `core.db(path)` returns `sqlite3.connect(str(path),timeout=20)`, sets `sqlite3.Row` and `PRAGMA busy_timeout=20000`. It returns a **connection**, not a separately decorated contextmanager. Python `with conn:` commits on success and rolls back on exception; **it does not itself close the connection**. New replacement route explicitly commits/rolls back inside the existing connection context to keep transaction boundaries clear. A release review must confirm connection cleanup in all production callers.

The exact `db` function was AST-extracted from GET-fetched deployed source, compiled in memory with synthetic SQLite only, and tested for commit, rollback, and PRAGMA/row factory. No production DB was opened.

## Finding 3 — deployed dispatcher UI needs new checks

Deployed `pdLoadDriverApplications()` renders `pdDriverApplicationsList` with approve buttons based on *file presence*; it did not call per-side `document-reviews`. Code-only gate alone would confuse dispatchers.

Prepared but **not applied**:
- `miniapp/static/pd_issue30_admin_review.js`: opt-in per-pilot review panel (11 document sides, existing SHA, approve/reject reason, admin replacement). Uses `textContent` instead of HTML injection and protected fetch for photo preview including `X-Telegram-Init-Data`; only safe JPEG blob URLs, revoked after viewing.
- `pd_issue30_patch_live_admin_html_offline.py`: SHA-pinned in-memory template modification that adds a `Проверить документы` button for each pilot, calls admin metadata API and disables legacy `Одобрить` until all stage-required sides explicitly have `approved` server statuses. Preserves other dispatcher controls.
- `test_pd_issue30_live_admin_html_patch.py`: source-pinned HTML patch contract checks; **not** a browser/UI visual test.
- No live HTML, static assets or WSGI were updated; JS source in feature branch requires an **authorized coordinated deployment** and manual UI review.

## GitHub Actions evidence

Workflow run `44009870190`: 3/3 jobs success.
- Synthetic SQLite/Flask/backup/recovery suites: **69 tests, OK**.
- SHA-pinned live handler + admin routes + live core.db + WSGI + live dispatcher HTML contract suites, all using GET-only source and synthetic runtime: **47 tests, OK**.
- GET-only PythonAnywhere source audit: success.
- Total: **116 tests passed**. JavaScript module syntax check also passed.

## Remaining launch controls (do not skip)

1. This is an **isolated code and static-template compatibility test**. Browser E2E with actual Telegram signed initData, CSS/layout, focus, accessibility, mobile and error behavior still requires staging review, not synthetic client claims.
2. Before release, explicitly verify signed Telegram initData expiry/replay and cross-origin request protection for new multipart replacement route; require backend to reject forged roles, malformed images and long sessions. The test fixture uses synthetic identity, never production headers.
3. Additive review/replacement audit table migration must be verified and backed up; no implicit approval for legacy photos; preserve old approved pilot accounts.
4. Confirm all legacy photo write paths are removed and all stage transitions/permission checks still align with current server version.
5. Coordinate WSGI imports, helper files, admin JS, patched HTML and schema migration in a **single** future approved maintenance window. Deploying any one alone can block application approvals.
6. Require verified **fresh** source fingerprints, backup integrity/readback, rollback and real service authorization. No production operations requested or performed here.

Status: **ready for controlled staging review, NOT approved for production launch**.
