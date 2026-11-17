> **SUPERSEDED (2026-11-17):** Этот документ RC1 содержит устаревший состав из трёх исходных файлов и старый SHA-256 манифеста. Актуальный безопасный кандидат — [RC2 final](issue30_final_rc2_verification.md). **Не использовать RC1 для установки.**\n\n# PRIVATE DRIVE Issue #30 — Release Candidate RC1

**State: STAGING-ONLY — NOT AUTHORIZED FOR PRODUCTION INSTALLATION**

Prepared: 2026-11-17. Base branch: `feature/issue-30-document-review-offline-20261117`. Candidate branch: `feature/issue-30-release-candidate-20261117`. This candidate is a **reproducible, source-SHA-pinned package definition and an isolated test suite**, not an executable production deploy script. No source, databases, pilot files, images, or statuses on PythonAnywhere were modified.

## 1. Exact verified release inventory

The source-of-truth deployed copy is not identical to GitHub main. Never overwrite it with older repository files.

| Deployed original (GET-only, no data) | Original SHA-256 |
| --- | --- |
| `pd_onboarding.py` | `7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b` |
| `miniapp_server.py` | `f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4` |
| `miniapp/templates/index.html` | `d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0` |

`pd_issue30_rc_build.py` requires an exact SHA-256 match for **all three** deployed inputs and produces:
- source-pinned, in-memory patched `pd_onboarding.py` (pilot insert-only + per-document dispatcher gate);
- source-pinned, in-memory patched `miniapp_server.py` (opt-in admin review/replacement route registration);
- source-pinned, in-memory patched `miniapp/templates/index.html` (per-side review, approval gate, stylesheet loading);
- verified SHA-256 and bytes for **11** repository components: `pd_document_review.py`, `pd_issue30_stage_adapter.py`, `pd_issue30_decision_bridge.py`, `pd_issue30_document_storage_guard.py`, `pd_issue30_admin_review_routes.py`, `miniapp/static/pd_issue30_admin_review.js`, `miniapp/static/pd_issue30_admin_review.css`, and the four offline patch-generation modules.

The actual code and patched source are **never uploaded as a CI artifact**. CI publishes only `issue30_rc_manifest.json` containing baseline and patched SHA-256, component hashes, expected migration list and safety checks. The published manifest SHA-256 is `a519f05c38129e4f4b4ea4e158a577bef4c14a308b05851dbe5695cf111d9397` from workflow run `44012170530`, commit `c5074ac5` (the RC scripts/components at that commit). This manifest is **not an authorization to deploy**.

Eight reproducible consistency checks: pilot storage guard exists; dispatcher bridge exists; no old image UPSERT; admin registration occurs once; review panel is mounted once; final approval checks server review metadata; CSS and JS are referenced in patched HTML. HTML CSS wiring was corrected specifically in this RC branch.

## 2. Verified dependencies

- `pd_onboarding` depends on `pd_issue30_document_storage_guard` and `pd_issue30_decision_bridge`.
- The bridge depends on `pd_issue30_stage_adapter`, which depends on `pd_document_review`.
- `pd_issue30_admin_review_routes.register(app,core,auth,pd_onboarding.read_photos)` requires existing server-verified Telegram auth, core admin role checks and production image normalization. **Never mount the synthetic fixture in production**.
- Dispatcher UI needs both `/static/pd_issue30_admin_review.js` and `/static/pd_issue30_admin_review.css` plus the metadata, review, and replace routes.
- Database requires `pd_document_review.ensure_tables` (review + decision event) and `pd_issue30_document_storage_guard.ensure_tables` (replacement event), in this order. Both are additive; do not backfill implicit approvals.

## 3. Future installation order (explicit authorization required; nothing below was done)

