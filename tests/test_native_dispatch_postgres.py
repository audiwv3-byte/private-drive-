"""Disposable localhost PostgreSQL: native API and browser queue share one order."""
import hashlib
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

import psycopg
import pytest
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_dispatcher_staging_wsgi import create_app
from pd_native_auth_postgres_http import make_app
from pd_native_auth_schema_migration import initialize_database
from pd_native_orders_http import make_orders_app


@pytest.fixture(scope="module")
def pilot_db():
    dsn = os.environ.get("PD_CI_POSTGRES_URL")
    if dsn is None:
        pytest.skip("Requires disposable localhost PostgreSQL; see native-dispatch-qa.yml")
    u = urlsplit(dsn)
    if not (os.environ.get("PD_CI_FAKE_DB_ONLY") == "YES"
            and u.scheme == "postgresql" and u.hostname == "127.0.0.1"
            and u.port == 5432 and u.path == "/pd_schema_ci"
            and u.username == "pd_ci" and u.password == "synthetic-only-password"
            and not u.query and not u.fragment):
        raise RuntimeError("Refusing non-synthetic PostgreSQL")

    api_user, dispatch_user = "pd_ci_order_api", "pd_ci_order_dispatcher"
    runtime_dsn = dsn.replace("pd_ci:synthetic-only-password@", f"{api_user}:synthetic-api@")
    dispatch_dsn = dsn.replace("pd_ci:synthetic-only-password@", f"{dispatch_user}:synthetic-dispatch@")
    now = int(time.time())
    tokens = {role: uuid.uuid4().hex + uuid.uuid4().hex
              for role in ("passenger", "other", "pilot", "expired")}
    initialize_database(dsn)
    sql_dir = Path(__file__).resolve().parents[1] / "migrations"
    # Migration controls its own BEGIN/COMMIT. Role grants have no default
    # runtime username and are separate from the versioned schema.
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute((sql_dir / "native_auth_session_functions.sql").read_text())
        db.execute((sql_dir / "native_dispatch_orders.sql").read_text())
    with psycopg.connect(dsn) as db:
        db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        db.execute("CREATE ROLE pd_ci_order_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("CREATE ROLE pd_ci_order_dispatcher LOGIN PASSWORD 'synthetic-dispatch'")
        db.execute("""
            GRANT USAGE ON SCHEMA public TO pd_ci_order_api, pd_ci_order_dispatcher;
            GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint),
                public.pd_revoke_current_session(text,bigint) TO pd_ci_order_api;
            GRANT SELECT, INSERT ON public.pd_dispatch_orders,
                public.pd_native_order_owners TO pd_ci_order_api;
            GRANT SELECT ON public.pd_dispatch_orders TO pd_ci_order_dispatcher;
        """)
        for i, (name, token) in enumerate(tokens.items()):
            uid = "synthetic_" + name
            db.execute("""INSERT INTO public.native_auth_users (id,channel,destination,created_at)
                VALUES (%s,'phone',%s,%s)""", (uid, f"+3706990000{i}", now - 100))
            if name == "pilot":
                db.execute("INSERT INTO public.native_auth_roles VALUES (%s,'pilot')", (uid,))
            expiry = now - 1 if name == "expired" else now + 1000
            db.execute("""INSERT INTO public.native_auth_sessions
                (token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)""",
                (hashlib.sha256(token.encode()).hexdigest(), uid, now - 100, expiry))
    yield runtime_dsn, dispatch_dsn, tokens, now


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_native_order_appears_in_authenticated_web_dispatch_and_passenger_history(pilot_db, monkeypatch):
    api_dsn, dispatch_dsn, tokens, now = pilot_db
    for key, value in {
        "PD_NATIVE_SMS_ISOLATED": "YES",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1",
        "PD_PAYMENT_MODE": "disabled",
        "PD_DISPATCH_SESSION_SECRET": "synthetic-session-only-secret-012345",
        "PD_DISPATCH_ADMIN_ID": "1001",
        "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("synthetic-dispatch-login"),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PD_DISPATCH_ORDERS_INGEST_SECRET", raising=False)
    monkeypatch.delenv("PD_DISPATCH_TEST_SYNC", raising=False)
    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL", api_dsn)
    api = Client(make_orders_app(
        make_app(api_dsn, live=False, clock=lambda: now), api_dsn, clock=lambda: now), Response)
    assert api.get("/health").json["sms_enabled"] is False
    passenger = auth(tokens["passenger"])
    assert api.get("/native-auth/session", headers=passenger).json["role"] == "passenger"
    assert api.get("/native-orders").status_code == 401
    assert api.get("/native-orders", headers=auth(tokens["expired"])).status_code == 401
    assert api.get("/native-orders", headers=auth(tokens["pilot"])).status_code == 403

    payload = {"request_id": str(uuid.uuid4()), "from": "Synthetic origin",
               "to": "Synthetic destination", "trip_date": "2026-12-01", "trip_time": "11:30"}
    monkeypatch.setenv("PD_PAYMENT_MODE", "live")
    assert api.post("/native-orders", headers=passenger, json=payload).status_code == 503
    monkeypatch.setenv("PD_PAYMENT_MODE", "disabled")
    created = api.post("/native-orders", headers=passenger, json=payload)
    assert created.status_code == 201, created.json
    assert created.json["payment_mode"] == "disabled"
    order_id = created.json["order_id"]
    retry = api.post("/native-orders", headers=passenger, json=payload)
    assert retry.status_code == 200 and retry.json["order_id"] == order_id
    assert api.post("/native-orders", headers=passenger,
                    json={**payload, "to": "Changed destination"}).status_code == 409
    assert [row["order_id"] for row in
            api.get("/native-orders", headers=passenger).json["orders"]] == [order_id]
    assert api.get("/native-orders", headers=auth(tokens["other"])).json["orders"] == []

    # Same database, distinct runtime users, as used by the two services.
    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL", dispatch_dsn)
    dispatcher = create_app().test_client()
    assert dispatcher.post("/v1/dispatch/orders/import", json={}).status_code == 503
    assert dispatcher.get("/dispatch/orders/state").status_code == 401
    login_page = dispatcher.get("/dispatch/login")
    assert login_page.status_code == 200
    csrf = re.search(rb'name="csrf" value="([^"]+)"', login_page.data)
    assert csrf is not None
    login = dispatcher.post("/dispatch/login", data={
        "csrf": csrf.group(1).decode(), "password": "synthetic-dispatch-login"
    })
    assert login.status_code == 302
    assert b"/dispatch/orders/state" in dispatcher.get("/dispatch").data
    queue = dispatcher.get("/dispatch/orders/state")
    assert queue.status_code == 200, queue.json
    assert [row["id"] for row in queue.json["orders"]] == [order_id]

    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL", api_dsn)
    assert api.post("/native-auth/logout", headers=passenger).status_code == 200
    assert api.get("/native-orders", headers=passenger).status_code == 401
