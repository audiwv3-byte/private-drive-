"""Run: python -m unittest test_web_dispatcher.py
Uses only a temporary Flask application and synthetic credentials.
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

import pd_web_dispatcher


class DispatcherBrowserTests(unittest.TestCase):
    def make_app(self, enabled=True):
        app = Flask(__name__)
        core = SimpleNamespace(ADMIN_IDS=frozenset({999}), is_admin=lambda uid: uid == 999)
        cfg = {"PD_DISPATCH_SESSION_SECRET": "synthetic-secret-32-characters-minimum-12345",
               "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("test-only-password"),
               "PD_DISPATCH_ADMIN_ID": "999"}
        with patch.dict(os.environ, cfg if enabled else {}, clear=True):
            result = pd_web_dispatcher.register(app, core)
        app.config["TESTING"] = True
        return app, result

    def test_disabled_without_secret(self):
        app, active = self.make_app(False)
        self.assertFalse(active)
        self.assertEqual(app.test_client().get("/dispatch").status_code, 503)

    def test_browser_login_csrf_role_and_logout(self):
        app, active = self.make_app()
        self.assertTrue(active)
        c = app.test_client()
        self.assertEqual(c.get("/dispatch").status_code, 302)
        self.assertEqual(c.post("/dispatch/login", data={"password": "test-only-password"}).status_code, 403)
        c.get("/dispatch/login")
        with c.session_transaction() as s:
            token = s["pd_dispatch_csrf"]
        self.assertEqual(c.post("/dispatch/login", data={"password": "wrong", "csrf": token}).status_code, 200)
        self.assertEqual(c.get("/dispatch").status_code, 302)
        self.assertEqual(c.post("/dispatch/login", data={"password": "test-only-password", "csrf": token}).status_code, 302)
        page = c.get("/dispatch")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Рабочая область пока пустая".encode(), page.data)
        with c.session_transaction() as s:
            logout_token = s["pd_dispatch_csrf"]
        self.assertEqual(c.post("/dispatch/logout", data={"csrf": "invalid"}).status_code, 403)
        self.assertEqual(c.post("/dispatch/logout", data={"csrf": logout_token}).status_code, 302)
        self.assertEqual(c.get("/dispatch").status_code, 302)
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        self.assertEqual(app.config["SESSION_COOKIE_SAMESITE"], "Strict")

    def test_no_telegram_admin_impersonation(self):
        app, _ = self.make_app()
        c = app.test_client()
        with c.session_transaction() as s:
            s["pd_dispatch_authenticated"] = True
            s["pd_dispatch_admin_id"] = 123
        self.assertEqual(c.get("/dispatch").status_code, 302)


if __name__ == "__main__":
    unittest.main()
