"""Offline-only release gates for the existing staging API and dispatcher.

Reads repository files; never connects to Render or a persistent database.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pd_dispatch_persistent import enabled as dispatcher_enabled, ingest_enabled
from pd_native_orders_http import make_orders_app

ROOT = Path(__file__).resolve().parents[1]


class StagingCompatibilityGate(unittest.TestCase):
    def test_both_staging_dependencies_include_psycopg(self):
        api = (ROOT / "requirements-sms-render.txt").read_text()
        dispatcher = (ROOT / "requirements-dispatcher-staging.txt").read_text()
        registration = (ROOT / "requirements-dispatcher-registration.txt").read_text()
        self.assertIn("psycopg[binary]", api)
        self.assertTrue(
            "psycopg[binary]" in dispatcher
            or ("-r requirements-dispatcher-registration.txt" in dispatcher
                and "psycopg[binary]" in registration))
        self.assertIn("gunicorn", api)
        self.assertIn("gunicorn", dispatcher)

    def test_migrations_guard_database_and_require_explicit_schema(self):
        files = (
            ROOT / "migrations/native_auth_session_functions.sql",
            ROOT / "migrations/native_dispatch_orders.sql",
        )
        for path in files:
            sql = path.read_text()
            self.assertIn("current_database()", sql, path.name)
            self.assertIn("'private_drive_test'", sql, path.name)
            self.assertIn("RAISE EXCEPTION", sql, path.name)
            self.assertIn("BEGIN;", sql, path.name)
            self.assertIn("COMMIT;", sql, path.name)
        functions = files[0].read_text()
        orders = files[1].read_text()
        self.assertIn("pd_validate_native_session", functions)
        self.assertIn("SECURITY DEFINER", functions)
        self.assertIn("REVOKE ALL ON FUNCTION", functions)
        self.assertIn("s.revoked_at IS NULL", functions)
        self.assertIn("CREATE TABLE IF NOT EXISTS public.pd_dispatch_orders", orders)
        self.assertIn("CREATE TABLE IF NOT EXISTS public.pd_native_order_owners", orders)
        self.assertIn("UNIQUE(source,source_order_id)", orders)
        self.assertIn("REFERENCES public.native_auth_users(id)", orders)

    def test_dispatcher_stays_closed_without_explicit_disabled_payments(self):
        settings = {
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_DISPATCH_PERSISTENT_QUEUE": "1",
            "PD_DISPATCH_ORDERS_DATABASE_URL": "postgresql://synthetic.invalid/test",
        }
        for payment_mode in (None, "", "live", "test"):
            with self.subTest(payment_mode=payment_mode):
                with patch.dict(os.environ, settings, clear=True):
                    if payment_mode is not None:
                        os.environ["PD_PAYMENT_MODE"] = payment_mode
                    self.assertFalse(dispatcher_enabled())
                    self.assertFalse(ingest_enabled())
        with patch.dict(os.environ, dict(settings, PD_PAYMENT_MODE="disabled"), clear=True):
            self.assertTrue(dispatcher_enabled())
            self.assertFalse(ingest_enabled())

    def test_api_returns_503_before_db_on_unsafe_configuration(self):
        settings = {
            "PD_NATIVE_SMS_ISOLATED": "YES",
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_DISPATCH_PERSISTENT_QUEUE": "1",
            "PD_DISPATCH_ORDERS_DATABASE_URL": "postgresql://synthetic.invalid/test",
        }
        def next_app(environ, start_response):
            start_response("404 Not Found", [])
            return [b"not found"]
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        for payment_mode in (None, "live", "test"):
            with self.subTest(payment_mode=payment_mode):
                with patch.dict(os.environ, settings, clear=True):
                    if payment_mode:
                        os.environ["PD_PAYMENT_MODE"] = payment_mode
                    app = Client(make_orders_app(next_app, settings["PD_DISPATCH_ORDERS_DATABASE_URL"]), Response)
                    reply = app.get("/native-orders")
                    self.assertEqual(reply.status_code, 503)
                    self.assertEqual(reply.json["error"], "orders_disabled")


if __name__ == "__main__":
    unittest.main()
