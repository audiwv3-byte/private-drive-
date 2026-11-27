"""Flask adapters for the shared, QA-only first-ride reward."""
from io import BytesIO
from pathlib import Path
import time

from flask import Response, jsonify, request, send_from_directory
from werkzeug.wrappers import Response as WsgiResponse

import pd_dispatch_persistent as dispatch
import pd_first_ride_wheel as wheel


def bearer():
    value = request.headers.get("Authorization", "")
    return value[7:] if value.startswith("Bearer ") else ""


def register(app, prefix, *, telegram_auth=None):
    @app.get("/assets/pd-first-ride-wheel.<extension>")
    def first_ride_assets(extension):
        if not wheel.enabled() or extension not in {"js", "css"}:
            return "", 404
        return send_from_directory(Path(__file__).with_name("assets"),
                                   "pd-first-ride-wheel." + extension)

    def response(data, status=200):
        result = jsonify(data)
        result.status_code = status
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.route(prefix + "/first-ride-wheel", methods=["GET", "POST"])
    def first_ride_wheel():
        if not wheel.enabled():
            return jsonify(error="wheel_disabled"), 404
        import psycopg
        try:
            with dispatch.connect() as db:
                now = int(time.time())
                if telegram_auth:
                    telegram_id, _ = telegram_auth()
                    user_id = wheel.telegram_account(db, telegram_id)
                    if not user_id:
                        return response({"state": "link_required"})
                else:
                    account = wheel.session_account(db, bearer(), now)
                    if not account:
                        return response({"state": "sign_in_required"})
                    user_id = account[0]
                return response(wheel.reward(db, user_id, now, spin=request.method == "POST"))
        except psycopg.Error:
            return response({"error": "storage_unavailable"}, 503)

    @app.post(prefix + "/first-ride-wheel/phone/<action>")
    def wheel_phone(action):
        if not wheel.enabled() or action not in {"request-code", "verify-code"}:
            return jsonify(error="wheel_disabled"), 404
        if telegram_auth:
            telegram_id, _ = telegram_auth()
        auth_wsgi = app.config.get("PD_WHEEL_QA_AUTH_WSGI")
        if auth_wsgi is None:
            return jsonify(error="phone_auth_unavailable"), 503
        if not 0 < (request.content_length or 0) <= 2048:
            return response({"error": "invalid_request"}, 400)
        body = request.get_data()
        environ = {**request.environ, "PATH_INFO": "/native-auth/" + action,
                   "CONTENT_LENGTH": str(len(body)), "wsgi.input": BytesIO(body)}
        result = WsgiResponse.from_app(auth_wsgi, environ)
        if not telegram_auth or action != "verify-code" or result.status_code != 200:
            return Response(result.get_data(), result.status_code, headers=result.headers)
        import psycopg
        try:
            with dispatch.connect() as db:
                account = wheel.session_account(db, result.json["access_token"], int(time.time()))
                if not account or not wheel.bind_telegram(db, telegram_id, account[0]):
                    return response({"error": "account_link_conflict"}, 409)
            return response({"linked": True})
        except psycopg.Error:
            return response({"error": "storage_unavailable"}, 503)


def install_qa_phone_auth(app, database_url, codes):
    """Install the real phone flow with fixture-only delivery and verification."""
    from hmac import compare_digest
    from pd_native_auth_postgres_http import make_app
    from pd_twilio_verify import VerifyError

    if not wheel.enabled() or not wheel.permitted(database_url):
        raise RuntimeError("Wheel phone sign-in requires the isolated QA database")
    if not codes or any(not phone.startswith("+120255501")
                        or not code.isascii() or not code.isdecimal()
                        for phone, code in codes.items()):
        raise ValueError("Expected synthetic QA phone numbers and codes")

    def request_code(phone, **_):
        if phone not in codes:
            raise VerifyError("Synthetic number required")

    def verify_code(phone, code, **_):
        return phone in codes and compare_digest(code, codes[phone])

    app.config["PD_WHEEL_QA_AUTH_WSGI"] = make_app(
        database_url, live=True, start_sms=request_code, check_sms=verify_code)
