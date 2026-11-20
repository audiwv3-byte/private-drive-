# PRIVATE DRIVE — isolated SMS role access (test branch only)

Scope: `feature/flutter-independent-auth`. Do **not** mount this WSGI app in the existing PythonAnywhere/Telegram production service.

## Expected login
- Unknown verified phone -> new/reused native account -> `passenger` -> passenger ride entry.
- Existing native passenger phone -> same user ID -> `passenger`.
- **Explicitly preassigned** verified phone -> `admin` -> isolated demo administrator/dispatcher cabinet.
- No public self-registration as administrator/pilot; role requests from client JSON are ignored.
- Existing production pilot and administrator accounts and permissions are left untouched; this branch **does not migrate** them into native SMS identity storage.
- Administrator UI is a **local test console**, not proof of server authorization for real dispatcher/admin operations. Any future privileged API must independently verify the bearer token and a server-side role registry before returning sensitive information.

## Server operator setup (not yet deployed)
1. Provision the admin phone in E.164 format **privately** in a protected test-server environment variable, e.g. `PD_NATIVE_ADMIN_PHONE`. Never commit a real phone number, tokens, or credentials.
2. The server entrypoint must explicitly pass `admin_phone=os.environ.get("PD_NATIVE_ADMIN_PHONE") or None` when creating `make_twilio_native_auth_app(...)`. If the variable is absent, **no admin access is granted**.
3. The isolated HTTPS WSGI runtime must have durable SQLite storage, authenticated privilege checks at the backend and robust shared rate limiting before an Internet-facing release. Do not use multiworker SQLite without transactions/locking.
4. Twilio Verify requires server-side `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID`, and explicit `TWILIO_VERIFY_ENABLED=true`. This can incur fees; configure spend caps and fraud protections before enablement.
5. Build the Android test app with `--dart-define=PD_NATIVE_AUTH_API_URL=https://<isolated-test-host>`. Never point it to existing production. The test UI does not make real bookings or payments.

Security: SMS alone is vulnerable to SIM swap. Before real production administrator operations, require an additional strong authentication factor, server-side RBAC and audit trails.

## Tests
`python -m unittest -v test_native_auth_twilio_http.py` is strictly offline and uses synthetic phone numbers. `flutter_app/test/offline_auth_test.dart` checks passenger/admin shell separation. GitHub Actions has a separate native authentication test workflow.

Status: Code and tests only. **No Twilio credentials configured, no real SMS sent, no server deployed, no admin phone provisioned, and no production change.**
