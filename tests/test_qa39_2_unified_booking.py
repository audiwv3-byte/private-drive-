import hashlib
import hmac
import json
import os
import ssl
import sqlite3
import subprocess
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import psycopg
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from pd_native_auth_postgres_http import initialize_database
from pd_qa25_wsgi import create_application


def telegram_data(token, uid):
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid})}
    key = hmac.digest(b"WebAppData", token.encode(), "sha256")
    fields = "\n".join(f"{name}={value}" for name, value in sorted(values.items()))
    values["hash"] = hmac.new(key, fields.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_booking_interfaces_share_postgres(monkeypatch, tmp_path):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    assert os.environ["PD_NATIVE_SMS_ISOLATED"] == "YES"
    assert os.environ["PD_NATIVE_SMS_LIVE"] == "NO"
    assert os.environ["PD_PAYMENT_MODE"] == "disabled"
    def reject_sqlite(*args, **kwargs):
        raise AssertionError("Unified booking opened SQLite")

    monkeypatch.setattr(sqlite3, "connect", reject_sqlite)
    initialize_database(dsn)

    native_token = "a" * 48
    with psycopg.connect(dsn, autocommit=True) as db:
        for migration in (
            "native_auth_session_functions.sql",
            "native_dispatch_orders.sql",
            "native_pilot_identity.sql",
            "qa26_pilot_assignment.sql",
        ):
            db.execute((Path("migrations") / migration).read_text())
        db.execute("CREATE ROLE qa_booking_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa_booking_api")
        db.execute("""
            GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners,
            public.pd_native_order_quotes, public.pd_telegram_order_owners TO qa_booking_api
        """)
        db.execute("GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint) TO qa_booking_api")
        db.execute("INSERT INTO native_auth_users VALUES ('qa-booking-passenger','phone','qa-booking-passenger',0)")
        db.execute("INSERT INTO native_auth_roles VALUES ('qa-booking-passenger','passenger')")
        now = int(time.time())
        db.execute("""
            INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at)
            VALUES (%s,'qa-booking-passenger',%s,%s)
        """, (hashlib.sha256(native_token.encode()).hexdigest(), now, now + 900))

    api_dsn = "postgresql://qa_booking_api:synthetic-api@127.0.0.1:5432/private_drive_test"
    tg_token = "qa25-synthetic-qa39-2-booking"
    for k, v in {
        "PD_QA25_WSGI": "1",
        "PD_QA25_TELEGRAM_TEST_TOKEN": tg_token,
        "PD_QA25_PASSENGERS": "101",
        "PD_QA25_ADMINS": "201",
        "PD_QA26_ASSIGNMENT": "1",
        "PD_QA26_CSRF": "qa26-synthetic-qa39-2",
        "PD_QA39_2_BOOKING_UI": "1",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1",
        "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_DISPATCH_ORDERS_DATABASE_URL": api_dsn,
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": api_dsn,
    }.items():
        monkeypatch.setenv(k, v)

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True, timeout=20)
    server = make_server("127.0.0.1", 0, create_application(), ssl_context=(str(cert), str(key)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"https://127.0.0.1:{server.server_port}"
    ack = tmp_path / "native-order-id"
    try:
        subprocess.run([
            "flutter", "test", "qa/qa39_2_booking_form_test.dart",
            "--no-pub", "--reporter", "expanded",
            f"--dart-define=PD_NATIVE_AUTH_API_URL={base}",
        ], cwd="flutter_app", check=True, timeout=180, env={
            **os.environ, "QA39_CERT": str(cert), "QA39_PASSENGER_TOKEN": native_token,
            "QA39_NATIVE_ORDER_ID_PATH": str(ack),
        })
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(ignore_https_errors=True)
                page.route("**/*", lambda route: route.continue_()
                           if urlsplit(route.request.url).netloc == urlsplit(base).netloc
                           else route.abort())
                init_data = json.dumps(telegram_data(tg_token, 101))
                page.add_init_script(f"window.Telegram = {{WebApp: {{initData: {init_data}, ready() {{}}, expand() {{}}}}}};")
                page.goto(base, wait_until="domcontentloaded")
                expect(page.locator("#step11")).to_be_visible()
                expect(page.locator("#pdbPays")).to_be_hidden()
                page.locator("#pdbOrigin").fill("Telegram pickup")
                page.locator("#pdbDest").fill("Telegram destination")
                page.locator("#pdbDate").fill((date.today() + timedelta(days=3)).isoformat())
                page.locator("#pdbAgree").check()
                with page.expect_response(lambda res: res.url == base + "/api/order") as sent:
                    page.locator("#pdbSend").click()
                response = sent.value
                assert response.ok, response.text()
                telegram = response.json()
                assert telegram["status"] == "requested" and telegram["payment_mode"] == "disabled"
                expect(page.locator("#pdbFeedback")).to_contain_text(telegram["order_id"])
                page.locator("#mainNav").get_by_role("button", name="Поездки").click()
                expect(page.locator("#orders")).to_contain_text(telegram["order_id"])
            finally:
                browser.close()

        admin = Request(base + "/dispatch/orders/state", headers={
            "X-Telegram-Init-Data": telegram_data(tg_token, 201),
        })
        with urlopen(admin, context=ssl.create_default_context(cafile=str(cert)), timeout=10) as response:
            queue = json.load(response)
        assert queue["persistent"] is True
        assert {(o["id"], o["source"], o["status"]) for o in queue["orders"]} == {
            (ack.read_text(), "android", "requested"),
            (telegram["order_id"], "telegram_miniapp", "requested"),
        }
        with psycopg.connect(dsn) as db:
            assert db.execute("SELECT count(*) FROM public.pd_dispatch_orders").fetchone() == (2,)
            assert db.execute("SELECT order_id::text, user_id FROM public.pd_native_order_owners").fetchall() == [
                (ack.read_text(), "qa-booking-passenger")
            ]
            assert db.execute("SELECT order_id::text, telegram_id FROM public.pd_telegram_order_owners").fetchall() == [
                (telegram["order_id"], 101)
            ]
        print("PASS Flutter and Telegram form acknowledgements match both PostgreSQL dispatcher orders")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