1. **Preflight stop gate.** Confirm authorized maintenance window, owner/operator, server, active WSGI imports, exact source hashes, target DB path, available storage, and all document writer endpoints. A single mismatch blocks the change. Freeze new pilot registration/uploads/reviews during swap, preserving existing bookings/payments.
2. **Verified backup.** Under controlled DB write freeze, make a consistent snapshot using SQLite backup API; back up deployed `pd_onboarding.py`, `miniapp_server.py`, `miniapp/templates/index.html`, WSGI configuration, relevant static assets and configs. Record SHA-256, private readback, `PRAGMA integrity_check` and test restoration to a separate path. Never copy an open WAL DB as a raw single file.
3. **Dry-run release build.** Recalculate all three live SHA-256 preconditions and run `pd_issue30_rc_build.py`; compare manifest SHA-256 against reviewed RC; verify `py_compile` and generated HTML/UI syntax, file permissions and import map in isolated staging.
4. **Migration while paused.** With a single caller-owned `BEGIN IMMEDIATE`, apply additive review, review-event and replacement-event table migrations; inspect schema, then COMMIT. No row changes or automatic document approvals.
5. **Stage and switch as one unit.** Make all seven helper/asset files available plus the three patched originals together. Verify exact content SHA on target, route registrations, deployment health; perform controlled service reload. Do not activate the server-side approval gate before the admin review UI/API and schema exist.
6. **Smoke checks on authorized test identities only.** Non-mutating service probes first; then on an isolated staging DB, test required stage-1 reviews → `stage2`, required stage-2 reviews → `approved`, unauthorized staff/pilot denial, rejected or stale SHA blocks, per-file replacement returns to pending, private file access, mobile 390/320 px, error feedback, and no live payment or order effects. Never create real user records to smoke-test.
7. **Release decision.** Only enable real registration/reviews after all checks, approved monitoring and a rollback decision point.

## 4. Rollback procedure (future; NO execution)

1. Stop **new** pilot registrations/document reviews and preserve immutable event logs.
2. Restore verified prior **application sources, static HTML, CSS/JS and WSGI bindings**, then controlled reload. Confirm original SHA-256 and existing health. Do not blindly drop newly added audit tables; older app code can ignore additive schema.
3. Avoid full-database snapshot restore unless separately authorized after accounting for any intervening legitimate writes: overwriting a live database could lose bookings/payments. Prefer code rollback and additive-schema retention.
4. If DB migration fails before commit, ROLLBACK that transaction; do not start the new code. If severe schema/integrity damage occurs, use a separately approved recovery procedure and verified offline snapshot.
5. Non-mutating smoke test of prior admin/passenger/pilot access and payment/order endpoints; record incident and restore workflows only when safe.

## 5. Verification and remaining hard gates

- Baseline synthetic Flask/SQLite tests, SHA-pinned deployed-source/WSGI/HTML integration, and isolated Chromium/Playwright admin review tests have been exercised in CI. Exact counts and current run conclusions must be verified against the GitHub Actions workflow; this file does not itself constitute test evidence.
- New RC manifest has **7 fail-closed tests** covering reproducibility, tampered baseline SHA, absent/unexpected files, missing dependencies and helper content hashes; the manifest builder performs 8 feature consistency checks.
- **Not tested against a production signed Telegram session or genuine user data.** Test fixtures substitute fake roles, generated photos and synthetic API responses. Real signed initData, CSRF/replay behavior, source drift, complete alternate photo-write path inventory and final mobile on-device QA must be independently reviewed before rollout.
- The RC is intentionally **staging-only**, and no PythonAnywhere upload, WebApp reload, migration, document/data read or write, real pilot approval, or payment was performed.

## 6. Files and evidence

- RC builder: `pd_issue30_rc_build.py`
- RC verification: `test_pd_issue30_rc_manifest.py`
- Existing CI workflow: `.github/workflows/issue30-readonly-check.yml`
- Isolated browser: `tests/issue30/browser_fixture.html`, `tests/issue30/browser.spec.mjs`, `tests/issue30/playwright.config.mjs`
- Prior validated plan: `ops/issue30_coordinated_rollout_plan.md`
- CI run: `https://github.com/audiwv3-byte/private-drive-/actions/runs/44012170530`

**Release classification: RC1 verified for isolated staging, NOT certified/authorized for production deployment.**
