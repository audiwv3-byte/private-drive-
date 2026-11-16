# Issue #30 — live GET-only comparison and offline adapter (2026-11-17)

## Evidence
- GitHub Actions GET-only audit fetched **live** `pd_onboarding.py` (HTTP 200, 13093 B, SHA-256 `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b`). It differs from repository `main`.
- Live `miniapp_server.py` and HTML also differ from GitHub. **Do not deploy main**.
- AST-only live probe confirms `stage2`, `pending`, `approved`, `rejected` are used in registration/dispatcher decision; stage-2 document types occur in deployed code.
- Existing GET document and POST application/admin-decision URLs exist. No per-document review tables/routes are present.
- Live files were inspected only via PythonAnywhere API `GET /files/path...`. No source bodies, BLOBs or DB records were uploaded to GitHub.

## Offline deliverables
- `pd_issue30_stage_adapter.py`: no Flask import/registration, no DB writing or status transition. Guards stage-1 and final transitions by requiring explicit per-document approvals and verifying the current document SHA. Final stage *also* requires a separately verified authoritative stage-2-submission flag. Refuses when review/audit schema is absent.
- `test_pd_issue30_stage_adapter.py`: in-memory SQLite tests covering missing/rejected/stale documents, stage-2 submission, status preconditions, missing migration, legacy already-approved pilots and no implicit status updates.
- `.github/workflows/issue30-readonly-check.yml`: offline tests and an independent GET-only source audit in feature branch.

## Production integration blockers (must resolve before enabling)
1. Map exact deployed stage-1->stage-2->pending->approved transitions and authoritative persisted proof of stage-2 submission. **The adapter's current status assumption is provisional** and intentionally fails closed; not tested against live transaction control flow.
2. Determine live DB schema and legacy upload/replace behavior through safe schema-only evidence (no real data). Existing photo UPSERT may let pilot replace already-stored photos: close this hole before enabling decisions.
3. Ensure server-side dispatcher access is checked on **every** new endpoint. Adapter alone is not an auth layer.
4. Wrap final-decision guard in the deployed existing `BEGIN IMMEDIATE` approval transaction and also guard alternative paths that set approved; don't patch `main` as if it were deployed.
5. Do not silently revoke legacy approved pilots or infer approvals for existing unreviewed photos.
6. Implement GET-only/private preview UI and per-side audit (future isolated changes); no automated release to PythonAnywhere.

## Safety boundary
Feature branch only; no production migrations, writes, reloads, document decisions, status changes, booking or payment operations. Successful unit tests validate synthetic contracts **not** deployed compatibility.
