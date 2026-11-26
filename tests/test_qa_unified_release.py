"""Unified no-deploy release: native API, Telegram, pinned dispatcher, GPS.

The tests run exclusively against localhost private_drive_test in GitHub Actions;
no live Render, Telegram, Android device, Twilio or payment endpoint is contacted.
"""
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import uuid

import psycopg
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_native_auth_postgres_http import initialize_database
from pd_qa_native_orders_mount import REQUIRED

DSN = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / ".qa_snapshot" / "dispatcher"


def telegram_header(uid, key):
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid})}
    secret = hmac.new(b"WebAppData", key.encode(), hashlib.sha256).digest()
    data = "\n".join(k + "=" + v for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urllib.parse.urlencode(fields)}


def test_unified_android_telegram_dispatcher_gps(monkeypatch):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    assert subprocess.check_output(["git", "-C", str(DISPATCH), "rev-parse", "HEAD"],
                                   text=True).strip() == "44795f496ed05760cfc09474c506c6d7916c86fb"
    initialize_database(DSN)
    now = int(time.time())
    with psycopg.connect(DSN, autocommit=True) as db:
        for migration in ("native_auth_session_functions.sql", "native_dispatch_orders.sql",
                          "native_pilot_identity.sql", "qa26_pilot_assignment.sql",
                          "qa27_pilot_gps.sql"):
            db.execute((ROOT / "migrations" / migration).read_text())
        for uid, char, role in (("unified-passenger", "a", "passenger"),
                                ("unified-pilot", "b", "pilot")):
            db.execute("INSERT INTO native_auth_users(id,channel,destination,created_at) "
                       "VALUES (%s,'phone',%s,0)", (uid, uid))
            db.execute("INSERT INTO native_auth_roles(user_id,role) VALUES (%s,%s)", (uid, role))
            db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) "
                       "VALUES (%s,%s,%s,%s)",
                       (hashlib.sha256((char * 48).encode()).hexdigest(), uid, now, now+600))
        db.execute("INSERT INTO native_identity_checks "
                   "(id,user_id,status,created_at,expires_at,decided_at) "
                   "VALUES ('unified-review','unified-pilot','approved',%s,%s,%s)",
                   (now-30, now+600, now-20))

    token = "qa25-synthetic-unified-test-token"
    env = {
        **REQUIRED, "DATABASE_URL": DSN, "PD_DISPATCH_ORDERS_DATABASE_URL": DSN,
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": DSN, "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_QA25_WSGI": "1", "PD_QA26_ASSIGNMENT": "1", "PD_QA27_GPS": "1",
        "PD_QA26_CSRF": "qa26-synthetic-unified-csrf",
        "PD_QA25_TELEGRAM_TEST_TOKEN": token, "PD_QA25_PASSENGERS": "101,102",
        "PD_QA25_ADMINS": "201", "PD_DISPATCH_ADMIN_ID": "201",
        "PD_DISPATCH_SESSION_SECRET": "qa-only-unified-session-secret-123456789",
        "PD_DISPATCH_ORDERS_INGEST_SECRET": "qa-only-unified-ingest-secret-123456789",
        "PD_DISPATCH_TEST_SYNC": "0", "TWILIO_VERIFY_ENABLED": "false",
        "PD_NATIVE_SMS_TEST_PHONE": "", "PD_NATIVE_SMS_LIVE": "NO",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                "TWILIO_VERIFY_SERVICE_SID", "PD_DISPATCH_DATABASE_URL",
                "PD_PAYSERA_MANUAL_ENABLED"):
        monkeypatch.delenv(key, raising=False)

    sys.modules.pop("isolated_sms_wsgi", None)
    native = Client(importlib.import_module("isolated_sms_wsgi").application, Response)
    from pd_qa25_wsgi import create_application
    miniapp = Client(create_application(), Response)
    passenger = {"Authorization": "Bearer " + "a"*48}
    pilot = {"Authorization": "Bearer " + "b"*48}
    tg = telegram_header(101, token)
    admin = telegram_header(201, token)

    assert native.get("/health").json["sms_enabled"] is False
    assert native.get("/native-orders").status_code == 401
    assert miniapp.get("/qa/staging/readiness", headers=admin).status_code == 200
    assert miniapp.get("/qa/staging/readiness", headers=tg).status_code == 403

    native_body = {"request_id": str(uuid.uuid4()), "from": "QA Native Airport",
                   "to": "QA Native City", "trip_date": "2027-01-01", "trip_time": "14:00"}
    telegram_body = {"request_key": uuid.uuid4().hex, "origin": "QA Telegram Airport",
                     "destination": "QA Telegram City", "trip_date": "2027-01-02",
                     "trip_time": "15:00"}
    assert native.post("/native-orders", json=native_body).status_code == 401
    android = native.post("/native-orders", json=native_body, headers=passenger)
    telegram = miniapp.post("/api/order", json=telegram_body, headers=tg)
    assert android.status_code == 201, android.get_data(as_text=True)
    assert telegram.status_code == 200, telegram.get_data(as_text=True)
    ids = {android.json["order_id"]: "android",
           telegram.json["order_id"]: "telegram_miniapp"}
    assert len(ids) == 2
    assert native.post("/native-orders", json=native_body, headers=passenger).json["order_id"] == android.json["order_id"]
    assert miniapp.post("/api/order", json=telegram_body, headers=tg).json["order_id"] == telegram.json["order_id"]
    assert miniapp.get("/api/orders", headers=telegram_header(102,token)).json["orders"] == []
    assert miniapp.get("/dispatch/orders/state", headers=tg).status_code == 401

    password = "qa-unified-browser-dispatcher-password"
    probe_env = dict(os.environ)
    probe_env["PD_DISPATCH_PASSWORD_HASH"] = generate_password_hash(password, method="pbkdf2:sha256")
    probe_env["QA_UNIFIED_DISPATCH_PASSWORD"] = password
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/qa_unified_dispatcher_probe.py"),
         str(DISPATCH), json.dumps(ids)],
        cwd=str(ROOT), env=probe_env, text=True, capture_output=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr[-5500:]
    confirmation = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(confirmation["orders"]) == set(ids)
    assert all(o["status"] == "assigned" for o in confirmation["orders"].values())

    history = native.get("/native-orders", headers=passenger)
    assert history.status_code == 200
    assert history.json["orders"][0]["status"] == "assigned"
    tg_history = miniapp.get("/api/orders", headers=tg)
    assert tg_history.status_code == 200
    assert tg_history.json["orders"][0]["status"] == "assigned"
    assigned = native.get("/native-pilot-orders", headers=pilot)
    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    assert {o["order_id"] for o in assigned.json["orders"]} == set(ids)

    captured_at = int(time.time()) - 3
    gps_path = "/native-pilot-orders/" + android.json["order_id"] + "/gps"
    gps_read = "/dispatch/orders/" + android.json["order_id"] + "/gps"
    fix = {"enabled": True, "captured_at": captured_at,
           "latitude": 54.6872, "longitude": 25.2797}
    assert miniapp.post(gps_path, json=fix, headers=passenger).status_code == 403
    assert miniapp.get(gps_read, headers=tg).status_code == 401
    written = miniapp.post(gps_path, json=fix, headers=pilot)
    assert written.status_code == 200, written.get_data(as_text=True)
    shown = miniapp.get(gps_read, headers=admin)
    assert shown.status_code == 200
    assert shown.json == {"available": True, "captured_at": captured_at,
                          "latitude": 54.6872, "longitude": 25.2797}
    # The merged browser WSGI reads the same GPS fix as QA27, via its
    # own authenticated dispatcher route, not the QA25 emulation.
    map_result = subprocess.run(
        [sys.executable, str(ROOT / "tests/qa_merged_browser_map_probe.py"),
         android.json["order_id"]],
        cwd=str(ROOT), env=probe_env, text=True, capture_output=True, timeout=45,
    )
    assert map_result.returncode == 0, map_result.stderr[-5500:]
    map_report = json.loads(map_result.stdout.strip().splitlines()[-1])
    assert all(map_report.values()), map_report
    assert miniapp.post(gps_path, json=fix, headers=pilot).status_code == 409
    stopped = miniapp.post(gps_path,
        json={"enabled": False, "captured_at": captured_at + 1}, headers=pilot)
    assert stopped.status_code == 200
    assert miniapp.get(gps_read, headers=admin).json == {"available": False}

    with psycopg.connect(DSN) as db:
        order_rows = db.execute(
            "SELECT o.id,o.source,o.status,a.pilot_user_id FROM public.pd_dispatch_orders o "
            "JOIN public.pd_native_order_assignments a ON o.id=a.order_id"
        ).fetchall()
        assert {(str(oid),source,status,pid) for oid,source,status,pid in order_rows} == {
            (oid,source,"assigned","unified-pilot") for oid,source in ids.items()}
        assert db.execute("SELECT count(*) FROM public.pd_dispatch_orders").fetchone() == (2,)

    monkeypatch.setenv("PD_PAYMENT_MODE", "live")
    assert native.post("/native-orders", json=native_body, headers=passenger).status_code == 503
    assert miniapp.get("/api/orders", headers=tg).status_code == 503
    assert miniapp.get(gps_read, headers=admin).status_code == 503
    print("UNIFIED QA PASS: Android + Telegram -> PostgreSQL -> pinned browser dispatcher "
          "-> pilot assignment -> passenger/pilot status -> GPS on/off; payments and SMS disabled")
