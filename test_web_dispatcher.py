"""Run: python -m unittest test_web_dispatcher.py
Uses only a temporary Flask application and synthetic credentials.
"""
import os
import time
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

    def test_shared_app_secret_is_preserved(self):
        app = Flask(__name__)
        app.secret_key = "original-telegram-session-secret"
        core = SimpleNamespace(ADMIN_IDS=frozenset({999}), is_admin=lambda uid: uid == 999)
        cfg = {"PD_DISPATCH_SESSION_SECRET": "synthetic-secret-32-characters-minimum-12345",
               "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("test-only-password"),
               "PD_DISPATCH_ADMIN_ID": "999"}
        with patch.dict(os.environ, cfg, clear=True):
            active = pd_web_dispatcher.register(app, core)
        self.assertFalse(active)
        self.assertEqual(app.secret_key, "original-telegram-session-secret")
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
        self.assertIn("Карта автопарка".encode(), page.data)
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


    def test_invitation_creates_password_once_and_survives_app_restart(self):
        invite = "synthetic-dispatcher-registration-invite123"
        cfg = {
            "PD_DISPATCH_SESSION_SECRET": "synthetic-secret-32-characters-minimum-12345",
            "PD_DISPATCH_ADMIN_ID": "999",
            "PD_DISPATCH_DATABASE_URL": "synthetic-db-dsn",
            "PD_DISPATCH_INVITE_CODE": invite,
            "PD_DISPATCH_INVITE_EXPIRES": str(int(time.time()) + 60),
        }
        credentials = {}

        def create(admin_id, password_hash):
            if admin_id in credentials:
                return False
            credentials[admin_id] = password_hash
            return True

        store = SimpleNamespace(read=lambda uid: credentials.get(uid, ""), create=create)
        core = SimpleNamespace(ADMIN_IDS=frozenset({999}), is_admin=lambda uid: uid == 999)
        with patch.dict(os.environ, cfg, clear=True), patch.object(
                pd_web_dispatcher, "DispatcherPasswords", return_value=store):
            app = Flask("dispatch_registration")
            self.assertTrue(pd_web_dispatcher.register(app, core))
            registration = app.test_client()
            form_path = "/dispatch/register"
            self.assertEqual(registration.get(form_path).status_code, 200)
            self.assertEqual(registration.post(form_path, data={"invite": invite}).status_code, 403)
            with registration.session_transaction() as session:
                csrf = session["pd_dispatch_csrf"]
            form = {"csrf": csrf, "invite": invite, "password": "new-test-password",
                    "confirmation": "new-test-password"}
            self.assertEqual(registration.post(form_path, data={**form, "invite": "wrong"}).status_code, 403)
            self.assertEqual(registration.post(form_path, data={**form, "confirmation": "wrong"}).status_code, 400)
            self.assertEqual(registration.post(form_path, data=form).status_code, 303)
            self.assertNotEqual(credentials[999], form["password"])
            self.assertEqual(registration.get("/dispatch").location, "/dispatch/login")

            restarted = Flask("dispatch_registration_restart")
            self.assertTrue(pd_web_dispatcher.register(restarted, core))
            client = restarted.test_client()
            self.assertNotIn(b'name="invite"', client.get(form_path).data)
            client.get("/dispatch/login")
            with client.session_transaction() as session:
                new_csrf = session["pd_dispatch_csrf"]
            retry = {"csrf": new_csrf, "invite": invite, "password": "another-test-password",
                     "confirmation": "another-test-password"}
            self.assertNotIn(b'name="invite"', client.post(form_path, data=retry).data)
            self.assertEqual(client.post("/dispatch/login", data={
                "csrf": new_csrf, "password": form["password"],
            }).location, "/dispatch")
            self.assertEqual(client.get("/dispatch").status_code, 200)

    def test_registration_without_configuration_is_closed(self):
        app, _ = self.make_app(False)
        client = app.test_client()
        page = client.get("/dispatch/register")
        self.assertEqual(page.status_code, 503)
        self.assertNotIn(b'name="invite"', page.data)
        self.assertEqual(client.post("/dispatch/register").status_code, 503)


if __name__ == "__main__":
    unittest.main()
