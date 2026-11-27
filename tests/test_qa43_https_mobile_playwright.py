"""Exercise the isolated mobile API and dispatcher in real browsers over trusted TLS."""

import os
import secrets
import socket
import ssl
import time
import uuid
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from werkzeug.wrappers import Response

from ops.qa.qa42_local_kit import prepare
from ops.qa.qa42_mobile_login import new_codes


@pytest.fixture(scope="module")
def lab():
    fixtures = Path(os.environ["QA43_FIXTURES"])
    codes = new_codes()
    password = secrets.token_urlsafe(24)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(fixtures / "server.crt", fixtures / "server.key")

    with patch.dict(os.environ, {"PD_QA42_LOCAL": "YES"}):
        app, _, _, _ = prepare(mobile_codes=codes, dispatcher_password=password)
        def browser_lab(environ, start_response):
            if environ["PATH_INFO"] == "/qa43-browser":
                page = Response("<!doctype html><title>QA43 mobile API</title>", mimetype="text/html")
                page.headers["Content-Security-Policy"] = "default-src 'none'; connect-src 'self'"
                return page(environ, start_response)
            return app(environ, start_response)

        server = make_server("127.0.0.1", 0, browser_lab, threaded=True, ssl_context=tls)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"https://127.0.0.1:{server.server_port}", fixtures, codes, password
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


