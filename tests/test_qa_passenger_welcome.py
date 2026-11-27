"""Mobile Chromium with a synthetic Telegram SDK, real Flask apps and local PostgreSQL."""
import io
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import timedelta
from threading import Thread
from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg import sql
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

from pd_native_auth_postgres_http import initialize_database
from test_qa_actual_miniapp_postgres import DSN, ROOT, TOKEN, signed


@pytest.fixture
def candidates_database(monkeypatch):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    name = "private_drive_candidates_" + uuid.uuid4().hex
    database = sql.Identifier(name)
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(database))
        try:
            # The applications accept PostgreSQL URLs as deployment settings.
            dsn = DSN.rsplit("/", 1)[0] + "/" + name
            monkeypatch.setenv("PD_QA_TELEGRAM_CANDIDATES_DATABASE_URL", dsn)
            with psycopg.connect(dsn, autocommit=True) as db:
                db.execute((ROOT / "migrations" / "qa_telegram_candidates.sql").read_text())

            def available(allowed):
                admin.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS {}").format(
                    database, sql.Literal(allowed)))

            yield dsn, available
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(database))


@pytest.fixture
def dispatcher_url(tmp_path):
    # Start the dispatcher WSGI entry in a separate process with its own data
    # directory. It serves requests independently of the Mini App WSGI server.
    def start():
        directory = tmp_path / "dispatcher"
        directory.mkdir()
        return subprocess.Popen(
            [sys.executable, "-u", "-c", """
from unittest.mock import patch
from werkzeug.serving import make_server
from pd_dispatcher_staging_wsgi import application
sqlite = patch("sqlite3.connect", side_effect=AssertionError("Dispatcher must not access SQLite"))
sqlite.start()
server = make_server("127.0.0.1", 0, application)
print(server.server_port)
server.serve_forever()
"""],
            cwd=directory, env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdout=subprocess.PIPE, text=True,
        )

    launch = []
    def url():
        process = start()
        launch.append(process)
        port = int(process.stdout.readline())
        return f"http://127.0.0.1:{port}"

    yield url
    for process in launch:
        process.terminate()
        process.communicate(timeout=10)


