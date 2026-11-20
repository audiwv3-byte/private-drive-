# PRIVATE DRIVE: isolated HTTPS SMS authentication — Render preparation

Status: configuration prepared only, **not deployed**. This does not change PythonAnywhere, Telegram Mini App, existing production services, Android, Stripe, or other payments.

## Why not Render Free for live SMS?
Render's Free web services have an ephemeral filesystem; local SQLite files are lost on restart, redeploy and spin-down. The SMS challenge, attempt counter and native session tables currently require durable storage. Do **not** deploy this SQLite implementation on Render Free with real testers. A paid persistent disk (operator approval required), or a redesigned external durable transactional database, is required.

## Required private Render Web Service settings (not yet created)
- Repository: `audiwv3-byte/private-drive-`
- Branch: `feature/flutter-independent-auth`
- Runtime: Python
- Build command: `pip install -r requirements-sms-render.txt`
- Start command: `gunicorn --workers 1 --threads 1 --bind 0.0.0.0:$PORT isolated_sms_wsgi:application`
- Persistent disk mount: `/var/data` (not available on Render Free)
- Health: do not claim readiness until backend is reachable and SMS opt-in is verified
- Disable automatic deployment until operator has reviewed app, data retention, Twilio billing and privacy obligations

## Sensitive environment values, configured privately in Render (never git / APK)
- `PD_NATIVE_SMS_ISOLATED=YES`
- `PD_NATIVE_SMS_DB=/var/data/private-drive-native-auth.sqlite3`
- `PD_NATIVE_ADMIN_PHONE=<E.164 admin number entered privately in Render dashboard>`
- `PD_NATIVE_SMS_LIVE=YES` **only after approved billing and abuse limits**
- `TWILIO_VERIFY_ENABLED=true` **only after approved billing and abuse limits**
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` (secret environment values)

The admin number is never hardcoded. When absent, all verified phone identities are passengers; admin entitlement requires the preassigned phone and successful Verify challenge. Client role claims are ignored. Existing production pilot and administrator accounts are untouched.

## Security gates before any real SMS
1. Confirm Twilio account and Verify Service in your own Twilio Console. Verify geographic permissions, Fraud Guard and Service Rate Limits.
2. Set usage alerts and an acceptable monthly budget. Alerts alone are not a strict spending cap; require explicit approval before enabling billable sends.
3. Deploy only with durable isolated storage, HTTPS, single WSGI worker, and controlled release settings. Shared / DB-backed IP and phone throttling is still required before exposing a mass public sign-in; this code is an integration prototype, not production-grade anti-abuse infrastructure.
4. For privileged real admin functionality implement backend role checks on every protected endpoint plus a second factor (SMS is susceptible to SIM swapping). This demo only opens a local administrator console, **not a production admin API**.
5. Set the native Android test build's `PD_NATIVE_AUTH_API_URL` to the isolated Render HTTPS hostname only after service is tested. Existing published APK is not automatically reconfigured.

Do not paste phone numbers, secrets or API tokens into chat, commits, build logs or app screenshots. Never submit live bookings or payments in testing.

References: Render Free docs https://render.com/docs/free ; Render disks https://render.com/docs/disks ; Twilio Verify Fraud Guard https://www.twilio.com/docs/verify/preventing-toll-fraud/sms-fraud-guard

## Verification
Run the GitHub Actions workflow `Native authentication tests` and check `test_native_sms_isolated_config.py`, `test_native_auth_twilio_http.py`. The new `isolated_sms_wsgi.py` deliberately refuses boot outside `/var/data/` to avoid silent data loss. This is preparation, not a claim that Render account is connected or the API deployed.
