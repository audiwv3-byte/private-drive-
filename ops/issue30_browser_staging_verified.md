# PRIVATE DRIVE — Issue #30: isolated Chromium dispatcher browser validation

Verified 2026-11-17. **Feature-branch-only; NO PythonAnywhere deployments, DB operations, genuine pilot files or statuses.**

## GitHub Actions evidence

[Run 44011063739](https://github.com/audiwv3-byte/private-drive-/actions/runs/44011063739): **4/4 jobs success**.

- **8/8 Playwright Chromium browser tests passed** (desktop plus 390px and 320px mobile viewports).
- **69/69** baseline synthetic Flask/SQLite, backups, migration tests passed.
- **47/47** SHA-pinned GET-only deployed-source integration, admin review, core.db, WSGI and HTML contract tests passed.
- Independent **PythonAnywhere GET-only source audit** passed. JavaScript syntax validation passed.
- Combined **124/124 tests passed** across independent suites. No paid testing tools/services were invoked; uses open-source Playwright, Chromium and GitHub Actions runner, subject to account's CI allowances.

## Standalone isolated browser fixture

- `tests/issue30/browser_fixture.html`: minimal synthetic admin cabinet UI and staged application #1001. It imports the **real feature-branch** `miniapp/static/pd_issue30_admin_review.js` and `miniapp/static/pd_issue30_admin_review.css`, not a rewritten mock panel.
- `tests/issue30/browser.spec.mjs`: Playwright tests intercept **all** `/api/**` calls using ephemeral test-local JavaScript fixtures. No API call reaches PythonAnywhere or a real PRIVATE DRIVE instance. A fake Telegram token is used solely as an assertion that frontend sends the expected header; this does **not** validate Telegram cryptographic signatures or authorization.
- `tests/issue30/playwright.config.mjs`: Chromium headless on localhost HTTP server `127.0.0.1:8765`, started from repository root; no public staging URL, server database or real user session.
- GitHub Actions browser job on `ubuntu-24.04`, `@playwright/test@1.55.1`; installs local browser, validates DOM; failure screenshots/traces kept as short-lived GitHub Actions artifacts only on failure.

## Browser assertions

1. Stage-1 main `Одобрить заявку` button disabled until **each of five** required documents is explicitly approved. Server review updates immediately refresh button state in the fixture, no full page reload.
2. Missing document has **disabled** individual approval and replacement controls; main approval remains disabled.
3. Rejection with a reason displays rejected status. A subsequent synthetic **HTTP 409 stale SHA** shows explicit error text, does not silently approve, and restores control availability.
4. Admin replacement sends multipart request with expected SHA, and returns replaced document to **pending** status.
5. Stage-2 `registration_back` optional and missing is disabled; it does **not** block final approval if five required stage-2 documents and first-stage documents have been approved.
6. Synthetic **HTTP 403** surfaces `Доступ запрещён` and keeps final approval disabled.
7. **390 px mobile viewport**: no horizontal overflow, touch targets ≥40 px, controls respond.
8. **320 px mobile viewport**: same checks.

The first browser run identified a **synthetic mock contract bug**: its missing optional file wrongly carried a SHA-256 (real `pd_document_review.states()` returns only `{status:'missing'}`). Fixed fixture; **final run: 8/8 pass**. Previous failed test runs must not be confused with final success.

## UX change in feature branch

- `pd_issue30_admin_review.js` now emits `pd-issue30-review-updated` after refreshing document statuses; initial 403 errors are displayed in the panel.
- `pd_issue30_patch_live_admin_html_offline.py` subscribes to the event and updates the existing dispatcher `Одобрить` control from server review statuses, clearing stale blocked hints when eligible. This is an **offline SHA-pinned source generator**, NOT a deployed HTML update.
- Responsive CSS isolated to `pd-issue30-* ` classes; synthetic mobile browser tests validate 390/320 px.
- Preview uses authenticated fetch with `X-Telegram-Init-Data`, not direct unauthenticated URL navigation.

## Manual reproduction (in a disposable checkout)

From the feature branch repository root:

```bash
npm install --no-save --package-lock=false @playwright/test@1.55.1
npx playwright install --with-deps chromium
npx playwright test --config tests/issue30/playwright.config.mjs
```

Do not use a real Telegram token, a production API URL or genuine documents in the test fixture.

## Readiness limitation

This test **does not** run the entire deployed HTML or an authenticated production Mini App. It exercises the real opt-in panel JS and the equivalent server-approval gating rules inside an isolated HTML fixture with mocked API semantics. The actual deployed `miniapp/templates/index.html`, `miniapp_server.py`, and `pd_onboarding.py` remain unchanged. Source-pinned patch compatibility is verified separately by Python-based GET-only tests. Release still requires controlled staging with real signed test initData, integrated WSGI routes, visual smoke checks on target browsers and authorized backups/migrations/rollback before any production installation.
