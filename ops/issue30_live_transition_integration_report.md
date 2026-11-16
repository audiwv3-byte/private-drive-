# Issue #30 — deployed transitions, source-declared schema and offline integration

Date: 2026-11-17. **No live installation.** Source-only GET on PythonAnywhere; no database opened, schema migrated, file uploaded or real applicant touched.

## Evidence from deployed `pd_onboarding.py`

- PythonAnywhere HTTP GET 200; file SHA-256 `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b`. This differs from GitHub main.
- `ensure_tables` declares `pd_driver_applications` fields `telegram_id` PK, `name`, `phone`, `city`, `vehicle`, `vehicle_year`, `plate`, `seats`, `status`, `created_at`, `updated_at`. **Separately**, conditional DDL uses `PRAGMA table_info(pd_driver_applications)` and `ALTER TABLE pd_driver_applications ADD COLUMN stage INTEGER NOT NULL DEFAULT 2`.
- `pd_driver_documents` declares `telegram_id`, `side`, `image BLOB`, `updated_at`, with composite primary key (`telegram_id`, `side`).
- `pd_driver_application_decisions` records prior/new status, admin and time.
- **Limit:** These are SOURCE-DECLARED schema fields, not an independently examined live SQLite schema. No live database was opened or queried.

### Confirmed control flow

1. Initial applicant submission: stage=1, status=`pending`. Stage 1 requires the two licence images and three distinct car images.
2. Dispatcher requests `approved` while stored `stage=1`: original handler turns target into `stage2` (first-stage acceptance), not final `approved`.
3. Stage 2 application submission is selected if stored status=`stage2` or stored stage=2. It stores stage=2 and resets status to `pending`, requiring both stages' required files. `registration_back` remains optional.
4. Dispatcher requests `approved` while stored `stage=2,status=pending`: final `approved` is the intended target. The existing live handler currently uses **presence-only** document checks, not per-document reviewed SHA.
5. Live documents insertion uses `ON CONFLICT(telegram_id,side) DO UPDATE SET image=excluded.image`. **Risk**: pilot can overwrite saved images. Must change in a separately reviewed deployment before turning on reviews.
6. Migration default of `stage=2` for legacy entries is **not** proof of stage-2 submission. Old images have no per-document review and must remain pending; do not alter legacy already-approved pilots.

### Offline code only

- `pd_issue30_stage_adapter.py`: checks stage=1/pending or stage=2/pending, review schema, all required reviews and photo hashes, without any writes.
- `pd_issue30_decision_bridge.py`: server-side `core.is_admin(admin_id)` check; resolves requested `approved` into `stage2` for stage 1, or `approved` for stage 2, only after the appropriate gate; preserves replay of already-approved pilots. Other target statuses preserve original semantics.
- No call to either adapter is added to deployed `pd_onboarding.py`. The adapter does NOT register Flask routes, modify files or commit transactions.
- **Future production hook**: in the existing authorized `POST /api/admin/driver-applications/<int:applicant>/decision` handler, after current application's row has been locked with `BEGIN IMMEDIATE` but before its `UPDATE pd_driver_applications`, invoke bridge with trusted `uid` from `auth()` and `core`, replacing only the *effective* target if bridge succeeds. Existing authorization, stage transitions and decision audit remain in place. Do not wrap with a second SQLite transaction.
- This is *not deploy-ready*: review status tables/migration and admin review routes are not installed; document replacement ownership, stage2 proof for historical defaults, and UI must be reconciled against deployed source in a separate, explicit release plan.

## Synthetic verification

`python -m unittest -v test_pd_document_review_synthetic.py test_pd_issue30_stage_adapter.py test_pd_issue30_decision_bridge.py`

Temporary SQLite `:memory:`; fake bytes only. Includes invalid dispatcher, stage1→stage2 candidate, stage2 pending→final candidate, stale hashes, missing files, legacy approvals, and no implicit status mutation.

## Deployment safety

Nothing written to PythonAnywhere; no real database PRAGMA run, no images read, no status changed, no live traffic generated. An explicit future deployment authorization and backup/readback/rollback plan will be required.
