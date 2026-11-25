"""Separate PRIVATE DRIVE test SMS WSGI service backed by Render PostgreSQL.

Only the dedicated isolated test Web Service imports this module. This module
never mounts the Telegram Mini App, production site, or payment processing.
"""
import os
import json
import threading

from pd_native_auth_postgres_http import make_app
from pd_native_identity_http import make_identity_app

if os.environ.get("PD_NATIVE_SMS_ISOLATED") != "YES":
    raise RuntimeError("Isolated SMS deployment requires explicit opt-in")

database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError("Missing separate PostgreSQL DATABASE_URL")

sms_test_phone = os.environ.get("PD_NATIVE_SMS_TEST_PHONE") or None
live = (
    sms_test_phone is not None
    and os.environ.get("PD_NATIVE_SMS_LIVE") == "YES"
    and os.environ.get("TWILIO_VERIFY_ENABLED", "").lower() == "true"
    and all(os.environ.get(key) for key in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"))
)

telegram_settings = tuple(os.environ.get(key, "") for key in (
    "PD_TELEGRAM_OIDC_CLIENT_ID", "PD_TELEGRAM_OIDC_CLIENT_SECRET",
    "PD_TELEGRAM_OIDC_CALLBACK_URL"))
telegram = None
if all(telegram_settings):
    from pd_native_telegram_oidc import TelegramOidc
    telegram = TelegramOidc(*telegram_settings)

application = make_app(
    database_url,
    admin_phone=os.environ.get("PD_NATIVE_ADMIN_PHONE") or None,
    dispatcher_phone=os.environ.get("PD_NATIVE_DISPATCHER_PHONE") or None,
    pilot_phone=os.environ.get("PD_NATIVE_PILOT_PHONE") or None,
    live=live, sms_test_phone=sms_test_phone, telegram_oidc=telegram,
)
application = make_identity_app(application, database_url, sms_enabled=live,
    telegram_enabled=telegram is not None, session_resume_enabled=True)

def _report_sms_setup():
    from pd_twilio_setup_diagnostics import inspect_setup
    print('PD_SMS_SETUP_STATUS ' + json.dumps(inspect_setup(os.environ)), flush=True)

threading.Thread(target=_report_sms_setup, name='read-only-sms-setup', daemon=True).start()
