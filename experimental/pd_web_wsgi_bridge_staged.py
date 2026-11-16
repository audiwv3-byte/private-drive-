"""STAGING: mount independent web identity behind existing Flask WSGI app.

The original Telegram application WSGI object is never modified. Only
/api/web/* requests go to the separately signed web-only Flask session app.
Unrelated routes remain byte-for-byte owned by the legacy WSGI callable.

NOT PRODUCTION READY: email delivery provider, database migrations, ownership
mapping of orders, frontend registration, cookie/domain security and rate limits
must be reviewed separately. No real customers, bookings, payments.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

from pd_web_identity_staged import create_isolated_app
from pd_web_bookings_staged import add_staged_web_bookings

class IsolatedWebApiMultiplexer:
    def __init__(self,legacy_wsgi,web_wsgi):
        if not callable(legacy_wsgi) or not callable(web_wsgi):
            raise ValueError("Expected two WSGI callables")
        self.legacy_wsgi=legacy_wsgi
        self.web_wsgi=web_wsgi

    def __call__(self,environ,start_response):
        path=environ.get("PATH_INFO","")
        if path.startswith("/api/web/"):
            return self.web_wsgi(environ,start_response)
        return self.legacy_wsgi(environ,start_response)

def create_staged_wsgi(legacy_app,testing_database,staging_session_secret,
                       send_otp,*,allowed_origin):
    if legacy_app is None or not hasattr(legacy_app,"wsgi_app"):
        raise TypeError("A Flask legacy app is required")
    # A separate Flask instance ensures auth handlers, secret and session
    # cookies do not leak into the live Telegram Flask application.
    web=create_isolated_app(testing_database,staging_session_secret,send_otp,
                            allowed_origin=allowed_origin)
    add_staged_web_bookings(web,testing_database,origin=allowed_origin)
    # Do not set legacy_app.wsgi_app! Production wiring requires WSGI review.
    mux=IsolatedWebApiMultiplexer(legacy_app.wsgi_app,web.wsgi_app)
    return mux,web
