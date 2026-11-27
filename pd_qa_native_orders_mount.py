"""Fail-closed QA-only mount for the isolated native orders API.

Never use this adapter for Render/production: it accepts only the synthetic
loopback PostgreSQL database and explicit SMS/payment isolation flags.
Existing native authentication, identity and pilot routes remain unchanged.
"""
import json
import os

REQUIRED = {
    "PD_QA_NATIVE_ORDERS_WSGI": "1",
    "PD_NATIVE_SMS_ISOLATED": "YES",
    "PD_NATIVE_SMS_LIVE": "NO",
    "PD_DISPATCH_STAGING_ONLY": "1",
    "PD_DISPATCH_PERSISTENT_QUEUE": "1",
    "PD_PAYMENT_MODE": "disabled",
}


def permitted(database_url, env=None):
    env = os.environ if env is None else env
    if any(env.get(key) != value for key, value in REQUIRED.items()):
        return False
    if env.get("PD_DISPATCH_ORDERS_DATABASE_URL") != database_url:
        return False
    if not database_url.startswith(("postgresql://", "postgres://")):
        return False
    from psycopg.conninfo import conninfo_to_dict
    try:
        target = conninfo_to_dict(database_url)
    except (TypeError, ValueError):
        return False
    return (
        target.get("host") == "127.0.0.1"
        and target.get("dbname") == "private_drive_test"
        and str(target.get("port", "5432")) == "5432"
        and not any(key in target for key in ("hostaddr", "service"))
    )


def mount_if_synthetic(next_app, database_url):
    """Mount only when explicitly allowed; otherwise leave WSGI unmodified."""
    if not permitted(database_url):
        return next_app
    from pd_native_orders_http import make_orders_app
    orders_app = make_orders_app(next_app, database_url)

    def guarded(environ, start_response):
        if environ.get("PATH_INFO") in ("/native-orders", "/native-first-ride-wheel") and not permitted(database_url):
            data = json.dumps({"error": "orders_disabled"}).encode("utf-8")
            start_response("503 Service Unavailable", [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(data))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ])
            return [data]
        return orders_app(environ, start_response)

    return guarded
