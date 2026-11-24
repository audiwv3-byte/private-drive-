"""Run: python -m unittest test_web_dispatcher.py
Uses only a temporary Flask application and synthetic credentials.
"""
import os
import hashlib
import re
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

import pd_web_dispatcher


class DispatcherBrowserTests(unittest.TestCase):
    def make_app(self, enabled=True, test_sync=False):
        app = Flask(__name__)
        core = SimpleNamespace(ADMIN_IDS=frozenset({999}), is_admin=lambda uid: uid == 999)
        cfg = {"PD_DISPATCH_SESSION_SECRET": "synthetic-secret-32-characters-minimum-12345",
               "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("test-only-password"),
               "PD_DISPATCH_ADMIN_ID": "999"}
        if test_sync:
            cfg.update(PD_DISPATCH_STAGING_ONLY="1", PD_DISPATCH_TEST_SYNC="1")
        with patch.dict(os.environ, cfg if enabled else {}, clear=True):
            result = pd_web_dispatcher.register(app, core)
        app.config["TESTING"] = True
        return app, result

    def test_postgres_restart_probe_blocks_wrong_environment_and_db(self):
        from pd_dispatch_db_restart_probe import assert_staging_configuration, check_id
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                assert_staging_configuration()
        with patch.dict(os.environ, {
                "PD_DISPATCH_STAGING_ONLY": "1",
                "PD_DISPATCH_ORDERS_DATABASE_URL":
                    "postgresql://example:unused@localhost/private_drive_prod"}, clear=True):
            with self.assertRaises(RuntimeError):
                assert_staging_configuration()
        with patch.dict(os.environ, {
                "PD_DISPATCH_STAGING_ONLY": "1",
                "PD_DISPATCH_ORDERS_DATABASE_URL":
                    "postgresql://example:unused@localhost/private_drive_test"}, clear=True):
            self.assertTrue(assert_staging_configuration().endswith("/private_drive_test"))
        self.assertEqual(check_id("b"*8+"-"+"b"*4+"-"+"b"*4+"-"+"b"*4+"-"+"b"*12),
                         "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        with self.assertRaises(ValueError):
            check_id("production-order")

    def test_persistent_order_validation_and_signature(self):
        import json
        import hmac
        from pd_dispatch_persistent import validated_order, verified_request, fingerprint
        order = {"source": "telegram_miniapp", "source_order_id": "123",
                 "from": "Vilnius", "to": "Vilnius Airport",
                 "trip_date": "2026-11-24", "trip_time": "12:00"}
        expected = ("telegram_miniapp", "123", "Vilnius", "Vilnius Airport",
                    "2026-11-24", "12:00")
        self.assertEqual(validated_order(order), expected)
        self.assertEqual(fingerprint(expected), fingerprint(expected))
        key = "staging-only-server-bridge-secret-32characters"
        ts = str(int(time.time()))
        raw = json.dumps(order).encode()
        mac = hmac.new(key.encode(), ts.encode()+b"."+raw, hashlib.sha256).hexdigest()
        header = {"X-PD-Order-Timestamp": ts, "X-PD-Order-Signature": mac}
        self.assertTrue(verified_request(raw, header, key))
        self.assertFalse(verified_request(raw+b" ", header, key))
        self.assertFalse(verified_request(raw, header, key, now=int(ts)+301))
        with self.assertRaises(ValueError):
            validated_order({**order, "source": "fake_client"})
        with self.assertRaises(ValueError):
            validated_order({**order, "to": "Vilnius"})
        with self.assertRaises(ValueError):
            validated_order({**order, "trip_time": "27:99"})

    def test_persistent_orders_closed_by_default(self):
        app, _ = self.make_app(enabled=True, test_sync=False)
        c = app.test_client()
        self.assertEqual(c.post("/v1/dispatch/orders/import",
                                json={"test":True}).status_code, 503)
        self.assertEqual(c.get("/dispatch/orders/state").status_code, 401)

    def test_staging_mobile_pilot_and_order_appear_in_dispatcher(self):
        app, _ = self.make_app(test_sync=True)
        directory, store = app.extensions["pd_dispatch_test_sync"]
        self.addCleanup(directory.cleanup)
        self.addCleanup(store.close)
        dispatcher = app.test_client()
        mobile = app.test_client()
        self.assertEqual(dispatcher.get("/dispatch/test-sync").status_code, 302)
        self.assertEqual(dispatcher.get("/dispatch/test-sync/state").status_code, 401)
        self.assertEqual(mobile.get("/v1/me").status_code, 401)
        dispatcher.get("/dispatch/login")
        with dispatcher.session_transaction() as session:
            csrf = session["pd_dispatch_csrf"]
        self.assertEqual(dispatcher.post("/dispatch/login", data={
            "csrf": csrf, "password": "test-only-password",
        }).status_code, 302)
        setup = dispatcher.get("/dispatch/test-sync")
        pilot_token, passenger_token = re.findall(rb'value="([a-f0-9]{64})"', setup.data)
        self.assertNotEqual(pilot_token, passenger_token)
        pilot = {"Authorization": "Bearer " + pilot_token.decode()}
        passenger = {"Authorization": "Bearer " + passenger_token.decode()}
        with dispatcher.session_transaction() as session:
            csrf = session["pd_dispatch_csrf"]
        self.assertIn(b'id="ordersList"', dispatcher.get("/dispatch").data)
        self.assertFalse(dispatcher.get("/dispatch/test-sync/state").json["pilot_online"])
        self.assertEqual(mobile.get("/v1/me", headers=pilot).json["role"], "pilot")
        self.assertIsNone(mobile.get("/v1/current", headers=pilot).json["trip"])
        route = {"from": "Тестовая точка A", "to": "Тестовая точка B"}
        self.assertEqual(mobile.post("/v1/trips", headers=pilot, json=route).status_code, 403)
        created = mobile.post("/v1/trips", headers=passenger, json=route)
        self.assertEqual(created.status_code, 201)
        snapshot = dispatcher.get("/dispatch/test-sync/state").json
        self.assertTrue(snapshot["pilot_online"])
        self.assertIsNone(snapshot["pilot_position"])
        position = {"latitude": 54.68725, "longitude": 25.27975}
        self.assertEqual(mobile.post("/v1/position", headers=passenger, json=position).status_code, 403)
        self.assertEqual(mobile.post("/v1/position", headers=pilot, json={
            **position, "latitude": 180,
        }).status_code, 400)
        self.assertEqual(mobile.post("/v1/position", headers=pilot, json=position).status_code, 200)
        self.assertEqual(dispatcher.get("/dispatch/test-sync/state").json["pilot_position"], list(position.values()))
        self.assertEqual(mobile.post("/v1/position", headers=pilot, json={
            "latitude": None, "longitude": None,
        }).status_code, 200)
        self.assertIsNone(dispatcher.get("/dispatch/test-sync/state").json["pilot_position"])
        trip = snapshot["trips"][0]
        self.assertEqual(trip["origin"], route["from"])
        self.assertEqual(trip["status"], "requested")
        self.assertEqual(mobile.get(f"/v1/trips/{trip['id']}", headers=pilot).status_code, 404)
        form = {"trip_id": trip["id"], "version": trip["version"]}
        self.assertEqual(dispatcher.post("/dispatch/test-sync/assign", data=form).status_code, 403)
        self.assertEqual(dispatcher.post("/dispatch/test-sync/assign",
            data={**form, "csrf": csrf}).status_code, 200)
        self.assertEqual(mobile.get("/v1/current", headers=pilot).json["trip"]["status"], "assigned")
        self.assertEqual(mobile.get(f"/v1/trips/{trip['id']}/events?after=0",
            headers=passenger).status_code, 200)
        self.assertEqual(mobile.get(f"/v1/trips/{trip['id']}/messages?after=0",
            headers=pilot).json["messages"], [])
        advanced = mobile.post(f"/v1/trips/{trip['id']}/action", headers=pilot,
            json={"action": "advance", "version": 2})
        self.assertEqual(advanced.json["trip"]["status"], "approaching")
        self.assertEqual(dispatcher.get("/dispatch/test-sync/state").json["trips"][0]["status"], "approaching")
        with patch("pd_dispatch_test_sync.time.monotonic", return_value=store.last_pilot_poll + 16):
            self.assertFalse(dispatcher.get("/dispatch/test-sync/state").json["pilot_online"])

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

    def test_owner_mfa_requires_code_and_closes_registration(self):
        app = Flask(__name__)
        core = SimpleNamespace(ADMIN_IDS=frozenset({999}), is_admin=lambda uid: uid == 999)
        credential = generate_password_hash("test-only-password")
        consumed = set()

        def consume(admin_id, counter):
            if counter in consumed:
                return False
            consumed.add(counter)
            return True

        passwords = SimpleNamespace(read=lambda admin_id: credential,
                                    reserve_owner_attempt=lambda *args: True,
                                    consume_totp=consume)
        cfg = {"PD_DISPATCH_SESSION_SECRET": "synthetic-secret-32-characters-minimum-12345",
               "PD_DISPATCH_ADMIN_ID": "999",
               "PD_DISPATCH_DATABASE_URL": "postgresql://unused/test",
               "PD_DISPATCH_REQUIRE_MFA": "1",
               "PD_DISPATCH_TOTP_BASE32": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"}
        with patch.dict(os.environ, cfg, clear=True):
            with patch.object(pd_web_dispatcher, "DispatcherPasswords", return_value=passwords):
                self.assertTrue(pd_web_dispatcher.register(app, core))
        app.config["TESTING"] = True
        browser = app.test_client()
        self.assertEqual(browser.get("/dispatch/register").status_code, 403)
        self.assertEqual(browser.get("/dispatch/recover").status_code, 403)
        self.assertIn(b'name="totp"', browser.get("/dispatch/login").data)

        def login(client, code=""):
            client.get("/dispatch/login")
            with client.session_transaction() as state:
                csrf = state["pd_dispatch_csrf"]
            return client.post("/dispatch/login", data={
                "password": "test-only-password", "csrf": csrf, "totp": code,
            })

        with patch.object(pd_web_dispatcher, "totp_counter",
                          side_effect=lambda key, code, now: 123 if code == "123456" else None):
            self.assertEqual(login(browser).status_code, 401)
            self.assertEqual(browser.get("/dispatch/orders/state").status_code, 401)
            self.assertEqual(login(browser, "123456").status_code, 302)
            self.assertEqual(browser.get("/dispatch").status_code, 200)
            other_browser = app.test_client()
            self.assertEqual(login(other_browser, "123456").status_code, 401)
            self.assertEqual(other_browser.get("/dispatch/map").status_code, 302)

    def test_mapbox_public_token_configuration_diagnostic(self):
        """Report only token presence and validity, never the token itself."""
        import re
        token = os.environ.get("MAPBOX_WEB_PUBLIC_TOKEN", "").strip()
        valid = bool(re.fullmatch(r"pk\\.[A-Za-z0-9_.-]{1,512}", token))
        state = "VALID" if valid else ("INVALID" if token else "ABSENT")
        print("PD_STAGING_MAPBOX_PUBLIC_TOKEN_STATUS=" + state, flush=True)

    def test_mapbox_mobile_theme_contract(self):
        from pathlib import Path
        page = Path(__file__).with_name("pd_dispatcher_mapbox.html").read_text(encoding="utf-8")
        for expected in (
            "dark-v11", "light-v11", "themeBtn",
            "@media(max-width:650px)", "tile.openstreetmap.org",
            "api.mapbox.com", "mapbox_token|tojson",
            'id="modeBtn"', "fill-extrusion", "pitch:mode3d?55:0",
        ):
            self.assertIn(expected, page)

    def test_mapbox_page_requires_existing_dispatcher_login(self):
        app, _ = self.make_app()
        c = app.test_client()
        response = c.get("/dispatch/map")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/dispatch/login")
        c.get("/dispatch/login")
        with c.session_transaction() as s:
            csrf = s["pd_dispatch_csrf"]
        self.assertEqual(c.post("/dispatch/login", data={
            "password": "test-only-password", "csrf": csrf,
        }).status_code, 302)
        page = c.get("/dispatch/map")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"leaflet", page.data)
        self.assertIn(b"PD_MAPBOX_PUBLIC_TOKEN", page.data)
        self.assertNotIn(b"pk.fake", page.data)
        self.assertEqual(page.headers["Cache-Control"], "private, no-store")
        self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
        self.assertIn("https://api.mapbox.com", page.headers["Content-Security-Policy"])
        self.assertIn("worker-src blob:", page.headers["Content-Security-Policy"])
        self.assertIn(b'href="/dispatch/map"', c.get("/dispatch").data)
        with c.session_transaction() as s:
            csrf = s["pd_dispatch_csrf"]
        c.post("/dispatch/logout", data={"csrf": csrf})
        self.assertEqual(c.get("/dispatch/map").status_code, 302)

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
            "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("old-test-password"),
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

    def test_recovery_code_rotates_password_once_and_closes_prior_session(self):
        code = "synthetic-recovery-code"
        old = "previous-test-password"
        new = "replacement-test-password"
        state = {"credential": generate_password_hash(old)}
        consumed = set()

        def recover(admin_id, previous, replacement, token):
            if previous != state["credential"] or token in consumed:
                return False
            state["credential"] = replacement
            consumed.add(token)
            return True

        store = SimpleNamespace(read=lambda uid: state["credential"], recover=recover)
        core = SimpleNamespace(ADMIN_IDS={999}, is_admin=lambda uid: uid == 999)
        cfg = {
            "PD_DISPATCH_SESSION_SECRET": "synthetic-secret-32-characters-minimum-12345",
            "PD_DISPATCH_ADMIN_ID": "999",
            "PD_DISPATCH_DATABASE_URL": "synthetic-db-dsn",
            "PD_DISPATCH_RECOVERY_SHA256": hashlib.sha256(code.encode()).hexdigest(),
            "PD_DISPATCH_RECOVERY_EXPIRES": str(int(time.time()) + 60),
        }
        with patch.dict(os.environ, cfg, clear=True), patch.object(
                pd_web_dispatcher, "DispatcherPasswords", return_value=store):
            app = Flask("dispatch_recovery")
            self.assertTrue(pd_web_dispatcher.register(app, core))
            signed_in = app.test_client()
            recovery = app.test_client()

            def csrf_for(client, route):
                self.assertEqual(client.get(route).status_code, 200)
                with client.session_transaction() as session:
                    return session["pd_dispatch_csrf"]

            login_url, recover_url = "/dispatch/login", "/dispatch/recover"
            self.assertEqual(signed_in.post(login_url, data={
                "csrf": csrf_for(signed_in, login_url), "password": old,
            }).status_code, 302)
            form = {"csrf": csrf_for(recovery, recover_url), "invite": code,
                    "password": new, "confirmation": new}
            self.assertEqual(recovery.post(recover_url, data={**form, "invite": "wrong"}).status_code, 403)
            self.assertEqual(recovery.post(recover_url, data=form).status_code, 303)
            self.assertEqual(signed_in.get("/dispatch").location, login_url)
            self.assertEqual(recovery.post(recover_url, data={
                **form, "csrf": csrf_for(recovery, recover_url),
            }).status_code, 403)
            csrf = csrf_for(recovery, login_url)
            self.assertEqual(recovery.post(login_url, data={"csrf": csrf, "password": old}).status_code, 200)
            self.assertEqual(recovery.post(login_url, data={"csrf": csrf, "password": new}).location, "/dispatch")

    def test_registration_without_configuration_is_closed(self):
        app, _ = self.make_app(False)
        client = app.test_client()
        page = client.get("/dispatch/register")
        self.assertEqual(page.status_code, 503)
        self.assertNotIn(b'name="invite"', page.data)
        self.assertEqual(client.post("/dispatch/register").status_code, 503)


if __name__ == "__main__":
    unittest.main()
