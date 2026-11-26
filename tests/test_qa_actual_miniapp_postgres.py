"""Actual Telegram Mini App WSGI -> synthetic PostgreSQL, no SQLite order queue.

The test substitutes only the Telegram transport client; it imports the real
miniapp_server Flask app and executes real signed Telegram HTTP requests.
"""
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse
import uuid

import psycopg
from unittest.mock import MagicMock

from pd_native_auth_postgres_http import initialize_database

DSN = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = "qa25-synthetic-telegram-api-contract-token"


def signed(uid):
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid})}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    plain = "\n".join(key+"="+val for key,val in sorted(values.items()))
    values["hash"] = hmac.new(secret, plain.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urllib.parse.urlencode(values)}


def test_actual_telegram_miniapp_orders_use_only_synthetic_postgres(monkeypatch):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    for k,v in {
        "BOT_TOKEN":TOKEN, "PD_QA_MINIAPP_POSTGRES":"1",
        "PD_QA25_WSGI":"1", "PD_QA26_ASSIGNMENT":"1",
        "PD_DISPATCH_STAGING_ONLY":"1", "PD_DISPATCH_PERSISTENT_QUEUE":"1",
        "PD_NATIVE_PILOT_ASSIGNMENT":"1",
        "PD_PILOT_ASSIGNMENT_DATABASE_URL":DSN,
        "PD_DISPATCH_ORDERS_DATABASE_URL":DSN,
        "PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO",
        "PD_PAYMENT_MODE":"disabled", "PD_QA25_TELEGRAM_TEST_TOKEN":TOKEN,
        "PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201",
        "PD_QA26_CSRF":"qa26-synthetic-miniapp-csrf",
        "PD_DISPATCH_ORDERS_INGEST_SECRET":"qa-synthetic-ingest-key-123456789abcdef",
    }.items():
        monkeypatch.setenv(k,v)

    initialize_database(DSN)
    with psycopg.connect(DSN, autocommit=True) as db:
        for sql in ("native_auth_session_functions.sql","native_dispatch_orders.sql",
                    "native_pilot_identity.sql","qa26_pilot_assignment.sql"):
            db.execute((ROOT / "migrations" / sql).read_text())

    import telebot
    monkeypatch.setattr(telebot, "TeleBot", lambda *a,**kw: MagicMock())
    import pd_stops
    monkeypatch.setattr(pd_stops, "ensure_schema", lambda *a,**kw: None)
    sys.modules.pop("Euro_Baltic_Transfer", None)
    sys.modules.pop("miniapp_server", None)
    app_module = importlib.import_module("miniapp_server")
    core = app_module.core
    monkeypatch.setattr(core, "user_record", lambda uid:
        {"name":"Synthetic Passenger","phone":"+37060000000"})
    monkeypatch.setattr(core, "clean_phone", lambda value: value)
    monkeypatch.setattr(core, "order_save", lambda *a, **kw:
        (_ for _ in ()).throw(AssertionError("SQLite order queue accessed")))
    original_db = core.db
    def no_order_sqlite(path):
        if str(path) == str(core.ORDERS_DB):
            raise AssertionError("SQLite orders.db must not be read or written")
        return original_db(path)
    monkeypatch.setattr(core, "db", no_order_sqlite)

    app = app_module.app
    client = app.test_client()
    body = {"origin":"QA Telegram Pickup","destination":"QA Telegram Airport",
            "trip_date":"01.01.2027","trip_time":"13:30",
            "request_key":uuid.uuid4().hex,"payment_method":"Наличными",
            "booking_details":{"tariff":"Трансфер","ride_type":"Трансфер",
              "round_trip":True,"advance_booking":True,
              "extras":["Встреча с табличкой","Вода"],
              "wishes":"В салоне 21 градус","passengers":2,
              "luggage":"Средний","fare_preview_eur":110}}
    assert app_module.qa_shared_orders_enabled()
    assert client.post("/api/order", json=body).status_code == 401
    created = client.post("/api/order", json=body, headers=signed(101))
    assert created.status_code in (200,201), created.get_data(as_text=True)
    assert created.json["details_saved"] is True
    assert created.json["details_not_saved"] is False
    oid = created.json["order_id"]
    assert str(uuid.UUID(oid)) == oid
    replay = client.post("/api/order",json=body,headers=signed(101))
    assert replay.status_code == 200
    assert replay.json["order_id"] == oid and replay.json["replayed"] is True
    conflict = client.post("/api/order",json={**body,"destination":"Other Location"},
                           headers=signed(101))
    assert conflict.status_code == 409

    history = client.get("/api/orders",headers=signed(101))
    assert history.status_code == 200
    assert len(history.json["orders"]) == 1
    assert history.json["orders"][0]["order_id"] == oid
    assert history.json["orders"][0]["trip_date"] == "2027-01-01"
    details = history.json["orders"][0]["booking_details"]
    assert details["fare_preview_eur"] == 110
    assert details["extras"] == ["Встреча с табличкой","Вода"]
    assert details["wishes"] == "В салоне 21 градус"
    assert client.get("/api/orders",headers=signed(102)).json == {"orders":[]}
    assert client.post("/api/order", json={**body,"payment_method":"Банковская карта"},
                       headers=signed(101)).status_code == 503

    from pd_qa25_wsgi import create_application
    dispatcher = create_application()
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    dispatch = Client(dispatcher, Response)
    assert dispatch.get("/dispatch/orders/state",headers=signed(101)).status_code == 401
    admin = dispatch.get("/dispatch/orders/state",headers=signed(201))
    assert admin.status_code == 200
    orders = admin.json["orders"]
    assert any(o["id"]==oid and o["source"]=="telegram_miniapp"
               and o["booking_details"]["passengers"] == 2
               and o["booking_details"]["round_trip"] is True for o in orders)
    with psycopg.connect(DSN) as db:
        assert db.execute("SELECT count(*) FROM public.pd_dispatch_orders").fetchone() == (1,)
        assert db.execute("SELECT telegram_id FROM public.pd_telegram_order_owners "
                          "WHERE order_id=%s",(oid,)).fetchone() == (101,)

    # QA flag on a nonlocal database must fail closed without falling back to SQLite.
    monkeypatch.setenv("PD_DISPATCH_ORDERS_DATABASE_URL",
                       "postgresql://qa@database.example/production")
    denied = client.post("/api/order",json=body,headers=signed(101))
    assert denied.status_code == 503 and denied.json["error"] == "orders_disabled"
    assert not app_module.qa_shared_orders_enabled()
    print("MINIAPP POSTGRES PASS: real signed Mini App endpoints -> synthetic PostgreSQL "
          "-> dispatcher; zero SQLite order reads/writes")
