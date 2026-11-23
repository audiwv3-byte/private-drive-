"""Multi-device PostgreSQL 18 session lifecycle, disposable synthetic CI only.

No Render/remote access, real SMS or credentials. Three independent bearer
tokens model devices for one user, and one token models a second user.
"""
import hashlib
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.errors import InsufficientPrivilege

from pd_native_auth_schema_migration import initialize_database
from pd_native_auth_postgres_session_lifecycle import (
    inspect_session, revoke_current_session,
)

DB = "pd_session_lifecycle_ci"
LOGIN = "pd_ci_session_service"
PASSWORD = "synthetic-session-test-only"
NOW = 1_000_000
A = "synthetic-device-A-" + "a" * 50
B = "synthetic-device-B-" + "b" * 50
C = "synthetic-device-C-" + "c" * 50
OTHER = "synthetic-other-account-" + "d" * 50
EXPIRED = "synthetic-expired-token-" + "e" * 50
FUTURE = "synthetic-not-yet-token-" + "f" * 50


def h(token):
    return hashlib.sha256(token.encode()).hexdigest()


class MultiDeviceSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get("PD_CI_POSTGRES_URL", "")
        u = urlsplit(raw)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES"
                or u.scheme != "postgresql" or u.hostname != "127.0.0.1"
                or u.port != 5432 or u.path != "/pd_schema_ci"
                or u.username != "pd_ci"):
            raise RuntimeError("refusing_non_local_synthetic_postgres")

        cls.owner_dsn = raw.replace("/pd_schema_ci", "/" + DB)
        cls.service_dsn = (f"postgresql://{LOGIN}:{PASSWORD}"
                           f"@127.0.0.1:5432/{DB}")
        with psycopg.connect(raw, autocommit=True) as root:
            root.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            root.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT "
                "NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(LOGIN), sql.Literal(PASSWORD)))
        initialize_database(cls.owner_dsn)
        with psycopg.connect(cls.owner_dsn) as db:
            db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            db.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(LOGIN)))
            db.execute(sql.SQL("GRANT SELECT ON native_auth_users,native_auth_roles "
                              "TO {}").format(sql.Identifier(LOGIN)))
            db.execute(sql.SQL("GRANT SELECT ON native_auth_sessions TO {}").format(
                sql.Identifier(LOGIN)))
            db.execute(sql.SQL("GRANT UPDATE (revoked_at) ON native_auth_sessions TO {}").format(
                sql.Identifier(LOGIN)))
            db.execute("""INSERT INTO native_auth_users (id,channel,destination,created_at)
                VALUES ('pilot-user','phone','+37060000041',1),
                       ('other-user','phone','+37060000042',1)""")
            db.execute("""INSERT INTO native_auth_roles (user_id,role)
                VALUES ('pilot-user','pilot'),('other-user','passenger')""")
            for token,user,created,expires in (
                (A,"pilot-user",NOW-100,NOW+500),
                (B,"pilot-user",NOW-100,NOW+500),
                (C,"pilot-user",NOW-100,NOW+500),
                (EXPIRED,"pilot-user",NOW-100,NOW),
                (FUTURE,"pilot-user",NOW+10,NOW+500),
                (OTHER,"other-user",NOW-100,NOW+500),
            ):
                db.execute("""INSERT INTO native_auth_sessions
                    (token_hash,user_id,created_at,expires_at)
                    VALUES (%s,%s,%s,%s)""",(h(token),user,created,expires))

    def setUp(self):
        self.conn = psycopg.connect(self.service_dsn)
        self.conn.execute("SELECT 1")  # rollback-only transaction per test

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def test_revoke_one_device_preserves_other_two_and_other_user(self):
        self.assertEqual(inspect_session(self.conn,A,now=NOW),
                         ("pilot-user","pilot"))
        self.assertTrue(revoke_current_session(self.conn,A,now=NOW))
        self.assertIsNone(inspect_session(self.conn,A,now=NOW))
        for token in (B,C):
            self.assertEqual(inspect_session(self.conn,token,now=NOW),
                             ("pilot-user","pilot"))
        self.assertEqual(inspect_session(self.conn,OTHER,now=NOW),
                         ("other-user","passenger"))
        self.assertFalse(revoke_current_session(self.conn,A,now=NOW))
        # Ensure exactly one synthetic row was revoked.
        self.assertEqual(self.conn.execute("""SELECT count(*)
            FROM native_auth_sessions WHERE revoked_at IS NOT NULL""").fetchone()[0],1)

    def test_expired_future_and_invalid_tokens_denied(self):
        for token in (EXPIRED,FUTURE,"missing-token-"+"x"*60,"bad"):
            with self.subTest(token_type=token[:8]):
                self.assertIsNone(inspect_session(self.conn,token,now=NOW))
                self.assertFalse(revoke_current_session(self.conn,token,now=NOW))

    def test_expiration_boundary_is_strict(self):
        self.assertEqual(inspect_session(self.conn,B,now=NOW+499),
                         ("pilot-user","pilot"))
        self.assertIsNone(inspect_session(self.conn,B,now=NOW+500))
        self.assertFalse(revoke_current_session(self.conn,B,now=NOW+500))

    def test_no_client_assigned_admin_and_no_role_change(self):
        self.assertEqual(inspect_session(self.conn,B,now=NOW),
                         ("pilot-user","pilot"))
        with self.assertRaises(InsufficientPrivilege):
            with self.conn.transaction():
                self.conn.execute("""UPDATE native_auth_roles SET role='admin'
                                  WHERE user_id='pilot-user'""")
        self.assertEqual(inspect_session(self.conn,B,now=NOW),
                         ("pilot-user","pilot"))

    def test_session_identifiers_are_independent_hashes(self):
        digests = {h(t) for t in (A,B,C)}
        self.assertEqual(len(digests),3)
        rows = self.conn.execute("""SELECT token_hash FROM native_auth_sessions
                                   WHERE user_id='pilot-user'
                                     AND expires_at>%s AND created_at<=%s""",
                                 (NOW,NOW)).fetchall()
        self.assertEqual({row[0] for row in rows},digests)

    def test_logout_cannot_revoke_with_wrong_or_expired_token(self):
        self.assertFalse(revoke_current_session(self.conn,"x"*60,now=NOW))
        self.assertFalse(revoke_current_session(self.conn,EXPIRED,now=NOW))
        self.assertEqual(inspect_session(self.conn,B,now=NOW),
                         ("pilot-user","pilot"))


if __name__=="__main__":
    unittest.main()
