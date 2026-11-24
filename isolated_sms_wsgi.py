"""Separate PRIVATE DRIVE test SMS WSGI service backed by Render PostgreSQL.

Only the dedicated isolated test Web Service imports this module. This module
never mounts the Telegram Mini App, production site, or payment processing.
"""
import os
import json
import threading

from pd_native_auth_postgres_http import make_app
from pd_native_identity_http import make_identity_app, use_restricted_identity_runtime
from pd_native_orders_http import make_orders_app
from pd_native_closed_invites import make_closed_invites_app, pilot_account_invites_enabled
from pd_native_pilot_assignment import make_native_pilot_orders_app

if os.environ.get("PD_NATIVE_SMS_ISOLATED") != "YES":
    raise RuntimeError("Isolated SMS deployment requires explicit opt-in")

database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError("Missing separate PostgreSQL DATABASE_URL")

pilot_invite_requested = os.environ.get("PD_NATIVE_PILOT_INVITE_ONBOARDING") == "1"
web_review_only = os.environ.get("PD_NATIVE_PHOTO_REVIEW_WEB_ONLY") == "1"
if web_review_only and not pilot_invite_requested:
    raise RuntimeError("Web-only photo review requires the isolated pilot invite configuration")
if pilot_invite_requested and not pilot_account_invites_enabled(database_url, os.environ):
    raise RuntimeError("Pilot invitation onboarding requires isolated no-SMS, no-payment settings")

live = (
    not pilot_invite_requested
    and os.environ.get("PD_NATIVE_SMS_LIVE") == "YES"
    and os.environ.get("TWILIO_VERIFY_ENABLED", "").lower() == "true"
    and all(os.environ.get(key) for key in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"))
)

application = make_app(
    database_url,
    admin_phone=os.environ.get("PD_NATIVE_ADMIN_PHONE") or None,
    dispatcher_phone=os.environ.get("PD_NATIVE_DISPATCHER_PHONE") or None,
    pilot_phone=os.environ.get("PD_NATIVE_PILOT_PHONE") or None,
    live=live,
)
application = make_identity_app(
    application, database_url, sms_enabled=live,
    restricted_runtime=use_restricted_identity_runtime(os.environ),
    web_review_only=web_review_only,
)
application = make_orders_app(application, database_url)
application = make_closed_invites_app(application, database_url)
application = make_native_pilot_orders_app(application, database_url)

def _report_sms_setup():
    from pd_twilio_setup_diagnostics import inspect_setup
    print('PD_SMS_SETUP_STATUS ' + json.dumps(inspect_setup(os.environ)), flush=True)

# Don't even make the existing read-only provider probes in the invitation-only
# mode, including when inherited Twilio credentials are otherwise present.
if not pilot_invite_requested:
    threading.Thread(target=_report_sms_setup, name='read-only-sms-setup', daemon=True).start()
