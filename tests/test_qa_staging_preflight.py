"""QA staging readiness tests; all external DB traffic targets synthetic localhost."""
import os
import unittest
from pd_qa_staging_preflight import check, REQUIRED, BASE_RELATIONS, QA26_RELATIONS

URL = "postgresql://qa:qa@127.0.0.1:5432/private_drive_test"
ENV = {**REQUIRED, "PD_DISPATCH_ORDERS_DATABASE_URL": URL}


class FakeDatabase:
    def __init__(self, missing=(), ping=(1,), failure=False):
        self.missing = set(missing)
        self.ping = ping
        self.failure = failure

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        if self.failure:
            raise RuntimeError("secret-should-not-leak")
        if query == "SELECT 1":
            self.row = self.ping
        else:
            assert query in ("SELECT to_regclass(%s)", "SELECT to_regprocedure(%s)")
            self.row = (None if params[0] in self.missing else params[0],)
        return self

    def fetchone(self):
        return self.row


def fake(db):
    return lambda *args, **kwargs: db


class PreflightTests(unittest.TestCase):
    def test_all_flags_and_schema_healthy(self):
        self.assertEqual(check(environment=ENV, connect=fake(FakeDatabase())),
                         {"ready": True, "reason": "ok"})

    def test_every_missing_flag_is_disabled(self):
        for key in REQUIRED:
            with self.subTest(key=key):
                env = dict(ENV)
                env.pop(key)
                self.assertEqual(check(environment=env)["reason"], "staging_flags_invalid")

    def test_invalid_database_url(self):
        self.assertEqual(check(environment={**ENV, "PD_DISPATCH_ORDERS_DATABASE_URL": "sqlite:///prod.db"})["reason"],
                         "database_url_invalid")

    def test_connection_failure_no_secret_leak(self):
        result = check(environment=ENV, connect=fake(FakeDatabase(failure=True)))
        self.assertEqual(result, {"ready": False, "reason": "database_unavailable"})
        self.assertNotIn("secret-should-not-leak", str(result))

    def test_bad_database_ping(self):
        self.assertEqual(check(environment=ENV, connect=fake(FakeDatabase(ping=(0,))))["reason"],
                         "database_healthcheck_failed")

    def test_missing_base_schema(self):
        for relation in BASE_RELATIONS + ("public.pd_validate_native_session(text,bigint)",):
            with self.subTest(relation=relation):
                self.assertEqual(check(environment=ENV, connect=fake(FakeDatabase(missing=(relation,))))["reason"],
                                 "database_schema_missing")

    def test_qa26_requires_additional_schema(self):
        env = {**ENV, "PD_QA26_ASSIGNMENT": "1"}
        for relation in QA26_RELATIONS:
            with self.subTest(relation=relation):
                self.assertEqual(check(environment=env, connect=fake(FakeDatabase(missing=(relation,))))["reason"],
                                 "database_schema_missing")

    def test_real_synthetic_postgres_if_configured(self):
        url = os.getenv("PD_QA_SYNTHETIC_POSTGRES_URL")
        if not url:
            self.skipTest("synthetic PostgreSQL not configured")
        from pathlib import Path
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        fields = conninfo_to_dict(url)
        self.assertEqual(fields.get("host"), "127.0.0.1")
        self.assertEqual(fields.get("dbname"), "private_drive_test")
        with psycopg.connect(url, autocommit=True) as db:
            db.execute("CREATE TABLE native_auth_users (id text PRIMARY KEY)")
            db.execute("CREATE TABLE native_auth_sessions (token_hash text PRIMARY KEY, user_id text, created_at bigint, expires_at bigint, revoked_at bigint)")
            db.execute("CREATE TABLE native_auth_roles (user_id text PRIMARY KEY, role text)")
            db.execute((Path("migrations") / "native_auth_session_functions.sql").read_text())
            db.execute((Path("migrations") / "native_dispatch_orders.sql").read_text())
        self.assertEqual(check(environment={**REQUIRED, "PD_DISPATCH_ORDERS_DATABASE_URL": url}),
                         {"ready": True, "reason": "ok"})


if __name__ == "__main__":
    unittest.main()
