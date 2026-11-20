"""Separate PRIVATE DRIVE test SMS WSGI service backed by Render PostgreSQL.

Only the dedicated isolated test Web Service imports this module. This module
never mounts the Telegram Mini App, production site, or payment processing.
"""
import os

from pd_native_auth_postgres_http import make_app

if os.environ.get("PD_NATIVE_SMS_ISOLATED") != "YES":
    raise RuntimeError("Isolated SMS deployment requires explicit opt-in")

database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError("Missing separate PostgreSQL DATABASE_URL")

live = (
    os.environ.get("PD_NATIVE_SMS_LIVE") == "YES"
    and os.environ.get("TWILIO_VERIFY_ENABLED", "").lower() == "true"
    and all(os.environ.get(key) for key in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"))
)

application = make_app(
    database_url,
    admin_phone=os.environ.get("PD_NATIVE_ADMIN_PHONE") or None,
    live=live,
)