def test_tls_certificate_and_protocol(lab):
    origin, fixtures, _, _ = lab
    address = ("127.0.0.1", urlsplit(origin).port)

    def connect(context, name="127.0.0.1"):
        with socket.create_connection(address, timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=name) as connection:
                return connection.version()

    trusted = ssl.create_default_context(cafile=str(fixtures / "root.crt"))
    assert connect(trusted) == "TLSv1.3"
    trusted.minimum_version = ssl.TLSVersion.TLSv1_2
    trusted.maximum_version = ssl.TLSVersion.TLSv1_2
    assert connect(trusted) == "TLSv1.2"
    with pytest.raises(ssl.SSLCertVerificationError):
        connect(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    with pytest.raises(ssl.SSLCertVerificationError):
        connect(trusted, "localhost")

    with pytest.raises(ssl.SSLError):
        with pytest.warns(DeprecationWarning):
            trusted.minimum_version = ssl.TLSVersion.TLSv1_1
            trusted.maximum_version = ssl.TLSVersion.TLSv1_1
        trusted.set_ciphers("DEFAULT:@SECLEVEL=0")
        connect(trusted)
    print("PASS TLS 1.2 and 1.3, untrusted CA and wrong SAN rejection, TLS 1.1 refused")


def offline_context(browser, origin, fixtures, **options):
    context = browser.new_context(service_workers="block", **options)
    local = urlsplit(origin)

    def route_request(route):
        url = urlsplit(route.request.url)
        if (url.scheme, url.netloc) == (local.scheme, local.netloc):
            return route.continue_()
        if (url.scheme, url.netloc) == ("https", "unpkg.com"):
            for asset, mime in (("leaflet.js", "text/javascript"), ("leaflet.css", "text/css")):
                if url.path == f"/leaflet@1.9.4/dist/{asset}":
                    return route.fulfill(
                        path=fixtures / asset, content_type=mime,
                        headers={"Access-Control-Allow-Origin": "*"},
                    )
        return route.abort()

    context.route("**/*", route_request)
    return context


def api(page, path, status, *, data=None, token=None, method="POST", cookies="omit"):
    result = page.evaluate(
        """async ({path, data, token, method, cookies}) => {
            const headers = {};
            if (data !== null) headers['Content-Type'] = 'application/json';
            if (token !== null) headers.Authorization = 'Bearer ' + token;
            const response = await fetch(path, {
                method, headers, credentials: cookies, redirect: 'error',
                body: data === null ? null : JSON.stringify(data)
            });
            return {status: response.status, body: await response.json()};
        }""",
        dict(path=path, data=data, token=token, method=method, cookies=cookies),
    )
    assert result["status"] == status, f"{method} {path}: expected {status}, got {result['status']}"
    return result["body"]


def sign_in(page, origin, phone, code, role):
    assert page.goto(origin + "/qa43-browser").ok
    assert page.evaluate("window.isSecureContext")
    api(page, "/native-auth/session", 401)
    challenge = api(
        page, "/native-auth/request-code", 202,
        data={"channel": "phone", "destination": phone},
    )
    verify = {"challenge_id": challenge["challenge_id"], "code": code}
    other_code = "000000" if code != "000000" else "111111"
    api(page, "/native-auth/verify-code", 401, data={**verify, "code": other_code})
    session = api(page, "/native-auth/verify-code", 200, data=verify)
    assert session["verified"] and session["role"] == role
    assert session["token_type"] == "Bearer" and session["expires_in"] > 0
    api(page, "/native-auth/verify-code", 401, data=verify)
    token = session["access_token"]
    restored = api(page, "/native-auth/session", 200, token=token)
    assert restored["user_id"] == session["user_id"]
    assert restored["role"] == role
    return token


def wait_for_marker(page, latitude, longitude):
    page.wait_for_function(
        """([latitude, longitude]) => {
            const marker = document.querySelector('.leaflet-marker-pane .pilot-marker');
            return marker && L.DomUtil.getPosition(marker)?.equals(
                raster.latLngToLayerPoint([latitude, longitude])
            );
        }""",
        arg=[latitude, longitude], timeout=15_000,
    )


def test_android_chromium_ios_webkit_and_dispatcher_gps(lab):
    origin, fixtures, codes, password = lab
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        webkit = playwright.webkit.launch()
        android = offline_context(chromium, origin, fixtures, **playwright.devices["Pixel 7"])
        ios = offline_context(webkit, origin, fixtures, **playwright.devices["iPhone 13"])
        dispatcher = offline_context(chromium, origin, fixtures, viewport={"width": 1440, "height": 900})
        passenger_page, pilot_page, desk = android.new_page(), ios.new_page(), dispatcher.new_page()
        errors = []
        desk.on("pageerror", lambda error: errors.append(str(error)))

        passenger_phone, pilot_phone = "+12025550101", "+12025550102"
        passenger = sign_in(passenger_page, origin, passenger_phone, codes[passenger_phone], "passenger")
        print("PASS Android Chromium profile: OTP rejection, one-time login, restored passenger session")
        pilot = sign_in(pilot_page, origin, pilot_phone, codes[pilot_phone], "pilot")
        print("PASS iOS WebKit profile: OTP rejection, one-time login, restored pilot session")

        order = api(passenger_page, "/native-orders", 201, token=passenger, data={
            "request_id": str(uuid.uuid4()), "from": "QA43 Vilnius A",
            "to": "QA43 Vilnius B", "trip_date": "2030-01-01", "trip_time": "12:00",
        })
        order_id = order["order_id"]
        gps_write = f"/native-pilot-orders/{order_id}/gps"
        gps_read = f"/dispatch/orders/{order_id}/gps"
        api(pilot_page, gps_read, 401, method="GET")
        assert desk.goto(origin + "/dispatch/login").ok
        desk.locator("input[name=password]").fill(password)
        desk.locator("form button").first.click()
        desk.wait_for_url(origin + "/dispatch")
        cookies = [cookie for cookie in dispatcher.cookies() if cookie["name"] == "pd_qa42_session"]
        assert len(cookies) == 1
        assert cookies[0]["secure"] and cookies[0]["httpOnly"] and cookies[0]["sameSite"] == "Strict"

        card = desk.locator("#ordersList .card").filter(has_text="QA43 Vilnius A")
        card.locator("select").select_option("qa39-pilot")
        card.get_by_role("button", name="Назначить пилота").click()
        card.get_by_role("button", name="Пилот на карте").click()
        marker = desk.locator(".leaflet-marker-pane .pilot-marker")
        expect(marker).to_have_count(0)

        first = {"latitude": 54.6872, "longitude": 25.2797}
        moved = {"latitude": 54.7000, "longitude": 25.3000}
        stamp = int(time.time())
        fix = {"enabled": True, "captured_at": stamp, **first}
        api(passenger_page, gps_write, 403, token=passenger, data=fix)
        api(pilot_page, gps_write, 401, data=fix)
        assert api(pilot_page, gps_write, 200, token=pilot, data=fix)["available"]
        wait_for_marker(desk, **first)
        api(pilot_page, gps_write, 409, token=pilot, data=fix)
        assert api(
            pilot_page, gps_write, 200, token=pilot,
            data={"enabled": True, "captured_at": stamp + 1, **moved},
        )["available"]
        wait_for_marker(desk, **moved)
        assert api(
            pilot_page, gps_write, 200, token=pilot,
            data={"enabled": False, "captured_at": int(time.time()) + 2},
        ) == {"available": False}
        expect(marker).to_have_count(0, timeout=15_000)
        assert api(desk, gps_read, 200, method="GET", cookies="same-origin") == {"available": False}
        print("PASS dispatcher GPS: role checks, stale fix rejected, marker appears, moves and disappears")

        for page, token in ((passenger_page, passenger), (pilot_page, pilot)):
            api(page, "/native-auth/sign-out", 200, token=token)
            api(page, "/native-auth/session", 401, token=token)
        api(pilot_page, gps_write, 401, token=pilot, data=fix)
        assert not errors, errors
        print("PASS both sessions revoked and signed-out pilot cannot publish GPS")
        chromium.close()
        webkit.close()
