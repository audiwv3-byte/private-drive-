"""Synthetic PG18 role migration, grants, identity, and session regression."""
import hashlib
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.errors import InsufficientPrivilege, UniqueViolation, CheckViolation

from pd_native_auth_schema_migration import initialize_database
from pd_native_auth_role_migration import (
    ROLES, migrate_roles_on_connection, migrate_roles_synthetic_ci_only,
)
from pd_native_phone_grants_ci import install_synthetic_phone_auth_grants
from pd_native_auth_logout_schema_ci import install_synthetic_logout_function

DB_NAME = "pd_role_migration_ci"
LOGIN = "pd_role_runtime_ci"
PW = "synthetic-only-role-tests"
NOW = 20000


class RoleMigrationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get("PD_CI_POSTGRES_URL", "")
        parsed = urlsplit(url)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES" or
                parsed.scheme != "postgresql" or parsed.hostname != "127.0.0.1"
                or parsed.port != 5432 or parsed.username != "pd_ci"
                or parsed.path != "/pd_schema_ci"):
            raise RuntimeError("not_synthetic_ci_database")
        cls.owner = url.replace("/pd_schema_ci", "/" + DB_NAME)
        cls.runtime = f"postgresql://{LOGIN}:{PW}@127.0.0.1:5432/{DB_NAME}"
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            db.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT NOCREATEROLE NOCREATEDB PASSWORD {}")
                       .format(sql.Identifier(LOGIN), sql.Literal(PW)))
        initialize_database(cls.owner)  # historical 3-role schema fixture
        with psycopg.connect(cls.owner) as db:
            db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            install_synthetic_phone_auth_grants(db)
            install_synthetic_logout_function(db)
            db.execute(sql.SQL("GRANT pd_ci_phone_auth TO {}").format(sql.Identifier(LOGIN)))
            for user_id, phone, role in (
                ("existing-admin", "+37060005001", "admin"),
                ("existing-pilot", "+37060005002", "pilot"),
                ("existing-passenger", "+37060005003", "passenger"),
            ):
                db.execute("""INSERT INTO native_auth_users(id,channel,destination,created_at)
                    VALUES (%s,'phone',%s,%s)""", (user_id, phone, NOW-100))
                db.execute("""INSERT INTO native_auth_roles(user_id,role)
                    VALUES (%s,%s)""", (user_id, role))
            cls.old_token = "synthetic-old-pilot-session-" + "a" * 48
            cls.old_hash = hashlib.sha256(cls.old_token.encode()).hexdigest()
            db.execute("""INSERT INTO native_auth_sessions
                (token_hash,user_id,created_at,expires_at)
                VALUES (%s,'existing-pilot',%s,%s)""",
                (cls.old_hash, NOW-100, NOW+300))
        cls.before = cls.snapshot()

    @classmethod
    def snapshot(cls):
        with psycopg.connect(cls.owner) as db:
            return {
                "users": db.execute("""SELECT id,channel,destination,created_at
                    FROM native_auth_users ORDER BY id""").fetchall(),
                "roles": db.execute("""SELECT user_id,role
                    FROM native_auth_roles ORDER BY user_id""").fetchall(),
                "sessions": db.execute("""SELECT token_hash,user_id,created_at,
                    expires_at,revoked_at FROM native_auth_sessions
                    ORDER BY token_hash""").fetchall(),
            }

    def test_01_migration_preserves_existing_user_roles_and_sessions(self):
        with psycopg.connect(self.owner) as db:
            self.assertTrue(migrate_roles_on_connection(db))
        self.assertEqual(self.snapshot(), self.before)
        self.assertFalse(migrate_roles_synthetic_ci_only(self.owner))
        self.assertEqual(self.snapshot(), self.before)

    def test_02_all_five_roles_are_database_allowed_but_admin_is_unique(self):
        with psycopg.connect(self.owner) as db:
            for index, role in enumerate(("dispatcher", "pilot_dispatcher"), start=1):
                uid=f"new-role-{index}"
                db.execute("""INSERT INTO native_auth_users(id,channel,destination,created_at)
                    VALUES (%s,'phone',%s,%s)""", (uid, f"+370600050{index+3:02d}", NOW))
                db.execute("INSERT INTO native_auth_roles(user_id,role) VALUES (%s,%s)",
                           (uid,role))
            rows = db.execute("SELECT role FROM native_auth_roles").fetchall()
            self.assertEqual({r[0] for r in rows}, set(ROLES))
        with psycopg.connect(self.owner) as db:
            with self.assertRaises(UniqueViolation):
                with db.transaction():
                    db.execute("""UPDATE native_auth_roles SET role='admin'
                        WHERE user_id='new-role-1'""")
        with psycopg.connect(self.owner) as db:
            with self.assertRaises(CheckViolation):
                with db.transaction():
                    db.execute("""UPDATE native_auth_roles SET role='superuser'
                        WHERE user_id='new-role-2'""")

    def test_03_runtime_role_grants_remain_read_only(self):
        with psycopg.connect(self.runtime) as runtime:
            rows = runtime.execute("SELECT user_id,role FROM native_auth_roles").fetchall()
            self.assertEqual({r[1] for r in rows}, set(ROLES))
            for query in (
                "UPDATE native_auth_roles SET role='admin' WHERE user_id='existing-pilot'",
                "DELETE FROM native_auth_roles WHERE user_id='existing-admin'",
                "INSERT INTO native_auth_roles(user_id,role) VALUES ('fake','admin')",
                "ALTER TABLE native_auth_roles DROP CONSTRAINT native_auth_roles_role_check",
            ):
                with self.subTest(query=query), self.assertRaises(InsufficientPrivilege):
                    with runtime.transaction():
                        runtime.execute(query)
        self.assertEqual(self.snapshot()["sessions"], self.before["sessions"])

    def test_04_server_side_session_roles_follow_migration(self):
        with psycopg.connect(self.owner) as owner:
            owner.execute("""INSERT INTO native_auth_sessions
                (token_hash,user_id,created_at,expires_at)
                VALUES (%s,'new-role-1',%s,%s),(%s,'new-role-2',%s,%s)""",
                ("b"*64,NOW-100,NOW+300,"c"*64,NOW-100,NOW+300))
        with psycopg.connect(self.runtime) as runtime:
            rows = runtime.execute("""SELECT user_id,server_role FROM
                public.pd_validate_native_session(%s,%s)""",
                (self.old_hash,NOW)).fetchall()
            self.assertEqual(rows, [("existing-pilot","pilot")])
            self.assertEqual(runtime.execute("""SELECT server_role FROM
                public.pd_validate_native_session(%s,%s)""",
                ("b"*64,NOW)).fetchone()[0], "dispatcher")
            self.assertEqual(runtime.execute("""SELECT server_role FROM
                public.pd_validate_native_session(%s,%s)""",
                ("c"*64,NOW)).fetchone()[0], "pilot_dispatcher")

    def test_05_migration_rejects_non_ci_or_remote_targets(self):
        with self.assertRaises(PermissionError):
            migrate_roles_synthetic_ci_only(
                "postgresql://pd_ci:synthetic@remote.invalid:5432/pd_role_migration_ci")


if __name__ == "__main__":
    unittest.main()
