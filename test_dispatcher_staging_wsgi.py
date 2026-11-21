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


if __name__ == "__main__":
    unittest.main()
