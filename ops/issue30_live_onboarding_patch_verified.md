# Issue #30 — verified offline patch of deployed two-stage onboarding

Date: 2026-11-17. GitHub Actions run **43978721066** — all three jobs successful.

## What was verified

- PythonAnywhere GET-only fetched deployed `pd_onboarding.py` using the preconfigured `PA_API_TOKEN`. A hard SHA-256 check required `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b`; stale or changed source fails closed.
- `pd_issue30_patch_live_onboarding_offline.py` produced a *patched copy only in GitHub Actions runner memory* from exact deployed source. No patched source was deployed, uploaded to PythonAnywhere, or saved to GitHub artifacts.
- Patch moves existing application UPSERT **before** the photo loop, under the original `BEGIN IMMEDIATE`, and replaces unsafe `pd_driver_documents` `ON CONFLICT ... DO UPDATE SET image` with `pd_issue30_store.pilot_insert_missing(...)`. The patch adds one import. The patcher checks exact structural match, absence of image UPSERT and unchanged Flask route signatures.
- `test_pd_issue30_live_onboarding_patch.py` executes the patched source in a synthetic Flask app, with actual `read_photos()` PIL normalization of synthetic 1200×800 JPEG images, a temporary SQLite DB and fake server authentication. No production database, real images or credentials are passed to Flask test clients.
- **10/10 real-handler integration tests passed** (stage1 pending→stage2→stage2 pending→final approved via existing admin route; correct original routes; pilot cannot replace stage1 files while submitting stage2; duplicate stage2 image blocks and preserves old bytes; missing files roll back; staged partial image inserts roll back atomically; unauthorized admin decision fails; repeat pending stage1 blocked; changed deployed SHA rejected).
- Baseline synthetic SQLite/Flask suite **59/59 passed** independently. Total **69/69 tests passed**, plus GET-only audit success.

## Files

- `pd_issue30_patch_live_onboarding_offline.py`: strict SHA-pinned in-memory patch generator.
- `test_pd_issue30_live_onboarding_patch.py`: exact deployed handler end-to-end test suite.
- `.github/workflows/issue30-readonly-check.yml`: separate GET-only audit, synthetic baseline and verified-live-source testing.

## Not deployed / remaining safeguards

1. This validates the **insert-only registration protection**, not full issue #30 document review rollout. Deployed dispatcher approval still uses presence-only checks; final server-side review bridge and per-document admin routes still need isolated integration.
2. Full production source might change; compare SHA before any subsequent authorized release. Fresh backup, readback and rollback are required; nothing has been approved for deployment here.
3. The live application's own transaction manager must rollback on guard exceptions. Synthetic fake core explicitly verified this; no live DB writes or rollback tests were performed.
4. Source patch is deliberately generated from GET only; not published as a replacement `pd_onboarding.py` in repository to prevent accidental production overwrite.
5. No changes to current production pilot photos, applications, admin decisions, SQLite schema, app code, payments or orders.
