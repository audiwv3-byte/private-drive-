"""PRIVATE DRIVE separate opt-in SMS test WSGI entrypoint.

Only the isolated Render-style service should import this module.
DO NOT mount under the production site or Telegram application.

Never add a real admin number or Twilio credentials to source control.
Render Free has ephemeral storage, so this entrypoint refuses its unsafe
filesystem layout. Use a separate persistent disk (or redesign for a durable
external database) before handling real phone numbers.
"""
import os
from pd_native_sms_isolated_config import make_isolated_sms_app

# A persistent Render disk mounted at /var/data is required for SQLite.
# Fail closed: Render's default /opt/render filesystem is ephemeral.
path = os.environ.get("PD_NATIVE_SMS_DB", "")
if not path.startswith("/var/data/"):
    raise RuntimeError(
        "Refusing SMS auth without isolated persistent SQLite under /var/data/"
    )
if os.environ.get("PD_NATIVE_SMS_ISOLATED") != "YES":
    raise RuntimeError("Isolated SMS deployment requires explicit opt-in")
application, _isolated_connection = make_isolated_sms_app()
