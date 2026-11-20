"""Secure, opt-in configuration for a separate PRIVATE DRIVE SMS test server.

No server is started by importing this module. Never mount in production.
Configure the secret admin number only via the host's private environment.
"""
import os
import sqlite3

from pd_native_auth_twilio_http import make_twilio_native_auth_app


def make_isolated_sms_app(*, environ=None, start_sms=None, check_sms=None, clock=None):
    config = os.environ if environ is None else environ
    if config.get("PD_NATIVE_SMS_ISOLATED") != "YES":
        raise RuntimeError("Isolated SMS app requires explicit opt-in")
    db_path = config.get("PD_NATIVE_SMS_DB", "")
    if not db_path or db_path == ":memory:" or not os.path.isabs(db_path):
        raise ValueError("A separate absolute persistent SQLite path is required")

    # Real SMS is opt-in a second time: no accidental sending during tests.
    if start_sms is None or check_sms is None:
        if config.get("PD_NATIVE_SMS_LIVE") != "YES" or config.get(
                "TWILIO_VERIFY_ENABLED", "").lower() != "true":
            raise RuntimeError("Real SMS provider remains disabled")
        if not all(config.get(key) for key in (
                "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                "TWILIO_VERIFY_SERVICE_SID")):
            raise RuntimeError("Twilio configuration incomplete")
        from pd_twilio_verify import start_verification, check_verification
        start_sms = lambda phone: start_verification(phone, env=config)
        check_sms = lambda phone, code: check_verification(phone, code, env=config)
    elif not (callable(start_sms) and callable(check_sms)):
        raise TypeError("Both test SMS callbacks must be callable")

    # This isolated test adapter is single-worker only. Protected deployment
    # needs independent HTTPS termination and shared anti-abuse rate limiting.
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        app = make_twilio_native_auth_app(
            conn, start_sms=start_sms, check_sms=check_sms,
            clock=clock, admin_phone=config.get("PD_NATIVE_ADMIN_PHONE") or None,
            dispatcher_phone=config.get("PD_NATIVE_DISPATCHER_PHONE") or None,
            pilot_phone=config.get("PD_NATIVE_PILOT_PHONE") or None)
    except Exception:
        conn.close()
        raise
    return app, conn
