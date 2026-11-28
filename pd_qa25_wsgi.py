"""Isolated WSGI entry for PostgreSQL order integration; no live services."""
import os
from flask import Flask, jsonify, request
from pd_request_security import verify_telegram_user, register_request_guard
from pd_dispatch_persistent import register
from pd_native_orders_http import make_orders_app
from pd_qa25_telegram_orders import safe, telegram_order

def create_application(*, qa_booking=False):
    if os.getenv("PD_QA25_WSGI") != "1" or not safe():
        raise RuntimeError("QA25 isolation required")
    # QA identities must be explicitly provisioned, never production credentials.
    token = os.environ["PD_QA25_TELEGRAM_TEST_TOKEN"]
    if not token.startswith("qa25-synthetic-"):
        raise RuntimeError("Synthetic Telegram token required")
    passengers = frozenset(int(x) for x in os.environ["PD_QA25_PASSENGERS"].split(","))
    admins = frozenset(int(x) for x in os.environ["PD_QA25_ADMINS"].split(","))
    if passengers & admins:
        raise RuntimeError("QA25 roles must be distinct")
    app = Flask(__name__)
    register_request_guard(app)

    @app.get("/qa/staging/readiness")
    def qa_staging_readiness():
        # Only a synthetic admin may inspect readiness; no DSN or secrets in output.
        from pd_qa_staging_preflight import check
        try:
            identity = verify_telegram_user(request.headers.get("X-Telegram-Init-Data", ""), token)[0]
        except (PermissionError, ValueError):
            return jsonify(error="unauthorized"), 401
        if identity not in admins:
            return jsonify(error="forbidden"), 403
        outcome = check()
        return jsonify(outcome), 200 if outcome["ready"] else 503

    def uid():
        return verify_telegram_user(request.headers.get("X-Telegram-Init-Data", ""), token)[0]

    @app.errorhandler(PermissionError)
    def denied(exc):
        return jsonify(error="unauthorized"), 401

    @app.post("/api/order")
    def order():
        user = uid()
        if user not in passengers:
            return jsonify(error="passenger_required"), 403
        return telegram_order(user, request.get_json(silent=True))

    def authorized():
        try:
            return uid() in admins
        except PermissionError:
            return False

    register(app, authorized)
    database_url = os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"]
    native = make_orders_app(app, database_url, qa_booking=qa_booking)
    if os.getenv("PD_QA26_ASSIGNMENT") != "1":
        return native

    import hmac
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from pd_native_pilot_assignment import register_dispatch_assignment, make_native_pilot_orders_app
    for url in (database_url, os.environ["PD_PILOT_ASSIGNMENT_DATABASE_URL"]):
        fields = conninfo_to_dict(url)
        if fields.get("host") != "127.0.0.1" or fields.get("dbname") != "private_drive_test" or any(k in fields for k in ("hostaddr","service")):
            raise RuntimeError("QA26 requires local isolated PostgreSQL")
    csrf = os.environ["PD_QA26_CSRF"]
    if not csrf.startswith("qa26-synthetic-"):
        raise RuntimeError("QA26 requires synthetic CSRF token")
    register_dispatch_assignment(app, authorized,
        lambda: hmac.compare_digest(request.form.get("csrf",""), csrf), uid)

    @app.get("/api/orders")
    def telegram_orders():
        user = uid()
        if user not in passengers:
            return jsonify(error="passenger_required"), 403
        if not safe():
            return jsonify(error="orders_disabled"), 503
        try:
            with psycopg.connect(database_url, connect_timeout=4, options="-c statement_timeout=4000") as db:
                rows = db.execute("""SELECT o.id,o.origin,o.destination,o.trip_date,o.trip_time,o.status
                    FROM public.pd_dispatch_orders o JOIN public.pd_telegram_order_owners t ON t.order_id=o.id
                    WHERE t.telegram_id=%s ORDER BY o.created_at DESC LIMIT 100""",(user,)).fetchall()
            response = jsonify(orders=[dict(zip(("order_id","origin","destination","trip_date","trip_time","status"),(str(r[0]),*r[1:]))) for r in rows])
            response.headers["Cache-Control"] = "private, no-store"
            return response
        except psycopg.Error:
            return jsonify(error="storage_unavailable"), 503

    if os.getenv("PD_QA27_GPS") == "1":
        from pd_qa27_gps import register_gps
        register_gps(app, authorized, database_url)
    pilot = make_native_pilot_orders_app(native, database_url)
    def qa26_application(environ, start_response):
        if environ.get("PATH_INFO") == "/native-pilot-orders":
            if not safe():
                return app.response_class('{"error":"assignment_disabled"}',status=503,mimetype="application/json")(environ,start_response)
            return pilot(environ, start_response)
        if environ.get("PATH_INFO","").startswith("/dispatch/orders/") and not safe():
            return app.response_class('{"error":"assignment_disabled"}',status=503,mimetype="application/json")(environ,start_response)
        return native(environ, start_response)
    return qa26_application
