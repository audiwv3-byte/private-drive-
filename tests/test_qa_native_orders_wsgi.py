"""Real isolated_sms_wsgi chain with QA-only /native-orders and synthetic Postgres.

No Render, production, SMS providers or payment providers are contacted.
"""
import hashlib
import importlib
import os
import sys
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_native_auth_postgres_http import initialize_database
from pd_qa_native_orders_mount import REQUIRED, permitted, mount_if_synthetic

DSN = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"


def test_mount_requires_explicit_synthetic_configuration():
    env = {**REQUIRED, "PD_DISPATCH_ORDERS_DATABASE_URL": DSN}
    assert permitted(DSN, env)
    for key in REQUIRED:
        wrong = dict(env)
        wrong.pop(key)
        assert not permitted(DSN, wrong), key
    assert not permitted(DSN, {**env, "PD_DISPATCH_ORDERS_DATABASE_URL": "postgresql://other@127.0.0.1:5432/private_drive_test"})
    for bad in (
        "postgresql://postgres@database.render.com/private_drive_test",
        "postgresql://postgres@127.0.0.1/production",
        "postgresql://postgres@127.0.0.1:5433/private_drive_test",
        "postgresql://postgres@127.0.0.1/private_drive_test?hostaddr=10.0.0.1",
        "postgresql://postgres@127.0.0.1/private_drive_test?service=production",
        "sqlite:///private_drive_test",
    ):
        assert not permitted(bad, {**env, "PD_DISPATCH_ORDERS_DATABASE_URL": bad}), bad


def test_denied_mount_preserves_existing_wsgi(monkeypatch):
    monkeypatch.delenv("PD_QA_NATIVE_ORDERS_WSGI", raising=False)
    def fallback(environ, start_response):
        start_response("418 I'm a teapot", [("Content-Type", "text/plain")])
        return [b"existing"]
    assert mount_if_synthetic(fallback, DSN) is fallback


def test_real_sms_wsgi_order_chain(monkeypatch):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    initialize_database(DSN)
    with psycopg.connect(DSN, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql", "native_dispatch_orders.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa_native_orders LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa_native_orders")
        db.execute("GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint) TO qa_native_orders")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners TO qa_native_orders")
        db.execute("INSERT INTO native_auth_users VALUES ('passenger-qa','phone','qa-passenger',0)")
        db.execute("INSERT INTO native_auth_users VALUES ('admin-qa','phone','qa-admin',0)")
        db.execute("INSERT INTO native_auth_roles VALUES ('admin-qa','admin')")
        now = int(time.time())
        for uid, char in (("passenger-qa", "a"), ("admin-qa", "b")):
            db.execute(
                "INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",
                (hashlib.sha256((char * 48).encode()).hexdigest(), uid, now, now + 600)
            )
    api_dsn = DSN.replace("postgres:isolated-test@", "qa_native_orders:synthetic-api@")
    for key, value in {**REQUIRED, "DATABASE_URL": api_dsn, "PD_DISPATCH_ORDERS_DATABASE_URL": api_dsn,
                       "PD_NATIVE_PILOT_ASSIGNMENT": "0", "TWILIO_VERIFY_ENABLED": "false",
                       "PD_NATIVE_SMS_TEST_PHONE": "", "PD_NATIVE_SMS_LIVE": "NO"}.items():
        monkeypatch.setenv(key, value)
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"):
        monkeypatch.delenv(name, raising=False)

    # Import the same WSGI entry point as the isolated Render service, not QA25.
    sys.modules.pop("isolated_sms_wsgi", None)
    application = importlib.import_module("isolated_sms_wsgi").application
    client = Client(application, Response)
    bearer = lambda char: {"Authorization": "Bearer " + char * 48}
    body = {"request_id": str(uuid.uuid4()), "from": "Synthetic Airport",
            "to": "Synthetic City", "trip_date": "2027-01-01", "trip_time": "14:00"}

    health = client.get("/health")
    assert health.status_code == 200, health.get_data(as_text=True)
    assert health.json["sms_enabled"] is False
    assert client.get("/native-orders").status_code == 401
    assert client.post("/native-orders", json=body, headers=bearer("b")).status_code == 403
    assert client.post("/native-orders", json={"invalid": 1}, headers=bearer("a")).status_code == 400
    created = client.post("/native-orders", json=body, headers=bearer("a"))
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.json["payment_mode"] == "disabled"
    order_id = created.json["order_id"]
    replayed = client.post("/native-orders", json=body, headers=bearer("a"))
    assert replayed.status_code == 200
    assert replayed.json["order_id"] == order_id
    assert client.post("/native-orders", json={**body, "to": "Other City"},
                       headers=bearer("a")).status_code == 409
    history = client.get("/native-orders", headers=bearer("a"))
    assert history.status_code == 200
    assert history.json["orders"][0]["order_id"] == order_id
    with psycopg.connect(DSN) as db:
        assert db.execute(
            "SELECT source FROM public.pd_dispatch_orders WHERE id=%s", (order_id,)
        ).fetchone() == ("android",)
        assert db.execute(
            "SELECT count(*) FROM public.pd_dispatch_orders"
        ).fetchone() == (1,)

    # The existing SMS/native-auth route stays present and intentionally disabled.
    disabled_sms = client.post("/native-auth/request-code", json={"channel": "phone", "destination": "+37060000000"})
    assert disabled_sms.status_code == 503
    assert disabled_sms.json["error"] == "sms_disabled"
    assert client.get("/native-pilot-orders").status_code == 503

    # Runtime flag changes must fail closed even after WSGI initialization.
    monkeypatch.setenv("PD_PAYMENT_MODE", "live")
    blocked = client.post("/native-orders", json=body, headers=bearer("a"))
    assert blocked.status_code == 503
    assert blocked.json["error"] == "orders_disabled"
    monkeypatch.setenv("PD_PAYMENT_MODE", "disabled")
    monkeypatch.setenv("PD_NATIVE_SMS_LIVE", "YES")
    assert client.get("/native-orders", headers=bearer("a")).status_code == 503
    monkeypatch.setenv("PD_NATIVE_SMS_LIVE", "NO")
    monkeypatch.setenv("PD_QA_NATIVE_ORDERS_WSGI", "0")
    assert client.get("/native-orders", headers=bearer("a")).status_code == 503
