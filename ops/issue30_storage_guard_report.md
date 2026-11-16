# PRIVATE DRIVE issue #30 — Pilot insert-only and dispatcher replacement protection

Date: 2026-11-17. Only feature-branch source and isolated GitHub Actions runners were changed. NO production PythonAnywhere files, DBs, photos, statuses, payments or orders were modified.

## New offline files

- `pd_issue30_document_storage_guard.py`: two **unregistered** Python functions for caller-owned `BEGIN IMMEDIATE` transactions.
  - `pilot_insert_missing(conn, applicant, side, image)`: only new `(telegram_id, side)` keys; `INSERT ... ON CONFLICT DO NOTHING` and `rowcount == 1`. Does NOT overwrite. Requires a pending stage-1 application for first-stage sides or a stage-2 application for second-stage sides; existing photos are immutable to pilot.
  - `dispatcher_replace(conn, applicant, side, image, expected_sha256, actor_id, is_admin)`: server-side dispatcher permission callback; existing document required; exact expected SHA-256 compared under caller's transaction; deny stale/invalid SHA; update image and clear any prior per-document review, making its state **pending**; append immutable metadata-only replacement audit with previous/new SHA, actor, time. Replay of identical content is a no-op. Approved/inactive pilot files cannot be replaced.
  - `ensure_tables(conn)` is an explicit migration helper **not called on production**; adds `pd_document_replacements` only, with no modification of historical BLOBs.
- `test_pd_issue30_document_storage_guard.py`: 19 in-memory SQLite test cases; no credentials, network or real files. Checks pilot first upload, repeated upload denial (same/different bytes), first/second stage authorization, dispatcher role, stale SHA, invalid sides, optional review schema, approved pilot denial, exact image and review rollback on failed audit insert, and append-only metadata.
- Workflow updated to run baseline + stage adapter + decision bridge + storage tests; READ-ONLY PythonAnywhere audit remains GET-only.

## Production integration constraints — NOT implemented

1. Replace **all** deployed pilot file writing paths that currently use `ON CONFLICT ... DO UPDATE` in `pd_onboarding.py`; leaving any old route active bypasses the guard.
2. Verify live code and file processing pipeline: always pass image data already validated/normalized by deployed `read_photos()`; validate size, MIME, actual decoded image, decompression safety, stage and correct side. This isolated guard only checks nonempty Python bytes and does not validate images.
3. Call the guard while holding the **same** `BEGIN IMMEDIATE` transaction as application stage/status read and document write; rollback the whole transaction on error. No nested `BEGIN`; never commit between SHA check, BLOB change, review invalidation and audit insert.
4. Restrict dispatcher replacement route to actual server-authenticated admin ID; never trust request JSON role or `is_admin` callback supplied from clients. Add CSRF/session controls appropriate to deployed auth method. The module itself does not implement the HTTP route.
5. Compare the live PythonAnywhere source SHA with approved baseline immediately before installation; take verified backup and independent read-back, prepare rollback. No migration or deployment without explicit authorization.
6. Preserve previously approved pilots and existing images; make replacement of an approved pilot a separate authorized re-review workflow rather than a silent edit.
7. Integrate with the existing per-document decision endpoint and `pd_issue30_decision_bridge.py` before enabling release; route-level auth tests, concurrent connections, and race tests still required.

## Verification

Workflow GitHub Actions run 43976651443: synthetic job reported `Ran 47 tests ... OK`. Includes 28 prior synthetic tests and 19 new storage tests. The module has NOT been installed, registered, or tested against live traffic.

## Safety

Only synthetic SQLite and fake bytes in GitHub Actions. PythonAnywhere audit uses GET on server-side SOURCE ONLY. No personal data or production database read.
