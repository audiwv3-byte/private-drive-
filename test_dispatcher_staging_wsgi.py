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


if __name__ == "__main__":
    unittest.main()
