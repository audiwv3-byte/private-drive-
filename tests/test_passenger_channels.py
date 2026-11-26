"""Passenger entry points and dispatcher assignments on synthetic loopback PostgreSQL."""
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit

import psycopg
from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_native_auth_postgres_http import initialize_database
from pd_qa_native_orders_mount import REQUIRED
from test_qa_unified_release import telegram_header, DSN


def test_passenger_channels(monkeypatch, tmp_path):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    password = "synthetic-dispatcher-password"
    token = "123456:synthetic-channel-test"
    for key, value in {**REQUIRED, "DATABASE_URL": DSN, "BOT_TOKEN": token,
                       "PD_DISPATCH_ORDERS_DATABASE_URL": DSN, "PD_NATIVE_PILOT_ASSIGNMENT": "1",
                       "PD_PILOT_ASSIGNMENT_DATABASE_URL": DSN, "PD_DISPATCH_ADMIN_ID": "201",
                       "PD_SOLE_TELEGRAM_ADMIN_ID": "201", "PD_DISPATCH_TEST_SYNC": "0",
                       "PD_DISPATCH_SESSION_SECRET": "synthetic-browser-dispatcher-secret-qa",
                       "PD_DISPATCH_PASSWORD_HASH": generate_password_hash(password),
                       "ORS_API_KEY": ""}.items():
        monkeypatch.setenv(key, value)
    initialize_database(DSN)
    now = int(time.time())
    run = uuid.uuid4().hex[:10]
    accounts = {}
    with psycopg.connect(DSN, autocommit=True) as db:
        for name in ("native_auth_session_functions", "native_dispatch_orders",
                     "native_pilot_identity", "qa26_pilot_assignment"):
            db.execute(Path(f"migrations/{name}.sql").read_text())
        for role in ("passenger", "pilot"):
            uid = f"{run}-{role}"
            bearer = uuid.uuid4().hex + uuid.uuid4().hex
            accounts[role] = {"Authorization": f"Bearer {bearer}"}
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)", (uid, uid))
            db.execute("INSERT INTO native_auth_roles VALUES (%s,%s)", (uid, role))
            db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) "
                       "VALUES (%s,%s,%s,%s)", (hashlib.sha256(bearer.encode()).hexdigest(), uid, now, now+600))
        db.execute("INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at) "
                   "VALUES (%s,%s,'approved',%s,%s,%s)", (run, uid, now-5, now+600, now-1))

    import Euro_Baltic_Transfer as core
    monkeypatch.setattr(core, "ORDERS_DB", tmp_path / "orders.db")
    monkeypatch.setattr(core, "USERS_DB", tmp_path / "users.db")
    monkeypatch.setattr(core, "route", lambda *args: (None, None))
    import miniapp_server
    import isolated_sms_wsgi
    from pd_dispatcher_staging_wsgi import create_app
    mini = miniapp_server.app.test_client()
    site = create_app().test_client()
    native = Client(isolated_sms_wsgi.application, Response)
    tomorrow = date.today() + timedelta(days=2)
    ids = {}
    browser_errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PD_TEST_CHROME"))
        page = browser.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        clients = {"mini.test": mini, "site.test": site}

        def serve(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname not in clients:
                route.abort()
                return
            response = clients[url.hostname].open(
                url.path + ("?" + url.query if url.query else ""), base_url="https://" + url.hostname,
                method=req.method, headers={k:v for k,v in req.headers.items()
                                            if k in ("content-type", "x-telegram-init-data")},
                data=req.post_data_buffer)
            route.fulfill(status=response.status_code, content_type=response.content_type, body=response.data)

        page.route("**/*", serve)
        init_data = telegram_header(201, token)["X-Telegram-Init-Data"]
        page.add_init_script("window.Telegram={WebApp:{ready(){},expand(){},initData:" +
                             json.dumps(init_data) + ",initDataUnsafe:{start_param:'driver_taxi_lt'}}};")
        page.goto("https://mini.test/?start=driver_taxi_lt&lang=ru")
        page.locator('#pdObLanguage button[lang=ru]').click()
        page.locator('#pdObPassengerName').fill("QA Passenger")
        page.locator('#pdObPassengerPhone').fill("+37060000000")
        page.locator('#pdObPassengerSubmit').click()
        page.locator('#pdbOrigin').fill('Vilnius')
        page.locator('#pdbDest').fill('Kaunas')
        page.locator('#pdbDate').fill(tomorrow.isoformat())
        page.locator('#pdbTime').fill("14:00")
        page.locator('#pdbAgree').check()
        with page.expect_response(lambda r: urlsplit(r.url).path == '/api/order') as sent:
            page.locator('#pdbSend').click()
        receipt = sent.value.json()
        assert sent.value.ok, receipt
        ids[receipt["dispatch_order_id"]] = "telegram_miniapp"
        again = mini.post("/api/order", json=sent.value.request.post_data_json,
                          headers=telegram_header(201, token))
        assert again.json["replayed"] and again.json["dispatch_order_id"] == receipt["dispatch_order_id"]
        page.reload()
        page.locator('#pdbSend').wait_for()
        assert not page.locator('#pdObRole,#adminNav,#pdPilotWork,#step10,#step13').count()
        assert mini.get(f"/api/trip/{receipt['order_id']}?view=passenger",
                        headers=telegram_header(201, token)).json["role"] == "passenger"
        page.goto("https://site.test/")
        for prefix, submit, origin, dest in [
                ("quick", "#quick-trip-form button[type=submit]", "#quick-from", "#quick-to"),
                ("pickup", "#submit-qa-order", "#pickup-address", "#dropoff-address")]:
            page.locator(origin).fill("Vilnius")
            page.locator(dest).fill("Kaunas")
            page.locator(f"#{prefix}-date").fill(tomorrow.isoformat())
            page.locator(f"#{prefix}-time").fill("14:00")
            with page.expect_response(lambda r: urlsplit(r.url).path == "/preview/api/qa-booking") as sent:
                page.locator(submit).click()
            assert sent.value.status == 201, sent.value.body()
            oid = sent.value.json()["trip"]["id"]
            ids[oid] = "website"
            duplicate = site.post("/preview/api/qa-booking", json=sent.value.request.post_data_json)
            assert duplicate.status_code == 200 and duplicate.json["trip"]["id"] == oid
        browser.close()
    assert not browser_errors, browser_errors

    body = {"request_id": str(uuid.uuid4()), "from":"Vilnius", "to":"Kaunas",
            "trip_date":tomorrow.isoformat(), "trip_time":"14:00",
            "details":{"ride_type":"taxi", "round_trip":False, "extras":[], "preferences":{}}}
    android = native.post("/native-orders", headers=accounts["passenger"], json=body)
    assert android.status_code == 201, android.json
    ids[android.json["order_id"]] = "android"
    assert native.post("/native-orders", headers=accounts["passenger"], json=body).json["order_id"] == android.json["order_id"]
    assert len(ids) == 4
    base = "https://site.test"
    assert site.get("/dispatch/orders/state", base_url=base).status_code == 401
    login = site.get("/dispatch/login", base_url=base)
    csrf = re.search(r'name="csrf" value="([^"]+)"', login.text)[1]
    assert site.post("/dispatch/login", base_url=base,
                     data={"csrf":csrf, "password":password}).status_code in (302,303)
    rows = site.get("/dispatch/orders/state", base_url=base).json["orders"]
    assert {r["id"]:r["source"] for r in rows if r["id"] in ids} == ids
    with site.session_transaction(base_url=base + "/dispatch") as session:
        csrf = session["pd_dispatch_csrf"]
    for oid in ids:
        result = site.post(f"/dispatch/orders/{oid}/assign", base_url=base,
                           data={"csrf":csrf, "pilot_id":uid})
        assert result.status_code == 200, result.json
    assigned = native.get("/native-pilot-orders", headers=accounts["pilot"])
    assert {r["order_id"] for r in assigned.json["orders"]} == set(ids)
    assert mini.get("/api/orders", headers=telegram_header(201,token)).json["orders"][0]["dispatch_status"] == "Пилот назначен"
    print("PASS Telegram booking as admin via old pilot link, both website forms, Android API, "
          "idempotent retries, authenticated dispatch, assigned pilot API and passenger status")
