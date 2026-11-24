"""Disposable PostgreSQL contract through the real browser and native HTTP entry points."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
import re
from threading import Barrier
import time
from urllib.parse import urlsplit
import uuid

import psycopg
import pytest
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_dispatcher_staging_wsgi import create_app
from pd_native_auth_schema_migration import initialize_database
from pd_native_identity_http import initialize_identity
from pd_native_orders_http import make_orders_app
from pd_native_pilot_assignment import make_native_pilot_orders_app


@pytest.fixture
def stage(monkeypatch):
    dsn = os.getenv("PD_SYNTHETIC_ASSIGNMENT_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires disposable localhost PostgreSQL")
    parts = urlsplit(dsn)
    if not (os.getenv("PD_CI_FAKE_DB_ONLY") == "YES"
            and parts.scheme == "postgresql"
            and parts.hostname == "127.0.0.1"
            and parts.username == "pd_assignment_owner"
            and parts.password == "synthetic-only"
            and parts.path == "/private_drive_test"
            and not parts.query and not parts.fragment and parts.port):
        raise RuntimeError("Refusing a non-synthetic database")
    initialize_database(dsn)
    initialize_identity(dsn)
    migration = Path(__file__).resolve().parents[1] / "migrations"
    with psycopg.connect(parts._replace(path="/postgres").geturl(), autocommit=True) as wrong_db:
        with pytest.raises(psycopg.errors.RaiseException, match="isolated test database"):
            wrong_db.execute((migration / "native_pilot_assignment.sql").read_text())
        wrong_db.execute("ROLLBACK")
        assert wrong_db.execute("SELECT to_regclass('public.pd_native_order_assignments')").fetchone() == (None,)
    owner = psycopg.connect(dsn, autocommit=True)
    if owner.execute("SELECT COUNT(*) FROM public.native_auth_users").fetchone()[0]:
        owner.close()
        raise RuntimeError("Synthetic database must be empty")
    for name in ("native_auth_session_functions.sql", "native_dispatch_orders.sql",
                 "native_pilot_assignment.sql"):
        owner.execute((migration / name).read_text())

    native, queue, assign = ("pd_assignment_api", "pd_assignment_reader", "pd_assignment_writer")
    for role in (native, queue, assign):
        owner.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'synthetic-only'")
        owner.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    owner.execute(f"""
        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint),
                                   public.pd_native_pilot_order_state(text,bigint) TO {native};
        GRANT SELECT, INSERT ON public.pd_dispatch_orders,
            public.pd_native_order_owners TO {native};
        GRANT SELECT ON public.pd_dispatch_orders TO {queue};
        GRANT EXECUTE ON FUNCTION public.pd_pilot_assignment_candidates(bigint),
            public.pd_assign_native_order(uuid,text,text,bigint) TO {assign};
    """)
    def role_dsn(role):
        # Keep URI form for the same application-level validation used in staging.
        return parts._replace(netloc=f"{role}:synthetic-only@127.0.0.1:{parts.port}").geturl()

    native_url, queue_url, assign_url = map(role_dsn, (native, queue, assign))
    for key, value in {
        "PD_NATIVE_SMS_ISOLATED": "YES",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1",
        "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_PAYMENT_MODE": "disabled",
        "PD_DISPATCH_ORDERS_DATABASE_URL": queue_url,
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": assign_url,
        "PD_DISPATCH_ADMIN_ID": "1001",
        "PD_DISPATCH_SESSION_SECRET": "synthetic-session-only-123456789012",
        "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("synthetic-dispatch"),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PD_DISPATCH_TEST_SYNC", raising=False)
    monkeypatch.delenv("PD_DISPATCH_ORDERS_INGEST_SECRET", raising=False)

    now = int(time.time())
    people = {
        "passenger": ("passenger", None, False),
        "other": ("passenger", None, False),
        "pilotA": ("pilot", "approved", False),
        "pilotB": ("pilot", "approved", False),
        "pilotOld": ("pilot", "approved", True),
        "pilotReview": ("pilot", "pending", False),
        "admin": ("admin", "approved", False),
    }
    tokens = {}
    for i, (user_id, (role, status, old)) in enumerate(people.items()):
        token = uuid.uuid4().hex + uuid.uuid4().hex
        tokens[user_id] = token
        owner.execute("""INSERT INTO public.native_auth_users VALUES
                            (%s,'phone',%s,%s)""",
                      (user_id, f"+3706991230{i}", now - 800000))
        owner.execute("INSERT INTO public.native_auth_roles VALUES (%s,%s)", (user_id, role))
        owner.execute("""INSERT INTO public.native_auth_sessions
            (token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)""",
            (sha256(token.encode()).hexdigest(), user_id, now - 100, now + 1000))
        if status:
            decided = now - (604810 if old else 50) if status == "approved" else None
            owner.execute("""INSERT INTO public.native_identity_checks
                (id,user_id,status,created_at,expires_at,decided_at) VALUES (%s,%s,%s,%s,%s,%s)""",
                (uuid.uuid4().hex, user_id, status, now - 800000, now + 1000, decided))
    try:
        yield owner, native_url, queue_url, assign_url, tokens
    finally:
        owner.close()


def auth(tokens, user):
    return {"Authorization": f"Bearer {tokens[user]}"}


def login(client):
    initial = re.search(rb'name="csrf" value="([^"]+)"', client.get("/dispatch/login").data)
    assert client.post("/dispatch/login", data={
        "csrf": initial.group(1).decode(), "password": "synthetic-dispatch",
    }).status_code == 302
    page = client.get("/dispatch")
    assert page.status_code == 200
    token = re.search(rb'name="csrf" value="([^"]+)"', page.data)
    return token.group(1).decode()


def test_assignment_across_existing_web_and_native_order_apis(stage, monkeypatch):
    owner, native_url, queue_url, assign_url, tokens = stage
    native = Client(make_native_pilot_orders_app(
        make_orders_app(Response("not found", status=404), native_url), native_url), Response)

    def orders(user="passenger"):
        return native.get("/native-orders", headers=auth(tokens, user)).json["orders"]

    def assignments(user):
        return native.get("/native-pilot-orders", headers=auth(tokens, user))

    def create_order():
        result = native.post("/native-orders", headers=auth(tokens, "passenger"), json={
            "request_id": str(uuid.uuid4()), "from": "Synthetic Vilnius",
            "to": "Synthetic Kaunas", "trip_date": "2026-12-01", "trip_time": "11:30",
        })
        assert result.status_code == 201, result.json
        return result.json["order_id"]

    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL", native_url)
    order_id, race_id = create_order(), create_order()
    assert assignments("pilotA").json["orders"] == []
    monkeypatch.delenv("PD_DISPATCH_STAGING_ONLY")
    assert assignments("pilotA").status_code == 503
    monkeypatch.setenv("PD_DISPATCH_STAGING_ONLY", "1")
    assert assignments("passenger").status_code == 403
    assert assignments("admin").status_code == 403
    assert assignments("pilotOld").status_code == 403
    assert assignments("pilotReview").status_code == 403
    assert native.get("/native-pilot-orders").status_code == 401
    assert native.post("/native-pilot-orders", headers=auth(tokens, "pilotA")).status_code == 405

    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL", queue_url)
    browser = create_app()
    client = browser.test_client()
    endpoint = f"/dispatch/orders/{order_id}/assign"
    assert client.get("/dispatch/orders/eligible-pilots").status_code == 401
    assert client.post(endpoint, data={"pilot_id": "pilotA"}).status_code == 401
    token = login(client)
    assert b"const pilotCsrf=" in client.get("/dispatch").data
    assert client.get("/dispatch/orders/eligible-pilots").json == {
        "pilots": [{"id": "pilotA"}, {"id": "pilotB"}]}
    assert client.post(endpoint, data={"pilot_id": "pilotA", "csrf": "invalid"}).status_code == 403
    assert client.post(endpoint, data={"pilot_id": "pilotOld", "csrf": token}).status_code == 409
    assert client.post(endpoint, data={"pilot_id": "pilotReview", "csrf": token}).status_code == 409
    assert client.post(endpoint, data={"pilot_id": "pilotA", "csrf": token, "role": "admin"}).status_code == 400
    assert client.post(f"/dispatch/orders/{uuid.uuid4()}/assign",
                       data={"pilot_id": "pilotA", "csrf": token}).status_code == 404

    imported_id = uuid.uuid4()
    owner.execute("""INSERT INTO public.pd_dispatch_orders
        (id, source, source_order_id, fingerprint, origin, destination, trip_date, trip_time)
        VALUES (%s,'android','synthetic-hmac-import','identity','Vilnius','Kaunas','2026-12-01','11:30')""",
        (imported_id,))
    assert client.post(f"/dispatch/orders/{imported_id}/assign",
                       data={"pilot_id": "pilotA", "csrf": token}).status_code == 404
    monkeypatch.setenv("PD_NATIVE_PILOT_ASSIGNMENT", "0")
    assert client.post(endpoint, data={"pilot_id": "pilotA", "csrf": token}).status_code == 503
    monkeypatch.setenv("PD_NATIVE_PILOT_ASSIGNMENT", "1")

    monkeypatch.setenv("PD_PILOT_ASSIGNMENT_DATABASE_URL", assign_url.replace("private_drive_test", "no"))
    assert client.post(endpoint, data={"pilot_id": "pilotA", "csrf": token}).status_code == 503
    monkeypatch.setenv("PD_PILOT_ASSIGNMENT_DATABASE_URL", assign_url)
    monkeypatch.setenv("PD_PAYMENT_MODE", "live")
    assert client.post(endpoint, data={"pilot_id": "pilotA", "csrf": token}).status_code == 503
    monkeypatch.setenv("PD_PAYMENT_MODE", "disabled")

    first = client.post(endpoint, data={"pilot_id": "pilotA", "csrf": token})
    assert first.status_code == 200, first.json
    assert first.json == {"order_id": order_id, "status": "assigned", "changed": True}
    assert client.post(endpoint, data={"pilot_id": "pilotA", "csrf": token}).json == {
        "order_id": order_id, "status": "assigned", "changed": False}
    assert client.post(endpoint, data={"pilot_id": "pilotB", "csrf": token}).status_code == 409
    assert next(o for o in client.get("/dispatch/orders/state").json["orders"]
                if o["id"] == order_id)["status"] == "assigned"

    barrier = Barrier(2)
    def assign_simultaneously(pilot):
        c = browser.test_client()
        t = login(c)
        barrier.wait(timeout=8)
        return c.post(f"/dispatch/orders/{race_id}/assign",
                      data={"pilot_id": pilot, "csrf": t}).status_code
    with ThreadPoolExecutor(2) as executor:
        outcomes = list(executor.map(assign_simultaneously, ("pilotA", "pilotB")))
    assert sorted(outcomes) == [200, 409]
    assert owner.execute("SELECT count(*) FROM public.pd_native_order_assignments WHERE order_id=%s",
                         (race_id,)).fetchone()[0] == 1

    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL", native_url)
    assert next(o for o in orders() if o["order_id"] == order_id)["status"] == "assigned"
    assert orders("other") == []
    assert order_id in {o["order_id"] for o in assignments("pilotA").json["orders"]}
    assert order_id not in {o["order_id"] for o in assignments("pilotB").json["orders"]}
    owner.execute("""INSERT INTO public.native_identity_checks
        (id,user_id,status,created_at,expires_at) VALUES (%s,'pilotA','pending',%s,%s)""",
        (uuid.uuid4().hex, int(time.time()), int(time.time()) + 1000))
    assert assignments("pilotA").status_code == 403
    owner.execute("UPDATE public.native_auth_sessions SET revoked_at=%s WHERE user_id='pilotA'",
                  (int(time.time()),))
    assert assignments("pilotA").status_code == 401

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(assign_url) as db:
            db.execute("SELECT photo FROM public.native_identity_checks").fetchall()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(queue_url) as db:
            db.execute("SELECT * FROM public.pd_assign_native_order(%s,%s,%s,%s)",
                       (order_id, "pilotA", "1001", int(time.time())))
