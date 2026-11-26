"""QA-only staging readiness: distinguish disabled API from unavailable storage.

Never disclose credentials or database addresses to callers.
"""
import os

REQUIRED = {
    "PD_QA25_WSGI": "1",
    "PD_DISPATCH_STAGING_ONLY": "1",
    "PD_DISPATCH_PERSISTENT_QUEUE": "1",
    "PD_PAYMENT_MODE": "disabled",
    "PD_NATIVE_SMS_ISOLATED": "YES",
    "PD_NATIVE_SMS_LIVE": "NO",
}


def check(*, connect=None, environment=None):
    env = os.environ if environment is None else environment
    if any(env.get(name) != expected for name, expected in REQUIRED.items()):
        return {"ready": False, "reason": "staging_flags_invalid"}
    url = env.get("PD_DISPATCH_ORDERS_DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        return {"ready": False, "reason": "database_url_invalid"}
    if connect is None:
        import psycopg
        connect = psycopg.connect
    try:
        with connect(url, connect_timeout=4, options="-c statement_timeout=4000") as db:
            row = db.execute("SELECT 1").fetchone()
            if row != (1,):
                return {"ready": False, "reason": "database_healthcheck_failed"}
    except Exception:
        return {"ready": False, "reason": "database_unavailable"}
    return {"ready": True, "reason": "ok"}
