"""Isolated WSGI entry for PostgreSQL order integration; no live services."""
import os
from flask import Flask, jsonify, request
from pd_request_security import verify_telegram_user, register_request_guard
from pd_dispatch_persistent import register
from pd_native_orders_http import make_orders_app
from pd_qa25_telegram_orders import safe, telegram_order

def create_application():
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
        return telegram_order(user, request.get_json())

    def authorized():
        try:
            return uid() in admins
        except PermissionError:
            return False

    register(app, authorized)
    return make_orders_app(app, os.environ["PD_DISPATCH_ORDERS_DATABASE_URL"])
