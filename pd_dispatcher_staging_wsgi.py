"""Isolated staging WSGI entry for PRIVATE DRIVE browser dispatcher.

Never imports miniapp_server, Telegram, orders, payment modules or databases.
Run only on a dedicated HTTPS test deployment; not production.
"""
import os
from types import SimpleNamespace

from flask import Flask
from pd_web_dispatcher import register


def create_app():
    app = Flask("private_drive_dispatcher_staging", static_folder=None)
    app.config.update(
        SESSION_COOKIE_NAME="pd_dispatch_staging_session",
        SESSION_COOKIE_PATH="/dispatch",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )

    # Staging is deliberately unavailable without an explicit environment gate.
    if os.environ.get("PD_DISPATCH_STAGING_ONLY") != "1":
        @app.get("/dispatch")
        @app.get("/dispatch/login")
        def staging_unavailable():
            return "Test dispatcher is disabled", 503
        return app

    raw_id = os.environ.get("PD_DISPATCH_ADMIN_ID", "")
    allowed_id = int(raw_id) if raw_id.isascii() and raw_id.isdecimal() else -1
    # Isolated role fixture, never the production Telegram administrator database.
    core = SimpleNamespace(
        ADMIN_IDS=frozenset((allowed_id,)) if allowed_id > 0 else frozenset(),
        is_admin=lambda uid: uid == allowed_id and allowed_id > 0,
    )
    register(app, core)
    return app


application = create_app()
