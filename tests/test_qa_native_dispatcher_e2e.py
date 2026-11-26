"""End-to-end native WSGI -> synthetic PostgreSQL -> pinned browser dispatcher.

Every request runs in GitHub Actions against the synthetic localhost database.
Browser dispatcher is loaded in a separate interpreter from its deployed SHA.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import psycopg
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_native_auth_postgres_http import initialize_database
from pd_qa_native_orders_mount import REQUIRED

DSN = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
SNAPSHOT = Path(__file__).resolve().parents[1] / ".qa_snapshot" / "dispatcher"


def test_native_order_reaches_pinned_browser_dispatcher_and_pilot(monkeypatch):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    assert SNAPSHOT.is_dir() and SNAPSHOT.name == "dispatcher"
    revision = subprocess.check_output(
        ["git", "-C", str(SNAPSHOT), "rev-parse", "HEAD"], text=True
    ).strip()
    assert revision == "44795f496ed05760cfc09474c506c6d7916c86fb"

    initialize_database(DSN)
    now = int(time.time())
    with psycopg.connect(DSN, autocommit=True) as db:
        for migration in (
            "native_auth_session_functions.sql",
            "native_dispatch_orders.sql",
            "native_pilot_identity.sql",
            "qa26_pilot_assignment.sql",
        ):
            db.execute((Path("migrations") / migration).read_text())
        for uid, char, role in (("e2e-passenger", "a", "passenger"), ("e2e-pilot", "b", "pilot")):
            db.execute(
                "INSERT INTO native_auth_users(id,channel,destination,created_at) VALUES (%s,'phone',%s,0)",
                (uid, uid),
            )
            db.execute("INSERT INTO native_auth_roles(user_id,role) VALUES (%s,%s)", (uid,role))
            db.execute(
                "INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",
                (hashlib.sha256((char * 48).encode()).hexdigest(), uid, now, now + 600),
            )
        db.execute(
            "INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at) "
            "VALUES ('review-e2e','e2e-pilot','approved',%s,%s,%s)",
            (now-30, now+600, now-20),
        )

    opts = {
        **REQUIRED,
        "DATABASE_URL": DSN,
        "PD_DISPATCH_ORDERS_DATABASE_URL": DSN,
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": DSN,
        "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_DISPATCH_ORDERS_INGEST_SECRET": "qa-only-synthetic-ingest-key-123456789",
        "PD_DISPATCH_ADMIN_ID": "201",
        "PD_DISPATCH_SESSION_SECRET": "qa-only-synthetic-session-secret-123456789",
        "PD_DISPATCH_TEST_SYNC": "0",
        "TWILIO_VERIFY_ENABLED": "false",
        "PD_NATIVE_SMS_TEST_PHONE": "",
        "PD_NATIVE_SMS_LIVE": "NO",
    }
    for name, value in opts.items():
        monkeypatch.setenv(name, value)
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID",
                 "PD_DISPATCH_DATABASE_URL", "PD_PAYSERA_MANUAL_ENABLED"):
        monkeypatch.delenv(name, raising=False)

    sys.modules.pop("isolated_sms_wsgi", None)
    app = importlib.import_module("isolated_sms_wsgi").application
    native = Client(app, Response)
    headers = {"Authorization":"Bearer " + "a" * 48}
    payload = {
        "request_id": str(uuid.uuid4()),
        "from": "Synthetic Pickup",
        "to": "Synthetic Destination",
        "trip_date": "2027-01-01",
        "trip_time": "12:20",
    }
    assert native.post("/native-orders", json=payload).status_code == 401
    created = native.post("/native-orders", json=payload, headers=headers)
    assert created.status_code == 201, created.get_data(as_text=True)
    oid = created.json["order_id"]
    replayed = native.post("/native-orders", json=payload, headers=headers)
    assert replayed.status_code == 200 and replayed.json["order_id"] == oid

    # Browser dispatcher reads and assigns the same order from the SAME database,
    # but with its real, pinned WSGI code and a real browser password/CSRF flow.
    password = "synthetic-test-password-for-qa"
    env = dict(os.environ)
    env["PD_DISPATCH_PASSWORD_HASH"] = generate_password_hash(password,method="pbkdf2:sha256")
    env["QA_DISPATCH_TEST_PASSWORD"] = password
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("qa_dispatcher_snapshot_probe.py")),
         str(SNAPSHOT), oid],
        cwd=str(Path(__file__).resolve().parents[1]), env=env, text=True,
        capture_output=True, timeout=35,
    )
    assert result.returncode == 0, "Pinned dispatcher probe failed: " + result.stderr[-4500:]
    probe = json.loads(result.stdout.strip().splitlines()[-1])
    assert probe["order_id"] == oid
    assert probe["status"] == "assigned" and probe["pilot"] == "e2e-pilot"

    # The passenger and assigned pilot immediately observe dispatcher action.
    history = native.get("/native-orders", headers=headers)
    assert history.status_code == 200, history.get_data(as_text=True)
    assert history.json["orders"][0]["status"] == "assigned"
    pilot = native.get("/native-pilot-orders", headers={"Authorization":"Bearer " + "b" * 48})
    assert pilot.status_code == 200, pilot.get_data(as_text=True)
    assert {order["order_id"] for order in pilot.json["orders"]} == {oid}
    with psycopg.connect(DSN) as db:
        assert db.execute(
            "SELECT o.status,a.pilot_user_id FROM public.pd_dispatch_orders o "
            "JOIN public.pd_native_order_assignments a ON a.order_id=o.id WHERE o.id=%s",
            (oid,),
        ).fetchone() == ("assigned", "e2e-pilot")
        assert db.execute("SELECT count(*) FROM public.pd_dispatch_orders").fetchone() == (1,)
    assert native.get("/health").json["sms_enabled"] is False
    print("E2E PASS: native order -> synthetic PostgreSQL -> pinned browser login "
          "-> dispatcher order -> pilot assigned -> native passenger/pilot state")
