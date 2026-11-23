"""Isolated staging WSGI entry for PRIVATE DRIVE browser dispatcher.

Never imports miniapp_server, Telegram, orders or payment modules.
Run only on a dedicated HTTPS test deployment; not production.
"""
import os
import re
from types import SimpleNamespace

from flask import Flask, request, Response, render_template_string, send_from_directory
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
        @app.route("/dispatch/register", methods=["GET", "POST"])
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

    @app.get("/assets/pd-black-gold.css")
    def brand_styles():
        response = send_from_directory(Path(__file__).with_name("assets"), "pd-black-gold.css",
                                       mimetype="text/css", max_age=3600)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def home_preview():
        page = Path(__file__).with_name("pd_public_home_preview.html").read_text(encoding="utf-8")
        return Response(page, content_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; img-src 'self' https://tile.openstreetmap.org https://unpkg.com data:; connect-src 'self'; style-src 'self' 'unsafe-inline' https://unpkg.com; script-src 'self' 'unsafe-inline' https://unpkg.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    @app.get("/payment/paysera")
    def paysera_payment():
        recipient = os.environ.get("PD_PAYSERA_RECIPIENT_CODE", "")
        qr = os.environ.get("PD_PAYSERA_QR_PNG_BASE64", "")
        enabled = (os.environ.get("PD_PAYSERA_MANUAL_ENABLED") == "1"
                   and re.fullmatch(r"EVP[0-9]{8,24}", recipient)
                   and re.fullmatch(r"iVBORw0KGgo[A-Za-z0-9+/]{1,8192}={0,2}", qr))
        page = Path(__file__).with_name("pd_paysera_payment.html").read_text(encoding="utf-8")
        return Response(
            render_template_string(page, code=recipient if enabled else "", qr=qr if enabled else ""),
            content_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                     "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; "
                                                "style-src 'self' 'unsafe-inline'; "
                                                "base-uri 'none'; frame-ancestors 'none'"},
        )

    @app.get("/services")
    def public_services():
        page = Path(__file__).with_name("pd_public_services_preview.html").read_text(encoding="utf-8")
        return Response(page, content_type="text/html; charset=utf-8",
                        headers={"Cache-Control":"no-store",
                                 "X-Content-Type-Options":"nosniff",
                                 "Content-Security-Policy":"default-src 'none'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    # Serve only approved owner assets on isolated staging; never query stock photo sites.
    @app.get("/assets/pd-approved-hero.webp")
    @app.get("/assets/pd-approved-airport.webp")
    @app.get("/assets/pd-approved-kaunas.webp")
    @app.get("/assets/pd-approved-klaipeda.webp")
    @app.get("/assets/pd-approved-warsaw.webp")
    @app.get("/assets/pd-approved-service_airport.webp")
    @app.get("/assets/pd-approved-service_parcel.webp")
    @app.get("/assets/pd-approved-service_driver.webp")
    @app.get("/assets/pd-approved-mock1-hero.webp")
    @app.get("/assets/pd-user-photo-7-original.webp")
    @app.get("/assets/pd-user-logo-4-original.webp")
    @app.get("/assets/pd-user-photo-6-original.webp")
    @app.get("/assets/pd-user-photo-6.webp")
    @app.get("/assets/pd-user-photo-7.webp")
    @app.get("/assets/pd-user-logo-4.webp")
    def approved_brand_media():
        filename = request.path.rsplit("/", 1)[-1]
        allowed = frozenset(("pd-approved-hero.webp", "pd-approved-airport.webp", "pd-approved-kaunas.webp", "pd-approved-klaipeda.webp", "pd-approved-warsaw.webp", "pd-approved-service_airport.webp", "pd-approved-service_parcel.webp", "pd-approved-service_driver.webp", "pd-approved-mock1-hero.webp", "pd-user-photo-6.webp", "pd-user-photo-6-original.webp", "pd-user-photo-7.webp", "pd-user-photo-7-original.webp", "pd-user-logo-4.webp", "pd-user-logo-4-original.webp"))
        if filename not in allowed:
            return "Not found", 404
        media_path = Path(__file__).parent / "assets" / filename
        return Response(media_path.read_bytes(), mimetype="image/webp",
                        headers={"Cache-Control":"public, max-age=3600",
                                 "X-Content-Type-Options":"nosniff"})

    @app.get("/pd-logo-transparent.png")
    def pd_logo_asset():
        logo = Path(__file__).parent / "assets" / "pd-logo-transparent.png"
        return Response(logo.read_bytes(), mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})


    @app.get("/pilot-registration")
    def pilot_registration():
        from pd_pilot_qa_intake import configured as pilot_intake_configured
        template = Path(__file__).with_name("pd_pilot_registration.html").read_text(encoding="utf-8")
        page = render_template_string(template, enabled=pilot_intake_configured())
        return Response(page, content_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; connect-src 'self'; frame-ancestors 'none'"})

    return app


application = create_app()
