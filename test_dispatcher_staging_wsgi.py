"""Isolated dispatcher WSGI regression tests, no live services or credentials."""
import os
import re
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from pd_dispatcher_staging_wsgi import create_app


class DispatcherStagingTests(unittest.TestCase):
    def env(self, active=True):
        return {
            "PD_DISPATCH_STAGING_ONLY": "1" if active else "0",
            "PD_DISPATCH_SESSION_SECRET": "staging-only-synthetic-secret-32-plus-chars",
            "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("synthetic-staging-password"),
            "PD_DISPATCH_ADMIN_ID": "999",
        }

    def test_gate_blocks_without_explicit_opt_in(self):
        with patch.dict(os.environ, self.env(False), clear=True):
            app = create_app()
        self.assertEqual(app.test_client().get("/dispatch").status_code, 503)

    def test_no_shared_server_or_api(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        self.assertEqual(app.test_client().get("/api/admin/orders").status_code, 404)
        self.assertEqual(app.test_client().get("/api/me").status_code, 404)
        self.assertEqual(app.config["SESSION_COOKIE_NAME"], "pd_dispatch_staging_session")
        self.assertEqual(app.config["SESSION_COOKIE_PATH"], "/dispatch")
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        self.assertTrue(app.config["SESSION_COOKIE_HTTPONLY"])

    def test_dashboard_is_protected_and_has_mock_map(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        self.assertEqual(client.get("/dispatch").status_code, 302)
        login = client.get("/dispatch/login")
        csrf = re.search(rb'name="csrf" value="([^"]+)"', login.data).group(1).decode()
        response = client.post("/dispatch/login", data={
            "csrf": csrf, "password": "synthetic-staging-password"
        })
        self.assertEqual(response.status_code, 302)
        page = client.get("/dispatch")
        self.assertEqual(page.status_code, 200)
        for item in ("PRIVATE DRIVE", "Карта автопарка", "Панель управления", "Заказы",
                     "Пилоты", "Финансы", "ТЕСТОВЫЕ ДАННЫЕ", "Схема расположения"):
            self.assertIn(item.encode("utf-8"), page.data)
        self.assertIn(b'data-filter="free"', page.data)
        self.assertIn(b'id="zoom-in"', page.data)
        self.assertNotIn(b"https://api.", page.data)
        self.assertEqual(client.get("/api/admin/orders").status_code, 404)

    def test_approved_home_and_services_assets(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        client = app.test_client()
        logo = client.get("/pd-logo-transparent.png")
        self.assertEqual(logo.status_code, 200)
        self.assertTrue(logo.data.startswith(bytes.fromhex("89504e470d0a1a0a")))
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        data = home.data.decode("utf-8")
        for heading in ("Ваш личный водитель", "Наши услуги", "Популярные направления",
                        "Быстрый заказ поездки", "© 2026 jenia ai_fast_work"):
            self.assertIn(heading, data)
        for fare in ("40", "120", "320", "460"):
            self.assertIn(fare + " евро", data)
        self.assertEqual(data.count('class="pd-img-card fare-link"'), 4)
        self.assertEqual(data.count('class="pd-img-card" href=') + data.count('class="pd-img-card pd-driver-card" href='), 3)
        self.assertIn('class="pd-img-card pd-driver-card"', data)
        self.assertIn('src="/assets/pd-user-photo-6-original.webp"', data)
        self.assertNotIn('src="/assets/pd-approved-service_driver.webp"', data)
        self.assertIn('id="quick-trip-form"', data)
        self.assertIn('id="order-live-map"', data)
        self.assertIn('id="route-details"', data)
        self.assertIn('href="/services"', data)
        self.assertNotIn("facebook.com", data)
        self.assertNotIn("commons.wikimedia.org", data)
        self.assertNotIn("private_drive.demo", data)
        self.assertIn("mailto:evrobaltictransfer@gmail.com", data)
        self.assertIn("https://t.me/PrivateDraive", data)
        self.assertIn("https://t.me/ai_fast_work", data)
        for name in ("hero", "airport", "kaunas", "klaipeda", "warsaw",
                     "service_airport", "service_parcel", "service_driver"):
            filename = "pd-approved-" + name + ".webp"
            self.assertIn(filename, data)
            response = client.get("/assets/" + filename)
            self.assertEqual(response.status_code, 200, filename)
            self.assertEqual(response.mimetype, "image/webp")
            self.assertGreater(len(response.data), 8000)
            self.assertEqual(response.data[:4], b"RIFF")
        self.assertEqual(client.get("/assets/non-approved.webp").status_code, 404)
        service = client.get("/services")
        self.assertEqual(service.status_code, 200)
        self.assertIn("Помощь с запуском автомобиля зимой", service.data.decode("utf-8"))
        self.assertIn("Трезвый водитель", service.data.decode("utf-8"))
        for path in ("/pilot-registration", "/dispatch/login"):
            self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.get("/dispatch").status_code, 302)

    def test_logo_size_and_aspect_ratio_mobile_desktop(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        client = app.test_client()
        home = client.get("/").data.decode("utf-8")
        pilot = client.get("/pilot-registration").data.decode("utf-8")
        login = client.get("/dispatch/login").data.decode("utf-8")
        self.assertIn("width:160px", home)
        self.assertIn("hero-stage", home)
        self.assertIn("@media(max-width:420px)", home)
        self.assertIn(".mock-two-hero", home)
        self.assertIn("@media(max-width:600px)", home)
        self.assertIn("https://t.me/PrivateDraive", home)
        self.assertIn("height:auto;aspect-ratio:1/1;object-fit:contain", home)
        self.assertIn("width:min(160px,100%)", home)
        self.assertIn("max-width:100%;aspect-ratio:1;object-fit:contain", pilot)
        self.assertIn("max-width:100%;aspect-ratio:1;object-fit:contain", login)
        self.assertIn("width=\"112\" height=\"112\"", login)

    def test_passenger_trip_transfer_map_and_geo_are_preview_only(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        client = app.test_client()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        for value in ("Поездка", "Трансфер", "pickup-address", "dropoff-address",
                      "use-location", "navigator.geolocation", "order-live-map", "leaflet.js",
                      "order-live-map", "leaflet.js", "pickup-date",
                      "pickup-time", "car-category", "preview-route"):
            self.assertIn(value.encode(), page.data)
        self.assertIn("connect-src 'self'", page.headers["Content-Security-Policy"])
        self.assertIn("form-action 'none'", page.headers["Content-Security-Policy"])
        self.assertNotIn(b'fetch("/api/', page.data)
        self.assertEqual(client.post("/", data={"pickup": "synthetic"}).status_code, 405)

    def test_report_staging_ors_configuration_without_secret(self):
        # Build log reveals only presence, never key content or fragment.
        import os
        configured = bool(os.environ.get("PD_STAGING_ORS_API_KEY", "").strip())
        print("PD_STAGING_ORS_CONFIGURED=" + ("YES" if configured else "NO"), flush=True)
        if configured:
            import pd_public_route_preview as preview
            import urllib.parse
            autocomplete_url = "https://api.heigit.org/pelias/v1/autocomplete?" + urllib.parse.urlencode({
                "text": "Vilnius", "size": 2, "focus.point.lat": 54.6872,
                "focus.point.lon": 25.2797
            })
            try:
                autocomplete = preview._request_json(autocomplete_url)
                okay = bool(isinstance(autocomplete.get("features"), list) and
                            any(x.get("geometry", {}).get("coordinates") for x in autocomplete["features"]))
                print("PD_STAGING_ORS_AUTOCOMPLETE=" + ("OK" if okay else "INVALID_RESPONSE"), flush=True)
            except Exception as exc:
                print("PD_STAGING_ORS_AUTOCOMPLETE=FAILED_" + type(exc).__name__ + ("_HTTP" + str(exc.code) if hasattr(exc, "code") else ""), flush=True)
            try:
                directions = preview._request_json("https://api.heigit.org/openrouteservice/v2/directions/driving-car/geojson", {
                    "coordinates": [[25.2797, 54.6872], [25.3130, 54.6980]]
                })
                feature = directions["features"][0]
                distance = feature["properties"]["summary"]["distance"]
                okay = isinstance(distance, (int, float)) and 0 < distance < 30000
                print("PD_STAGING_ORS_ROUTE=" + ("OK" if okay else "INVALID_RESPONSE"), flush=True)
            except Exception as exc:
                print("PD_STAGING_ORS_ROUTE=FAILED_" + type(exc).__name__ + ("_HTTP" + str(exc.code) if hasattr(exc, "code") else ""), flush=True)
        self.assertIsInstance(configured, bool)

    def test_staging_route_no_key_does_not_create_orders(self):
        from pd_public_route_preview import estimate
        from decimal import Decimal
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
            client = app.test_client()
            result = client.get("/preview/api/suggest?q=Vilnius")
            self.assertEqual(result.status_code, 200)
            self.assertFalse(result.get_json()["available"])
            data = {"origin": "Vilnius, Lithuania", "destination": "Kaunas, Lithuania",
                    "origin_coordinates": [25.2797, 54.6872],
                    "destination_coordinates": [23.9036, 54.8985],
                    "category": "comfort", "roundtrip": False}
            response = client.post("/preview/api/route", json=data)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.get_json()["available"])
            self.assertEqual(client.post("/api/order", json=data).status_code, 404)
            self.assertEqual(estimate(100, 90, data)[0], Decimal("110.00"))
            self.assertEqual(client.post("/preview/api/route", json=dict(data, category="invalid")).status_code, 400)

    def test_mocked_ors_route_for_supported_and_unsupported_classes(self):
        import pd_public_route_preview
        with patch.dict(os.environ, {**self.env(), "PD_STAGING_ORS_API_KEY": "synthetic"}, clear=True):
            app = create_app()
            client = app.test_client()
            fixture = {"features": [{"properties": {"summary": {"distance": 100000, "duration": 5400}},
                                     "geometry": {"coordinates": [[25.2797, 54.6872], [23.9036, 54.8985]]}}]}
            with patch.object(pd_public_route_preview, "_request_json", return_value=fixture):
                data = {"origin": "Vilnius", "destination": "Kaunas",
                        "origin_coordinates": [25.2797, 54.6872],
                        "destination_coordinates": [23.9036, 54.8985],
                        "category": "comfort", "roundtrip": False}
                response = client.post("/preview/api/route", json=data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["price"], "110.00")
                self.assertEqual(response.get_json()["km"], 100)
                data["category"] = "minivan"
                result = client.post("/preview/api/route", json=data).get_json()
                self.assertTrue(result["available"])
                self.assertIsNone(result["price"])

    def test_pilot_registration_public_preview_has_no_upload_backend(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        page = client.get("/pilot-registration")
        self.assertEqual(page.status_code, 200)
        for expected in ("Регистрация пилота", "ФИО", "Телефон", "Категория прав",
                         "Госномер", "Паспорт", "IBAN", "ТЕСТОВЫЙ МАКЕТ"):
            self.assertIn(expected.encode("utf-8"), page.data)
        self.assertIn(b"form-action 'none'", page.headers["Content-Security-Policy"].encode())
        self.assertEqual(client.post("/pilot-registration", data={"full_name": "synthetic"}).status_code, 503)
        self.assertNotIn("submit", app.view_functions)

    def test_login_and_logout(self):
        with patch.dict(os.environ, self.env(), clear=True):
            app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        self.assertEqual(client.get("/dispatch").status_code, 302)
        page = client.get("/dispatch/login")
        csrf = re.search(rb'name="csrf" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(client.post("/dispatch/login", data={"csrf":csrf,"password":"synthetic-staging-password"}).status_code, 302)
        self.assertEqual(client.get("/dispatch").status_code, 200)
        page = client.get("/dispatch")
        csrf = re.search(rb'name="csrf" value="([^"]+)"', page.data).group(1).decode()
        self.assertEqual(client.post("/dispatch/logout", data={"csrf":csrf}).status_code, 302)
        self.assertEqual(client.get("/dispatch").status_code, 302)


# External HTTPS smoke test runs in Render's build environment, never on production.
# Disabled by default. No plaintext test password is stored in the repository.
@unittest.skipUnless(os.environ.get("PD_DISPATCH_HTTPS_SMOKE") == "1", "external smoke test disabled")
class DispatcherHTTPSIntegrationTests(unittest.TestCase):
    def test_real_https_login_logout(self):
        from http.cookiejar import CookieJar
        from urllib.parse import urlencode
        from urllib.request import build_opener, HTTPCookieProcessor, Request
        import ssl

        base = "https://private-drive-dispatcher-staging.onrender.com"
        password = os.environ.get("PD_DISPATCH_SMOKE_PASSWORD", "")
        self.assertTrue(len(password) >= 24, "Missing isolated synthetic test password")
        opener = build_opener(HTTPCookieProcessor(CookieJar()))

        def get(path):
            with opener.open(base + path, timeout=40) as r:
                return r.status, r.url, r.read().decode("utf-8")

        def post(path, csrf, pw=None):
            form = {"csrf": csrf}
            if pw is not None:
                form["password"] = pw
            req = Request(base + path, data=urlencode(form).encode(),
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          method="POST")
            with opener.open(req, timeout=40) as r:
                return r.status, r.url, r.read().decode("utf-8")

        status, address, login = get("/dispatch/login")
        self.assertEqual(status, 200)
        self.assertIn("Вход диспетчера", login)
        csrf_match = re.search(r'name="csrf" value="([^"]+)"', login)
        self.assertIsNotNone(csrf_match, "Missing CSRF token on live login")
        csrf = csrf_match.group(1)
        status, address, dashboard = post("/dispatch/login", csrf, password)
        self.assertEqual(status, 200)
        self.assertTrue(address.endswith("/dispatch"))
        self.assertIn("Карта автопарка", dashboard)
        logout_match = re.search(r'name="csrf" value="([^"]+)"', dashboard)
        self.assertIsNotNone(logout_match)
        status, address, after_logout = post("/dispatch/logout", logout_match.group(1))
        self.assertEqual(status, 200)
        self.assertTrue(address.endswith("/dispatch/login"))
        self.assertIn("Вход диспетчера", after_logout)
        status, address, no_access = get("/dispatch")
        self.assertEqual(status, 200)
        self.assertTrue(address.endswith("/dispatch/login"))
        self.assertNotIn("Карта автопарка", no_access)
        print("LIVE_HTTPS_SMOKE_OK: login page 200, login 200, dashboard 200, logout 200, unauthorized redirected")


@unittest.skipUnless(os.environ.get("PD_PILOT_HTTPS_SMOKE") == "1", "public pilot HTTPS smoke disabled")
class PilotRegistrationHTTPSIntegrationTests(unittest.TestCase):
    def test_public_pilot_registration_https(self):
        from urllib.request import urlopen
        url = "https://private-drive-dispatcher-staging.onrender.com/pilot-registration"
        with urlopen(url, timeout=40) as response:
            page = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Регистрация пилота", page)
            self.assertIn("ТЕСТОВЫЙ МАКЕТ", page)
            self.assertIn('type="file"', page)
        print("PILOT_REGISTRATION_HTTPS_OK: status 200, correct page loaded")



if __name__ == "__main__":
    unittest.main()
