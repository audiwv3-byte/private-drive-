"""Mobile Chromium with a synthetic Telegram SDK, real Flask apps and local PostgreSQL."""
import hashlib
import io
import json
import os
import re
from time import time as unix_time
from pathlib import Path
from datetime import timedelta
from threading import Thread
from unittest.mock import MagicMock

import psycopg
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

from pd_native_auth_postgres_http import initialize_database
from test_qa_actual_miniapp_postgres import DSN, ROOT, TOKEN, signed


def test_passenger_welcome(monkeypatch, tmp_path):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    password = "qa-browser-admin-password"
    dispatcher_password = "qa-browser-operator-password"
    pilot_token = "qa-synthetic-pilot-token-" * 3
    passenger_token = "qa-synthetic-passenger-token-" * 3
    for name, value in {
        "BOT_TOKEN": TOKEN,
        "ORS_API_KEY": "",
        "PD_QA_MINIAPP_POSTGRES": "1",
        "PD_QA25_WSGI": "1",
        "PD_QA26_ASSIGNMENT": "1",
        "PD_QA27_GPS": "1",
        "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": DSN,
        "PD_QA_DISPATCHER_ID": "202",
        "PD_QA_DISPATCHER_PASSWORD_HASH": generate_password_hash(dispatcher_password),
        "PD_DISPATCH_TEST_SYNC": "0",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1",
        "PD_DISPATCH_ORDERS_DATABASE_URL": DSN,
        "PD_NATIVE_SMS_ISOLATED": "YES",
        "PD_NATIVE_SMS_LIVE": "NO",
        "PD_PAYMENT_MODE": "disabled",
        "PD_DISPATCH_ADMIN_ID": "201",
        "PD_DISPATCH_DATABASE_URL": "",
        "PD_DISPATCH_PASSWORD_HASH": generate_password_hash(password),
        "PD_DISPATCH_SESSION_SECRET": "qa-only-dispatcher-session-secret-for-browser",
    }.items():
        monkeypatch.setenv(name, value)
    initialize_database(DSN)
    with psycopg.connect(DSN, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql", "native_dispatch_orders.sql",
                     "native_pilot_identity.sql", "qa26_pilot_assignment.sql", "qa27_pilot_gps.sql",
                     "qa_telegram_candidates.sql"):
            db.execute((ROOT / "migrations" / name).read_text())

        now = int(unix_time())
        for role, token in (("pilot", pilot_token), ("passenger", passenger_token)):
            uid = "qa-dispatch-" + role
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)", (uid, uid))
            db.execute("INSERT INTO native_auth_roles VALUES (%s,%s)", (uid, role))
            db.execute("""INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at)
                VALUES (%s,%s,%s,%s)""", (hashlib.sha256(token.encode()).hexdigest(), uid, now, now + 600))
        db.execute("""INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at)
            VALUES ('qa-dispatch-check','qa-dispatch-pilot','approved',%s,%s,%s)""",
            (now - 5, now + 600, now - 1))

    import telebot
    monkeypatch.setattr(telebot, "TeleBot", lambda *args, **kwargs: MagicMock())
    import Euro_Baltic_Transfer as core
    monkeypatch.setattr(core, "USERS_DB", tmp_path / "users.db")
    monkeypatch.setattr(core, "ORDERS_DB", tmp_path / "orders.db")
    core.initialize()
    import miniapp_server
    from pd_dispatcher_staging_wsgi import create_app
    from flask import Flask
    from pd_qa27_gps import register_gps
    pilot_api = Flask("qa_dispatch_gps")
    register_gps(pilot_api, lambda: False, DSN)
    miniapp = miniapp_server.app
    dispatcher = create_app()
    assert miniapp_server.qa_shared_orders_enabled()
    client = miniapp.test_client()
    for uid in (101, 102):
        response = client.post("/api/register/telegram", json={},
                               headers=signed(uid, first_name="QA Passenger"))
        assert response.status_code == 200, response.json
        assert response.json == {"name": "QA Passenger", "registered": False}
        response = client.post("/api/register", json={"name": "QA Passenger", "phone": "+37060000000"},
                               headers=signed(uid))
        assert response.status_code == 200, response.json

    def dispatch_application(environ, start_response):
        app = pilot_api if environ["PATH_INFO"].startswith("/native-pilot-orders/") else dispatcher
        return app(environ, start_response)

    miniapp_server_http = make_server("127.0.0.1", 0, miniapp, threaded=True)
    dispatcher_server_http = make_server("127.0.0.1", 0, dispatch_application, threaded=True)
    servers = (miniapp_server_http, dispatcher_server_http)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    base = f"http://127.0.0.1:{miniapp_server_http.server_port}"
    dispatch_base = f"http://127.0.0.1:{dispatcher_server_http.server_port}"

    leaflet_dir = os.environ.get("QA_LEAFLET_DIR")
    tile = io.BytesIO()
    picture = Image.new("RGB", (256, 256), "#dedbce")
    draw = ImageDraw.Draw(picture)
    for start in (44, 116, 203):
        draw.line((0, start, 256, start - 18), fill="#c3bd9d", width=4)
        draw.line((start, 0, start + 26, 256), fill="#c3bd9d", width=4)
    picture.save(tile, format="PNG")

    def configure_page(page, uid=None):
        def offline_routes(route):
            if route.request.url.startswith((base + "/", dispatch_base + "/")):
                route.continue_()
            elif route.request.url.startswith("https://telegram.org/js/"):
                init_data = signed(uid)["X-Telegram-Init-Data"] if uid else ""
                route.fulfill(content_type="application/javascript", body=(
                    "window.Telegram={WebApp:{initData:" + json.dumps(init_data)
                    + ",initDataUnsafe:{},ready(){},expand(){}}};"))
            elif leaflet_dir and route.request.url in (
                "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
                "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
            ):
                path = Path(leaflet_dir) / route.request.url.rsplit("/", 1)[1]
                route.fulfill(path=str(path), content_type=(
                    "application/javascript" if path.suffix == ".js" else "text/css"))
            elif leaflet_dir and route.request.url.startswith("https://tile.openstreetmap.org/"):
                route.fulfill(content_type="image/png", body=tile.getvalue())
            else:
                route.abort()
        page.route("**/*", offline_routes)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get("QA_CHROMIUM"),
                                                 args=["--no-sandbox"])
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            configure_page(page, 101)
            for lang, labels in {
                "en": ["Book a trip", "My trips", "Book in advance", "Sober driver", "Wheel of fortune", "Become a driver"],
                "lt": ["Užsakyti kelionę", "Mano kelionės", "Išankstinis užsakymas", "Blaivus vairuotojas", "Laimės ratas", "Tapti vairuotoju"],
                "ru": ["Заказать поездку", "Мои поездки", "Предзаказ", "Трезвый водитель", "Колесо фортуны", "Стать водителем"],
            }.items():
                page.goto(f"{base}/?lang={lang}")
                welcome = page.locator("#step0")
                expect(welcome).to_be_visible()
                expect(page.locator("#pdLangSelect")).to_have_count(1)
                expect(page.locator("#pdLangSelect")).to_have_value(lang)
                for label in labels:
                    expect(welcome.get_by_text(label, exact=True)).to_be_visible()
                expect(page.locator("#mainNav").get_by_text(labels[1], exact=True)).to_have_count(1)
                page.locator("#pdPassengerMenuToggle").click()
                expect(page.locator("#pdPassengerMenu").get_by_role("button", name=labels[1])).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#pdPassengerMenu")).to_be_hidden()

            screenshot = os.environ.get("QA_WELCOME_SCREENSHOT")
            if screenshot:
                page.reload()
                expect(welcome).to_be_visible()
                page.screenshot(path=screenshot, full_page=True)

            day = (core.now() + timedelta(days=2)).date().isoformat()
            requests = {}
            for entry_label, service, time in (("Заказать поездку", "Поездка", "11:30"),
                                                ("Предзаказ", "Предзаказ", "12:40")):
                page.locator("#step0").get_by_role("button", name=entry_label).click()
                expect(page.locator("#step11")).to_be_visible()
                if service == "Предзаказ":
                    expect(page.locator("#pdbDate")).to_be_focused()
                page.locator("#pdbOrigin").fill("QA pickup Vilnius")
                page.locator("#pdbDest").fill("QA destination Kaunas")
                page.locator("#pdbDate").fill(day)
                page.locator("#pdbTime").fill(time)
                page.locator("#pdbAgree").check()
                with page.expect_response(lambda r: r.url == base + "/api/order") as result:
                    page.locator("#pdbSend").click()
                assert result.value.ok, result.value.text()
                requests[service] = (result.value.json()["order_id"], time)
                page.locator("#pdPassengerMenuToggle").click()
                page.locator("#pdPassengerMenu").get_by_role("button", name="Главная").click()

            opening = page.locator("#step0").get_by_role("button", name="Трезвый водитель")
            opening.click()
            sober = page.locator(".pd-sober-form")
            sober.locator("[name=origin]").fill("QA sober pickup")
            sober.locator("[name=destination]").fill("QA sober destination")
            sober.locator("[name=trip_date]").fill(day)
            sober.locator("[name=trip_time]").fill("14:20")
            expect(sober.get_by_text("Стоимость подтвердит диспетчер")).to_be_visible()
            with page.expect_response(lambda r: r.url == base + "/api/route") as unavailable:
                sober.get_by_role("button", name="Рассчитать стоимость").click()
            assert unavailable.value.json()["available"] is False
            monkeypatch.setattr(core, "route", lambda a, b: (12.0, 21.0))
            with page.expect_response(lambda r: r.url == base + "/api/route") as estimate:
                sober.get_by_role("button", name="Рассчитать стоимость").click()
            price = estimate.value.json()["price"]
            assert price == miniapp_server.pd_pet_price(core.quote(12, 21), {"extras": ["Трезвый водитель"]})
            expect(sober.get_by_text(price + " €")).to_be_visible()
            with page.expect_response(lambda r: r.url == base + "/api/order") as result:
                sober.get_by_role("button", name="Отправить заявку").click()
            assert result.value.ok, result.value.text()
            requests["Трезвый водитель"] = (result.value.json()["order_id"], "14:20")

            page.locator("#pdPassengerMenuToggle").click()
            page.locator("#pdPassengerMenu").get_by_role("button", name="Главная").click()
            page.locator("#step0").get_by_role("button", name="Мои поездки").click()
            passenger = page.locator("#step8")
            expect(passenger).to_be_visible()
            for service, (oid, time) in requests.items():
                card = passenger.locator("article").filter(has_text=oid)
                expect(card).to_contain_text(service)
                expect(card).to_contain_text(day + " " + time)
            expect(passenger.locator("article").filter(has_text="Трезвый водитель")).to_contain_text(price + " €")
            foreign_history = client.get("/api/orders", headers=signed(102)).json
            assert foreign_history == {"orders": []}

            before = client.get("/api/orders", headers=signed(101)).json
            page.locator("#pdPassengerMenuToggle").click()
            page.locator("#pdPassengerMenu").get_by_role("button", name="Главная").click()
            page.locator("#step0").get_by_role("button", name="Колесо фортуны").click()
            expect(page.locator("#pdWelcomeWheel")).to_contain_text("Демо")
            assert page.locator("#pdWheelDisk span").all_text_contents() == ["5%", "10%", "15%", "20%"]
            page.get_by_role("button", name="Крутить").click()
            expect(page.locator("#pdWheelResult")).to_have_text(re.compile(r"(5|10|15|20)%$"))
            assert client.get("/api/orders", headers=signed(101)).json == before

            page.get_by_role("link", name="Стать водителем").click()
            expect(page.locator("#pdObDriver")).to_be_visible()
            expect(page.locator("#pdObDriverName")).to_have_value("QA Passenger")
            for element, value in {"City": "Vilnius", "Vehicle": "Toyota RAV4", "Year": "2024", "Plate": "QA 101"}.items():
                page.locator("#pdObDriver" + element).fill(value)
            for index, side in enumerate(("license_front", "license_back", "car_front", "car_rear", "car_interior")):
                image = io.BytesIO()
                Image.new("RGB", (1200, 800), (30 + 20 * index, 80, 130)).save(image, "JPEG")
                page.locator("#pdPhoto_" + side).set_input_files(
                    {"name": side + ".jpg", "mimeType": "image/jpeg", "buffer": image.getvalue()})
                expect(page.locator("#pdPhotoStatus_" + side)).to_contain_text("Фото добавлено")
            with page.expect_response(lambda r: r.url == base + "/api/driver/application") as applicant:
                page.locator("#pdObDriverSubmit").click()
            assert applicant.value.ok, applicant.value.text()
            expect(page.locator("#pdObReceived")).to_be_visible()
            page.locator("#pdObReceived").get_by_role("button", name="Продолжить как пассажир").click()
            expect(page.locator("#step0")).to_be_visible()
            page.reload()
            expect(page.locator("#step0")).to_be_visible()
            me = client.get("/api/me", headers=signed(101)).json
            assert me["id"] == 101 and me["registered"] and not me["pilot_access"] and not me["admin"]
            assert me["driver_application"]["status"] == "pending"
            assert client.get("/api/me", headers=signed(102)).json["driver_application"] is None

            page.get_by_role("link", name="Стать водителем").click()
            expect(page.locator("#pdObDriverCity")).to_have_value("Vilnius")
            page.locator("#pdObDriverCity").fill("Kaunas")
            with page.expect_response(lambda r: r.url == base + "/api/driver/application") as repeated:
                page.locator("#pdObDriverSubmit").click()
            assert repeated.value.ok, repeated.value.text()
            assert not client.get("/api/me", headers=signed(101)).json["pilot_access"]
            with psycopg.connect(DSN) as db:
                assert db.execute("""
                    SELECT telegram_id, city, status FROM pd_qa_telegram_candidates
                """).fetchall() == [(101, "Kaunas", "pending")]
            photo_path = "/api/driver/documents/101/license_front"
            own_photo = client.get(photo_path, headers=signed(101))
            assert own_photo.status_code == 200 and own_photo.mimetype == "image/jpeg"
            assert client.get(photo_path, headers=signed(102)).status_code == 401

            def login(page, secret):
                page.goto(dispatch_base + "/dispatch/map")
                expect(page).to_have_url(dispatch_base + "/dispatch/login")
                page.locator("input[name=password]").fill(secret)
                page.locator("form").filter(has=page.locator("input[name=password]")).get_by_role(
                    "button", name="Войти").click()
                expect(page).to_have_url(dispatch_base + "/dispatch")

            for bearer, uid in ((passenger_token, 101), (pilot_token, 103)):
                auth = {**signed(uid), "Authorization": "Bearer " + bearer}
                forbidden = dispatcher.test_client()
                assert forbidden.get("/dispatch", headers=auth).location.endswith("/dispatch/login")
                assert forbidden.get("/dispatch/orders/state", headers=auth).status_code == 401
                assert forbidden.get("/dispatch/telegram-candidates", headers=auth).location.endswith("/dispatch/login")
                assert forbidden.post("/dispatch/orders/" + requests["Поездка"][0] + "/assign",
                                      headers=auth, data={"pilot_id": "qa-dispatch-pilot"}).status_code == 401

            admin = browser.new_page()
            configure_page(admin)
            login(admin, password)
            assert admin.request.get(dispatch_base + "/dispatch/orders/state").ok
            admin.close()

            dispatch = browser.new_page(viewport={"width": 1440, "height": 900})
            configure_page(dispatch)
            baseline = os.environ.get("QA_DISPATCH_BASELINE")
            screenshots = os.environ.get("QA_DISPATCH_SCREENSHOTS")
            if baseline and screenshots:
                baseline_html = Path(baseline).read_text(encoding="utf-8")
                original_read = Path.read_text
                def read_baseline(path, *args, **kwargs):
                    if path.name == "pd_dispatcher_mapbox.html":
                        return baseline_html
                    return original_read(path, *args, **kwargs)
                with monkeypatch.context() as before:
                    before.setattr(Path, "read_text", read_baseline)
                    login(dispatch, dispatcher_password)
                    expect(dispatch.locator("#topSheet")).to_be_visible()
                    expect(dispatch.locator("#ordersList .card").first).to_be_visible()
                    dispatch.screenshot(path=str(Path(screenshots) / "PRIVATE-DRIVE-Dispatcher-Before.png"))
                dispatch.reload()
            else:
                login(dispatch, dispatcher_password)

            assert dispatch.request.get(dispatch_base + "/dispatch/orders/state").ok
            alias = dispatch.request.get(dispatch_base + "/dispatch/map", max_redirects=0)
            assert alias.status == 302 and alias.headers["location"] == "/dispatch"
            for service, (oid, time_slot) in requests.items():
                card = dispatch.locator("#ordersList .card").filter(has_text=oid)
                expect(card).to_contain_text(service)
                expect(card).to_contain_text(day + " " + time_slot)

            dispatch.get_by_role("button", name="Пассажиры", exact=True).click()
            expect(dispatch.locator("#passengerDirectory")).to_be_visible()
            dispatch.locator("#dispatchMenuToggle").click()
            menu = dispatch.locator("#dispatchMenu")
            expect(menu).to_be_visible()
            menu.get_by_role("link", name="Пилоты", exact=True).click()
            expect(menu).to_be_hidden()
            expect(dispatch.locator("#pilotDirectory")).to_be_visible()

            order_id = requests["Поездка"][0]
            card = dispatch.locator("#ordersList .card").filter(has_text=order_id)
            card.locator("select").select_option("qa-dispatch-pilot")
            card.get_by_role("button", name="Назначить пилота").click()
            card.get_by_role("button", name="Пилот на карте").click()
            fix = {"enabled": True, "captured_at": int(unix_time()),
                   "latitude": 54.6872, "longitude": 25.2797}
            gps_url = dispatch_base + "/native-pilot-orders/" + order_id + "/gps"
            assert dispatch.request.post(gps_url, data=fix, headers={
                "Authorization": "Bearer " + passenger_token}).status == 403
            assert dispatch.request.post(gps_url, data=fix, headers={
                "Authorization": "Bearer " + pilot_token}).ok
            gps = dispatch.request.get(dispatch_base + "/dispatch/orders/" + order_id + "/gps").json()
            assert (gps["latitude"], gps["longitude"]) == (54.6872, 25.2797)
            marker = dispatch.locator(".leaflet-marker-pane .pilot-marker")
            expect(marker).to_be_visible(timeout=12_000)
            with psycopg.connect(DSN) as db:
                assert db.execute("SELECT assigned_by FROM pd_native_order_assignments WHERE order_id=%s",
                                  (order_id,)).fetchone() == ("202",)
            if screenshots:
                dispatch.screenshot(path=str(Path(screenshots) / "PRIVATE-DRIVE-Dispatcher-After.png"))
                dispatch.locator("#dispatchMenuToggle").click()
                dispatch.screenshot(path=str(Path(screenshots) / "PRIVATE-DRIVE-Dispatcher-Menu.png"))
                dispatch.keyboard.press("Escape")
            off = {"enabled": False, "captured_at": fix["captured_at"] + 1}
            assert dispatch.request.post(gps_url, data=off, headers={
                "Authorization": "Bearer " + pilot_token}).ok
            expect(marker).to_have_count(0, timeout=12_000)
            dispatch.locator("#dispatchMenuToggle").click()
            menu.get_by_role("link", name="Анкеты из Telegram").click()
            expect(dispatch.get_by_text("QA Passenger", exact=True)).to_have_count(1)
            expect(dispatch.get_by_text("Kaunas", exact=False)).to_be_visible()
            expect(dispatch.get_by_text("На проверке")).to_be_visible()
            with psycopg.connect(DSN, autocommit=True) as db:
                db.execute("ALTER TABLE pd_qa_telegram_candidates RENAME TO pd_qa_telegram_candidates_offline")
                try:
                    offline = dispatch.request.get(dispatch_base + "/dispatch/telegram-candidates")
                    assert offline.status == 503 and "no-store" in offline.headers["cache-control"]
                    application = client.get("/api/me", headers=signed(101)).json["driver_application"]
                    application["city"] = "Trakai"
                    unavailable = client.post("/api/driver/application", json=application, headers=signed(101))
                    assert unavailable.status_code == 503
                finally:
                    db.execute("ALTER TABLE pd_qa_telegram_candidates_offline RENAME TO pd_qa_telegram_candidates")
            retried = client.post("/api/driver/application", json=application, headers=signed(101))
            assert retried.status_code == 200
            dispatch.reload()
            expect(dispatch.get_by_text("Trakai", exact=False)).to_be_visible()
            expect(dispatch.get_by_text("QA Passenger", exact=True)).to_have_count(1)
            print("PASS independent Mini App and dispatcher WSGI, candidate upsert, private photos, roles, orders and GPS")
            browser.close()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
