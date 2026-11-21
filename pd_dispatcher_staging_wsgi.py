"""Isolated staging WSGI entry for PRIVATE DRIVE browser dispatcher.

Never imports miniapp_server, Telegram, orders, payment modules or databases.
Run only on a dedicated HTTPS test deployment; not production.
"""
import os
from types import SimpleNamespace

from flask import Flask, request, Response
from pathlib import Path
from pd_web_dispatcher import register
from pd_public_route_preview import register as register_route_preview


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
    register_route_preview(app)

    @app.get("/")
    def home_preview():
        page = Path(__file__).with_name("pd_public_home_preview.html").read_text(encoding="utf-8")
        return Response(page, content_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; img-src 'self' https://tile.openstreetmap.org https://unpkg.com https://www.wanderin.ge data:; connect-src 'self'; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self' 'unsafe-inline' https://unpkg.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    @app.get("/pd-logo-transparent.png")
    def pd_logo_asset():
        logo = Path(__file__).parent / "assets" / "pd-logo-transparent.png"
        return Response(logo.read_bytes(), mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})


    @app.get("/pilot-registration")
    def pilot_registration():
        page = Path(__file__).with_name("pd_pilot_registration.html").read_text(encoding="utf-8")
        return Response(page, content_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    @app.post("/pilot-registration")
    def pilot_registration_submission_disabled():
        # Never accept IDs, uploaded photos, bank details or other PII on staging.
        return "Загрузка анкет не подключена", 503

    return app


application = create_app()
