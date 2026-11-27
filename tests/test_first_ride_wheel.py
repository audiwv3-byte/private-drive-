"""Cross-channel first-ride reward with real isolated PostgreSQL API writes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import psycopg
import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

import pd_first_ride_wheel as wheel
from pd_first_ride_wheel_flask import install_qa_phone_auth
from pd_native_auth_postgres_http import initialize_database
from pd_qa_native_orders_mount import REQUIRED, mount_if_synthetic
from pd_unified_accounts_schema import install_schema
from test_qa_unified_release import DSN, telegram_header


def test_percent_distribution():
    assert [wheel.draw_percent(i) for i in range(100)] == (
        [5] * 45 + [10] * 35 + [15] * 15 + [20] * 5)
    assert wheel.discounted_cents(101, 5) == 96
    assert wheel.discounted_cents(None, 5) is None


@pytest.fixture(scope="module")
def mini_db(tmp_path_factory):
    return tmp_path_factory.mktemp("first-ride-miniapp")


@pytest.fixture
def channels(monkeypatch, mini_db):
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == DSN
    token = "123456:synthetic-wheel"
    for key, value in {**REQUIRED, "DATABASE_URL": DSN, "BOT_TOKEN": token,
                       "PD_DISPATCH_ORDERS_DATABASE_URL": DSN,
                       "PD_QA_FIRST_RIDE_WHEEL": "1", "ORS_API_KEY": ""}.items():
        monkeypatch.setenv(key, value)
    initialize_database(DSN)
    with psycopg.connect(DSN, autocommit=True) as db:
        for name in ("native_auth_session_functions", "native_dispatch_orders",
                     "native_pilot_identity", "qa26_pilot_assignment"):
            db.execute(Path(f"migrations/{name}.sql").read_text())
        install_schema(db)
        db.execute(Path("migrations/qa_first_ride_wheel.sql").read_text())

    from telebot import apihelper

    def forbid_telegram_network(*args, **kwargs):
        raise AssertionError("QA must never call the Telegram Bot API")

    monkeypatch.setattr(apihelper, "_make_request", forbid_telegram_network)
    import Euro_Baltic_Transfer as core
    import pd_referrals

    monkeypatch.setattr(pd_referrals, "bot_username", lambda: "SyntheticWheelTestBot")
    monkeypatch.setattr(core, "TOKEN", token)
    monkeypatch.setattr(core, "ORDERS_DB", mini_db / "orders.db")
    monkeypatch.setattr(core, "USERS_DB", mini_db / "users.db")
    monkeypatch.setattr(core, "route", lambda *args: (27, 30))
    import miniapp_server
    from pd_dispatcher_staging_wsgi import create_app
    monkeypatch.setattr(wheel, "randbelow", lambda _: 82)
    codes = {f"+120255501{n:02}": "123456" for n in range(20, 28)}
    site = create_app()
    for app in (site, miniapp_server.app):
        install_qa_phone_auth(app, DSN, codes)
    native = mount_if_synthetic(lambda e, s: Response(status=404)(e, s), DSN)
    return site, miniapp_server.app, native, token


def confirm(client, prefix, phone, *, headers=None):
    reply = client.post(prefix + "/phone/request-code",
                        headers=headers, json={"channel": "phone", "destination": phone})
    assert reply.status_code == 202, reply.json
    verified = client.post(prefix + "/phone/verify-code", headers=headers,
                           json={"challenge_id": reply.json["challenge_id"], "code": "123456"})
    assert verified.status_code == 200, verified.json
    return verified.json


def second_session(user_id):
    bearer = uuid.uuid4().hex * 2
    with psycopg.connect(DSN) as db:
        db.execute("""INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at)
            VALUES (%s,%s,%s,%s)""", (hashlib.sha256(bearer.encode()).hexdigest(),
                                     user_id, int(time.time()), int(time.time()) + 600))
    return {"Authorization": "Bearer " + bearer}


def test_one_reward_and_redemption_across_channels(channels):
    site_app, mini_app, native_app, token = channels
    site, mini, native = site_app.test_client(), mini_app.test_client(), Client(native_app, Response)
    web_wheel = "/preview/api/first-ride-wheel"
    tg_wheel = "/api/first-ride-wheel"
    assert site.get(web_wheel).json == {"state": "sign_in_required"}
    assert native.post("/native-first-ride-wheel").status_code == 401
    tg = telegram_header(750001, token)
    assert mini.get(tg_wheel, headers=tg).json == {"state": "link_required"}
    assert mini.post("/api/register", headers=tg,
                     json={"name": "Synthetic rider", "phone": "+12025550120"}).status_code == 200
    assert mini.get(tg_wheel, headers=tg).json == {"state": "link_required"}

    web_account = confirm(site, web_wheel, "+12025550120")
    web_headers = {"Authorization": "Bearer " + web_account["access_token"]}
    native_headers = second_session(web_account["user_id"])
    result = mini.post(tg_wheel + "/phone/request-code", headers=tg,
                       json={"channel": "phone", "destination": "+12025550121"})
    assert result.status_code == 202
    wrong = mini.post(tg_wheel + "/phone/verify-code", headers=tg,
                      json={"challenge_id": result.json["challenge_id"], "code": "000000"})
    assert wrong.status_code == 401
    assert mini.get(tg_wheel, headers=tg).json == {"state": "link_required"}
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE native_twilio_challenges SET created_at=created_at-61 WHERE phone=%s",
                   ("+12025550120",))
    assert confirm(mini, tg_wheel, "+12025550120", headers=tg) == {"linked": True}

    def web_spin():
        return site_app.test_client().post(web_wheel, headers=web_headers).json

    def mobile_spin():
        return Client(native_app, Response).post("/native-first-ride-wheel", headers=native_headers).json

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(web_spin)
        second = pool.submit(mobile_spin)
        reward = first.result()
        assert second.result() == reward
    assert reward["state"] == "available" and reward["percent"] == 15
    assert abs(reward["expires_at"] - int(time.time()) - wheel.TTL) <= 3
    assert mini.post(tg_wheel, headers=tg, json={}).json == reward

    future = date.today() + timedelta(days=2)
    website = {"reference": uuid.uuid4().hex, "from": "Вильнюс", "to": "Каунас",
               "phone": "+12025550999", "trip_date": future.isoformat(), "trip_time": "14:00"}
    mobile = {"request_id": str(uuid.uuid4()), "from": "Вильнюс", "to": "Каунас",
              "trip_date": future.isoformat(), "trip_time": "14:00", "details": {}}

    def website_order():
        return site_app.test_client().post("/preview/api/qa-booking", headers=web_headers, json=website)

    def mobile_order():
        return Client(native_app, Response).post("/native-orders", headers=native_headers, json=mobile)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(website_order)
        second = pool.submit(mobile_order)
        web_order, app_order = first.result(), second.result()
    assert web_order.status_code == app_order.status_code == 201, (web_order.json, app_order.json)
    results = [web_order.json["trip"], app_order.json]
    discounted, = [order for order in results if order.get("discount_percent")]
    assert discounted["quoted_total_cents"] == 9350
    assert website_order().json["trip"] == web_order.json["trip"]
    assert mobile_order().json == app_order.json
    assert mini.get(tg_wheel, headers=tg).json["state"] == "used"
    assert site.get(web_wheel, headers=web_headers).json["state"] == "used"

    tg_order = mini.post("/api/order", headers=tg, json={
        "origin": "Vilnius", "destination": "Kaunas", "trip_date": future.strftime("%d.%m.%Y"),
        "trip_time": "14:05", "request_key": uuid.uuid4().hex})
    assert tg_order.status_code == 200, tg_order.json
    assert "discount_percent" not in tg_order.json
    listing = native.get("/native-orders", headers=native_headers).json["orders"]
    assert len(listing) == 3
    assert {row["order_id"] for row in listing} == {
        web_order.json["trip"]["id"], app_order.json["order_id"], tg_order.json["dispatch_order_id"]}
    with psycopg.connect(DSN) as db:
        row = db.execute("SELECT website_contact FROM pd_dispatch_orders WHERE id=%s",
                         (web_order.json["trip"]["id"],)).fetchone()
        assert row == ("+12025550120",)


def test_telegram_first_order_and_expiry(channels):
    site_app, mini_app, native_app, token = channels
    site, mini = site_app.test_client(), mini_app.test_client()
    web_wheel = "/preview/api/first-ride-wheel"
    tg_wheel = "/api/first-ride-wheel"
    tg = telegram_header(750002, token)
    number = "+12025550122"
    assert confirm(mini, tg_wheel, number, headers=tg) == {"linked": True}
    assert mini.post("/api/register", headers=tg, json={"name": "Test Rider", "phone": number}).status_code == 200
    reward = mini.post(tg_wheel, headers=tg, json={}).json
    future = date.today() + timedelta(days=2)
    booking = {"origin": "Vilnius", "destination": "Kaunas", "trip_date": future.strftime("%d.%m.%Y"),
               "trip_time": "14:05", "request_key": uuid.uuid4().hex}
    first = mini.post("/api/order", headers=tg, json=booking)
    retry = mini.post("/api/order", headers=tg, json=booking)
    assert first.status_code == retry.status_code == 200, (first.json, retry.json)
    assert first.json["discount_percent"] == retry.json["discount_percent"] == reward["percent"]
    assert first.json["price"] == retry.json["price"]
    assert retry.json["replayed"]

    account = confirm(site, web_wheel, "+12025550123")
    headers = {"Authorization": "Bearer " + account["access_token"]}
    percent = site.post(web_wheel, headers=headers).json["percent"]
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE pd_first_ride_rewards SET expires_at=0 WHERE user_id=%s", (account["user_id"],))
    assert site.post(web_wheel, headers=headers).json == {"state": "expired", "percent": percent, "expires_at": 0}
    booking = {"reference": uuid.uuid4().hex, "from": "Вильнюс", "to": "Каунас",
               "phone": "+12025550123", "trip_date": future.isoformat(), "trip_time": "15:00"}
    expired = site.post("/preview/api/qa-booking", headers=headers, json=booking)
    assert expired.status_code == 201 and "discount_percent" not in expired.json["trip"]

    with psycopg.connect(DSN) as db:
        db.execute("UPDATE native_twilio_challenges SET created_at=created_at-61 WHERE phone=%s",
                   ("+12025550123",))
    wrong = mini.post(tg_wheel + "/phone/request-code", headers=tg,
                      json={"channel": "phone", "destination": "+12025550123"})
    assert wrong.status_code == 202
    conflict = mini.post(tg_wheel + "/phone/verify-code", headers=tg,
                         json={"challenge_id": wrong.json["challenge_id"], "code": "123456"})
    assert conflict.status_code == 409
    assert mini.get(tg_wheel, headers=tg).json["state"] == "used"


def test_browser_website_spin_and_miniapp_reward(channels):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright

    site_app, mini_app, _, token = channels
    clients = {"site.test": site_app.test_client(), "mini.test": mini_app.test_client()}
    telegram = telegram_header(750003, token)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.getenv("PD_TEST_CHROME"))
        page = browser.new_page(reduced_motion="reduce")
        page.set_default_timeout(8000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname not in clients:
                route.abort()
                return
            response = clients[url.hostname].open(
                url.path + ("?" + url.query if url.query else ""),
                base_url="https://" + url.hostname, method=req.method,
                headers={key: value for key, value in req.headers.items()
                         if key in ("authorization", "content-type", "x-telegram-init-data")},
                data=req.post_data_buffer)
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)

        page.route("**/*", route_request)
        assert page.goto("https://site.test/").ok
        panel = page.locator("#pdFirstRideWheel")
        panel.locator('input[name="phone"]').fill("+12025550124")
        panel.get_by_role("button", name="Получить код").click()
        panel.locator('input[name="code"]').fill("123456")
        panel.get_by_role("button", name="Подтвердить номер").click()
        panel.get_by_role("button", name="Крутить колесо").click()
        panel.get_by_text("Твоя скидка — 15%", exact=False).wait_for()
        panel.get_by_role("button", name="Заказать со скидкой").click()
        page.locator("#quick-from").fill("Вильнюс")
        page.locator("#quick-to").fill("Каунас")
        page.locator("#quick-date").fill((date.today() + timedelta(days=2)).isoformat())
        page.locator("#quick-time").fill("14:00")
        page.locator('#quick-trip-form button[type="submit"]').click()
        page.get_by_text("Итого: 93.50 €.", exact=False).wait_for()
        mini = clients["mini.test"]
        with psycopg.connect(DSN) as db:
            db.execute("UPDATE native_twilio_challenges SET created_at=created_at-61 WHERE phone=%s",
                       ("+12025550124",))
        assert confirm(mini, "/api/first-ride-wheel", "+12025550124", headers=telegram) == {"linked": True}
        registration = mini.post("/api/register", headers=telegram,
                                json={"name": "Synthetic rider", "phone": "+12025550124"})
        assert registration.status_code == 200
        page.add_init_script("window.Telegram={WebApp:{ready(){},expand(){},initData:" +
                             json.dumps(telegram["X-Telegram-Init-Data"]) + "}};")
        assert page.goto("https://mini.test/?lang=ru").ok
        page.locator('#mainNav button[onclick="go(12)"]').click()
        page.locator("#pdFirstRideWheel").get_by_text("Скидка 15% уже применена.").wait_for()
        assert not page.locator("#pdFirstRideWheel [data-wheel-spin]").is_visible()
        browser.close()
    assert not errors, errors
