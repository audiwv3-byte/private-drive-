# Issue #30 — dispatcher per-document approval gate: offline verification

Date: 2026-11-17. **No PythonAnywhere changes.**

## Verified result

GitHub Actions workflow run `44008144034` completed **successfully**:
- Existing isolated synthetic SQLite/Flask suite: **59/59 passed**
- Source-SHA-pinned Flask suite against GET-only retrieved *live* `pd_onboarding.py`, with combined registration + dispatcher patches applied **only in runner memory**: **23/23 passed** (10 prior registration checks plus 13 new dispatcher checks)
- Independent PythonAnywhere source audit: success, read-only GET only
- Total **82/82** test cases passed.

## New source files (feature branch only)

- `pd_issue30_patch_live_dispatcher_offline.py`: first applies existing SHA-256-pinned registration patch; replaces only the legacy presence-only dispatcher approval block in the existing `POST /api/admin/driver-applications/<int:applicant>/decision`. The single inserted call is `pd_issue30_bridge.guard_admin_approval(c, applicant, target, uid, core)`, within the **same** existing `BEGIN IMMEDIATE` transaction, before the original status `UPDATE` and decision-audit `INSERT`. It does not register, rename, remove or add Flask routes. Patcher fails closed on source fingerprint mismatch or unexpected AST/source layout, then verifies unchanged Flask route signatures.
- `test_pd_issue30_live_dispatcher_patch.py`: 13 Flask + synthetic temporary SQLite checks of the **combined** patched source, including both stage transitions, explicit individual document approvals, missing/rejected/stale document denials, unauthorized dispatcher, rollback on audit failure, missing review schema and route preservation.
- Previously tested `pd_issue30_decision_bridge.py`, `pd_issue30_stage_adapter.py` and `pd_document_review.py` are reused without changing their logic or authorizations.

## Approval semantics tested

- Stage 1 `pending, stage=1` and all five FIRST docs explicitly reviewed with current SHA-256 → original decision route changes status to `stage2`, not `approved`.
- Stage 2 submission `pending, stage=2` and all five SECOND **plus all five FIRST** docs individually approved with matching current SHA-256 → `approved`.
- Unreviewed, rejected, missing or superseded files → deny; application status and existing decision log unchanged.
- Non-admin caller → deny through original `auth()` and `core.is_admin(uid)`; bridge independently verifies admin role.
- Exception on original `pd_driver_application_decisions` audit INSERT → status UPDATE rolled back atomically in synthetic core.
- Already approved legacy pilots are not automatically revoked by the bridge.

## Production blockers / scope limitations

1. **NOT deployed.** The working `pd_onboarding.py` still contains the unsafe image UPSERT and the presence-only approval rules until a separately authorized release.
2. Per-document review schema and admin review HTTP endpoints are not installed; deploy **no** approval gate in isolation, because it would block all new applications.
3. Synthetic tests use simulated authenticated users, generated JPEGs and an isolated SQLite file. They establish compatibility with the identified source version, not operational production readiness.
4. Before any release: ensure verified backup/readback, migration verification, pilot/admin authorization and private document access, race testing against real app workflow, rollback mechanism and explicit authorization; revalidate deployed SHA-256.
5. No real photos, applications, statuses, orders, payments or DB rows were read or written. PythonAnywhere access was GET of source only.
