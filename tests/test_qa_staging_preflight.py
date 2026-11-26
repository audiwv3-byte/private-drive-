"""Staging preflight tests. Uses only synthetic data and local PostgreSQL."""
import os
import unittest
from unittest.mock import Mock
from pd_qa_staging_preflight import check, REQUIRED

URL = "postgresql://qa:qa@127.0.0.1:5432/private_drive_test"
ENV = {**REQUIRED, "PD_DISPATCH_ORDERS_DATABASE_URL": URL}


class FakeDatabase:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query):
        assert query == "SELECT 1"
        return self

    def fetchone(self):
        return (1,)


class PreflightTests(unittest.TestCase):
    def test_all_flags_and_database_healthy(self):
        self.assertEqual(check(environment=ENV, connect=lambda *a, **kw: FakeDatabase()),
                         {"ready": True, "reason": "ok"})

    def test_every_missing_flag_is_disabled(self):
        for key in REQUIRED:
            with self.subTest(key=key):
                env = dict(ENV)
                env.pop(key)
                self.assertEqual(check(environment=env)["reason"], "staging_flags_invalid")

    def test_invalid_database_url(self):
        env = {**ENV, "PD_DISPATCH_ORDERS_DATABASE_URL": "sqlite:///prod.db"}
        self.assertEqual(check(environment=env)["reason"], "database_url_invalid")

    def test_connection_failure_classified_without_leaking_secrets(self):
        def fail(*args, **kwargs):
            raise RuntimeError("supersecret")
        result = check(environment=ENV, connect=fail)
        self.assertEqual(result, {"ready": False, "reason": "database_unavailable"})
        self.assertNotIn("supersecret", str(result))

    def test_real_synthetic_postgres_if_configured(self):
        url = os.getenv("PD_QA_SYNTHETIC_POSTGRES_URL")
        if not url:
            self.skipTest("synthetic PostgreSQL not configured")
        from psycopg.conninfo import conninfo_to_dict
        fields = conninfo_to_dict(url)
        self.assertEqual(fields.get("host"), "127.0.0.1")
        self.assertEqual(fields.get("dbname"), "private_drive_test")
        self.assertEqual(check(environment={**REQUIRED, "PD_DISPATCH_ORDERS_DATABASE_URL": url}),
                         {"ready": True, "reason": "ok"})


if __name__ == "__main__":
    unittest.main()