def test_passenger_welcome(monkeypatch, tmp_path, candidates_database, dispatcher_url):
    candidates_dsn, set_candidates_available = candidates_database
    password = "qa-browser-dispatcher-password"
    for name, value in {
        "BOT_TOKEN": TOKEN,
        "ORS_API_KEY": "",
        "PD_QA_MINIAPP_POSTGRES": "1",
        "PD_QA25_WSGI": "1",
        "PD_QA26_ASSIGNMENT": "1",
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
                     "native_pilot_identity.sql", "qa26_pilot_assignment.sql"):
            db.execute((ROOT / "migrations" / name).read_text())

    import telebot
    monkeypatch.setattr(telebot, "TeleBot", lambda *args, **kwargs: MagicMock())
    import Euro_Baltic_Transfer as core
    miniapp_data = tmp_path / "miniapp"
    miniapp_data.mkdir()
    monkeypatch.setattr(core, "USERS_DB", miniapp_data / "users.db")
    monkeypatch.setattr(core, "ORDERS_DB", miniapp_data / "orders.db")
    core.initialize()
    import miniapp_server
    miniapp = miniapp_server.app
    dispatch_base = dispatcher_url()
    assert miniapp_server.qa_shared_orders_enabled()
    client = miniapp.test_client()
    for uid in (101, 102):
        response = client.post("/api/register", json={"name": "QA Passenger", "phone": "+37060000000"},
                               headers=signed(uid))
        assert response.status_code == 200, response.json

    server = make_server("127.0.0.1", 0, miniapp, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def configure_page(page, uid=None, origin=base):
        def offline_routes(route):
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            elif route.request.url.startswith("https://telegram.org/js/"):
                init_data = signed(uid)["X-Telegram-Init-Data"] if uid else ""
                route.fulfill(content_type="application/javascript", body=(
                    "window.Telegram={WebApp:{initData:" + json.dumps(init_data)
                    + ",initDataUnsafe:{},ready(){},expand(){},isVersionAtLeast(){return true},requestContact(){throw Error('Unexpected contact request')}}};"))
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
                page.locator("#pdPassengerMenuToggle").click()
                expect(page.locator("#pdPassengerMenu").get_by_role("button", name=labels[1])).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#pdPassengerMenu")).to_be_hidden()

            with page.expect_response(lambda r: r.url == base + "/api/register/telegram") as login:
                page.evaluate("pdbRegisterTelegram()")
            assert login.value.request.method == "POST" and login.value.json()["registered"]
            outside_telegram = browser.new_page()
            configure_page(outside_telegram)
            outside_login_requests = []
            outside_telegram.on("request", lambda request: outside_login_requests.append(request)
                                if request.url.endswith("/api/register/telegram") else None)
            outside_telegram.goto(base + "/?lang=ru")
            outside_telegram.evaluate("pdbRegisterTelegram()")
            assert outside_telegram.locator("#pdbProfileStatus a").get_attribute("href").startswith("https://t.me/")
            assert not outside_login_requests

            screenshot = os.environ.get("QA_WELCOME_SCREENSHOT")
            if screenshot:
                page.reload()
                expect(welcome).to_be_visible()
                page.screenshot(path=screenshot, full_page=True)

            day = (core.now() + timedelta(days=2)).date().isoformat()
            requests = {}
            coordinates = [[25.2797, 54.6872], [23.9036, 54.8985]]
            summary = {"distance": 12000, "duration": 1260}

            def ors_response(request, timeout):
                assert core.ORS_API_KEY == "synthetic-ors-key"
                if "/geocode/search?" in request.full_url:
                    index = int("destination" in request.full_url)
                    payload = {"features": [{"geometry": {"coordinates": coordinates[index]}}]}
                else:
                    assert request.get_header("Authorization") == "synthetic-ors-key"
                    assert json.loads(request.data)["coordinates"] == coordinates
                    if request.full_url.endswith("/geojson"):
                        payload = {"features": [{"properties": {"summary": summary},
                                                 "geometry": {"coordinates": coordinates}}]}
                    else:
                        assert request.full_url.endswith("/driving-car")
                        payload = {"routes": [{"summary": summary}]}
                return io.BytesIO(json.dumps(payload).encode())

            ors_transport = MagicMock(side_effect=ors_response)
            monkeypatch.setattr(core.urllib.request, "urlopen", ors_transport)
            for entry_label, service, time in (("Заказать поездку", "Поездка", "11:30"),
                                                ("Предзаказ", "Предзаказ", "12:40")):
                page.locator("#step0").get_by_role("button", name=entry_label).click()
                expect(page.locator("#step11")).to_be_visible()
                if service == "Предзаказ":
                    expect(page.locator("#pdbDate")).to_be_focused()
                page.locator("#pdbOrigin").fill("QA pickup A")
                page.locator("#pdbDest").fill("QA destination B")
                if service == "Поездка":
                    calculate = page.locator(".pd-route-calculate")
                    with page.expect_response(lambda r: r.url == base + "/api/route") as unavailable:
                        calculate.click()
                    assert unavailable.value.json()["available"] is False
                    ors_transport.assert_not_called()
                    expect(page.locator("#pdbPrice")).to_have_text("По согласованию")
                    monkeypatch.setattr(core, "ORS_API_KEY", "synthetic-ors-key")
                    with page.expect_response(lambda r: r.url == base + "/api/route") as estimate:
                        calculate.click()
                    assert estimate.value.json()["road_coordinates"] == coordinates
                    expect(page.locator("#pdbRouteStatus")).to_contain_text("12 км")
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
            monkeypatch.setattr(core, "ORS_API_KEY", "")
            with page.expect_response(lambda r: r.url == base + "/api/route") as unavailable:
                sober.get_by_role("button", name="Рассчитать стоимость").click()
            assert unavailable.value.json()["available"] is False
            monkeypatch.setattr(core, "ORS_API_KEY", "synthetic-ors-key")
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
            for service, (oid, time) in requests.items():
                card = passenger.locator("article").filter(has_text=oid)
                expect(card).to_contain_text(service)
                expect(card).to_contain_text(day + " " + time)
            expect(passenger.locator("article").filter(has_text=requests["Трезвый водитель"][0])).to_contain_text(price + " €")
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

            dispatch = browser.new_page()
            configure_page(dispatch, origin=dispatch_base)
            listing = dispatch_base + "/dispatch/telegram-candidates"
            foreign = dispatch.request.get(listing, headers=signed(102), max_redirects=0)
            assert foreign.status == 302 and foreign.headers["location"] == "/dispatch/login"
            assert client.get("/api/admin/driver-applications", headers=signed(102)).status_code == 401
            dispatch.goto(listing)
            assert dispatch.url.endswith("/dispatch/login")
            dispatch.locator("input[name=password]").fill(password)
            dispatch.locator("form").filter(has=dispatch.locator("input[name=password]")).get_by_role("button", name="Войти").click()
            expect(dispatch).to_have_url(dispatch_base + "/dispatch")
            assert dispatch.evaluate("async () => (await fetch('/dispatch/orders/state')).status") == 200
            for service, (oid, time) in requests.items():
                card = dispatch.locator("#ordersList .card").filter(has_text=oid)
                expect(card).to_contain_text(service)
                expect(card).to_contain_text(day + " " + time)
            dispatch.get_by_role("link", name="Анкеты из Telegram").click()
            expect(dispatch.get_by_text("QA Passenger")).to_be_visible()
            expect(dispatch.get_by_text("На проверке")).to_be_visible()
            assert dispatch.evaluate("""async () => (await fetch(location.pathname))
                .headers.get('cache-control')""") == "private, no-store"

            document_path = "/api/driver/documents/101/license_front"
            owner_photo = client.get(document_path, headers=signed(101))
            assert owner_photo.status_code == 200 and owner_photo.mimetype == "image/jpeg"
            assert owner_photo.cache_control.private and owner_photo.cache_control.no_store
            assert client.get(document_path, headers=signed(102)).status_code == 401

            with psycopg.connect(candidates_dsn) as db:
                original = db.execute("""
                    SELECT telegram_id, created_at, updated_at, status
                    FROM public.pd_qa_telegram_candidates
                """).fetchall()
            assert len(original) == 1 and original[0][0] == 101 and original[0][3] == "pending"

            page.locator("#step0").get_by_role("link", name="Стать водителем").click()
            page.locator("#pdObReceived").get_by_role("button", name="Изменить данные").click()
            page.locator("#pdObDriverCity").fill("Kaunas")
            set_candidates_available(False)
            try:
                with page.expect_response(lambda r: r.url == base + "/api/driver/application") as failed:
                    page.locator("#pdObDriverSubmit").click()
                assert failed.value.status == 503
                expect(page.locator("#pdObStatus")).to_contain_text("Повторите отправку")
                assert dispatch.evaluate("async () => (await fetch(location.pathname)).status") == 503
                assert client.get("/api/me", headers=signed(101)).json["driver_application"]["city"] == "Vilnius"
            finally:
                set_candidates_available(True)
            assert dispatch.reload().ok
            expect(dispatch.get_by_text("На проверке")).to_be_visible()

            with page.expect_response(lambda r: r.url == base + "/api/driver/application") as retried:
                page.locator("#pdObDriverSubmit").click()
            assert retried.value.ok
            expect(page.locator("#pdObReceived")).to_contain_text("Kaunas")
            me = client.get("/api/me", headers=signed(101)).json
            assert me["registered"] and not me["pilot_access"] and not me["admin"]
            assert client.get(document_path, headers=signed(101)).data == owner_photo.data

            dispatch.reload()
            expect(dispatch.locator("article")).to_have_count(1)
            expect(dispatch.get_by_text("Kaunas")).to_be_visible()
            expect(dispatch.get_by_text("На проверке")).to_be_visible()
            with psycopg.connect(candidates_dsn) as db:
                rows = db.execute("""
                    SELECT telegram_id, created_at, updated_at, status FROM public.pd_qa_telegram_candidates
                """).fetchall()
            assert len(rows) == 1
            assert rows[0][:2] == original[0][:2] and rows[0][2] > original[0][2] and rows[0][3] == "pending"
            screenshot = os.environ.get("QA_CANDIDATES_SCREENSHOT")
            if screenshot:
                dispatch.screenshot(path=screenshot, full_page=True)
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
