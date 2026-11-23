"""Integration test on disposable PostgreSQL 18 in GitHub Actions ONLY.

The CI database is a synthetic Docker service on localhost. A hard gate refuses
Render or any remote host. Test inserts and migration never touch real data.
"""
import os
import unittest
from urllib.parse import urlsplit

from pd_unified_accounts_schema import install_schema, safe_dispatcher_registry_sql

SYNTHETIC_OLD_SCHEMA = (
    """CREATE TABLE native_auth_users (
       id TEXT PRIMARY KEY,
       channel TEXT NOT NULL,
       destination TEXT NOT NULL,
       created_at BIGINT NOT NULL,
       UNIQUE(channel,destination)
    )""",
    """CREATE TABLE native_auth_roles (
       user_id TEXT PRIMARY KEY REFERENCES native_auth_users(id),
       role TEXT NOT NULL CHECK (role IN ('passenger','pilot','admin'))
    )""",
    """CREATE UNIQUE INDEX native_auth_one_admin
       ON native_auth_roles(role) WHERE role='admin'""",
    """CREATE TABLE native_auth_sessions (
       token_hash TEXT PRIMARY KEY,
       user_id TEXT NOT NULL REFERENCES native_auth_users(id),
       created_at BIGINT NOT NULL,
       expires_at BIGINT NOT NULL,
       revoked_at BIGINT
    )""",
    """CREATE TABLE native_identity_checks (
       id TEXT PRIMARY KEY,
       user_id TEXT NOT NULL REFERENCES native_auth_users(id),
       status TEXT NOT NULL
          CHECK (status IN ('pending','approved','rejected','expired')),
       photo BYTEA,
       created_at BIGINT NOT NULL,
       expires_at BIGINT NOT NULL,
       reviewer_id TEXT REFERENCES native_auth_users(id),
       decided_at BIGINT
    )""",
)


class MigrationPostgres18Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES":
            raise RuntimeError("Live PostgreSQL migration tests forbidden")
        url = os.environ.get("PD_CI_POSTGRES_URL", "")
        parsed = urlsplit(url)
        if (parsed.hostname not in ("localhost", "127.0.0.1")
                or parsed.path != "/pd_schema_ci"
                or parsed.port != 5432):
            raise RuntimeError("Refusing non-local, non-synthetic PostgreSQL")
        import psycopg
        cls.conn = psycopg.connect(url)
        with cls.conn.cursor() as cur:
            for sql in SYNTHETIC_OLD_SCHEMA:
                cur.execute(sql)
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.conn = self.__class__.conn

    def tearDown(self):
        self.conn.rollback()

    def seed(self):
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO native_auth_users(id,channel,destination,created_at)
                           VALUES ('passenger-fixture','phone','+37060000001',1),
                                  ('pilot-fixture','phone','+37060000002',2),
                                  ('admin-fixture','phone','+37060000003',3)""")
            cur.execute("""INSERT INTO native_auth_roles(user_id,role) VALUES
                           ('pilot-fixture','pilot'),('admin-fixture','admin')""")
            cur.execute("""INSERT INTO native_auth_sessions
                           (token_hash,user_id,created_at,expires_at)
                           VALUES ('synthetic-hash-only','passenger-fixture',10,1000000)""")
            cur.execute("""INSERT INTO native_identity_checks
                           (id,user_id,status,photo,created_at,expires_at)
                           VALUES ('synthetic-check','pilot-fixture','pending',
                                   decode('000102','hex'),10,1000)""")

    def test_additive_migration_preserves_existing_accounts_and_sessions(self):
        self.seed()
        with self.conn.cursor() as cur:
            cur.execute("""SELECT id,channel,destination,created_at FROM native_auth_users
                           ORDER BY id""")
            users_before = cur.fetchall()
            cur.execute("SELECT * FROM native_auth_sessions")
            sessions_before = cur.fetchall()
            cur.execute("SELECT * FROM native_identity_checks")
            checks_before = cur.fetchall()
            cur.execute("SELECT * FROM native_auth_roles ORDER BY user_id")
            roles_before = cur.fetchall()
        install_schema(self.conn)
        install_schema(self.conn)  # idempotent
        with self.conn.cursor() as cur:
            cur.execute("SELECT id,channel,destination,created_at FROM native_auth_users ORDER BY id")
            self.assertEqual(cur.fetchall(), users_before)
            cur.execute("SELECT * FROM native_auth_sessions")
            self.assertEqual(cur.fetchall(), sessions_before)
            cur.execute("SELECT * FROM native_identity_checks")
            self.assertEqual(cur.fetchall(), checks_before)
            cur.execute("SELECT * FROM native_auth_roles ORDER BY user_id")
            self.assertEqual(cur.fetchall(), roles_before)
            cur.execute(safe_dispatcher_registry_sql())
            rows = cur.fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row[5] is None for row in rows))
        self.assertTrue(any(row[1] == "admin" for row in rows))

    def test_telegram_link_unique_and_pilot_approval_requires_reviewer(self):
        self.seed()
        install_schema(self.conn)
        from psycopg.errors import CheckViolation, UniqueViolation, ForeignKeyViolation
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO pd_account_telegram_links
                    (user_id,telegram_subject,verified_at,verification_method)
                    VALUES ('pilot-fixture','7035610182',NOW(),'telegram_oidc')""")
        # A duplicate Telegram subject must not attach to another user.
        with self.assertRaises(UniqueViolation):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute("""INSERT INTO pd_account_telegram_links
                        (user_id,telegram_subject,verified_at,verification_method)
                        VALUES ('passenger-fixture','7035610182',NOW(),'telegram_oidc')""")
        # An approved pilot without a reviewer must be rejected.
        with self.assertRaises(CheckViolation):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute("""INSERT INTO pd_pilot_reviews(user_id,review_status)
                                   VALUES ('pilot-fixture','approved')""")
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO pd_pilot_reviews(user_id,review_status)
                           VALUES ('pilot-fixture','pending')""")
            cur.execute("""UPDATE pd_pilot_reviews
                           SET review_status='approved', reviewed_by='admin-fixture',
                               reviewed_at=NOW() WHERE user_id='pilot-fixture'""")
            cur.execute("""SELECT review_status FROM pd_pilot_reviews
                           WHERE user_id='pilot-fixture'""")
            self.assertEqual(cur.fetchone()[0], "approved")

    def test_schema_migration_is_rollback_safe(self):
        self.seed()
        install_schema(self.conn)
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM information_schema.tables
                           WHERE table_schema='public' AND
                           table_name IN ('pd_account_telegram_links','pd_pilot_reviews',
                                          'pd_account_profiles')""")
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute("""SELECT count(*) FROM information_schema.tables
                           WHERE table_schema='public' AND table_name='native_auth_users'""")
            self.assertEqual(cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
