"""Disposable PostgreSQL 18: verify phone sign-in SQL with least privilege.

Only synthetic data, no SMS provider, no Render connections or real passwords.
"""
import os
import unittest
from urllib.parse import urlsplit
import psycopg
from psycopg.errors import InsufficientPrivilege

from pd_native_phone_grants_ci import install_synthetic_phone_auth_grants
from test_unified_accounts_postgres_integration import SYNTHETIC_OLD_SCHEMA

ROLE = "pd_ci_phone_auth"


class PhoneAuthPostgresGrantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=os.environ.get("PD_CI_POSTGRES_URL","")
        parsed=urlsplit(raw)
        if not (os.environ.get("PD_CI_FAKE_DB_ONLY")=="YES"
                and parsed.scheme=="postgresql"
                and parsed.hostname=="127.0.0.1" and parsed.port==5432
                and parsed.path=="/pd_schema_ci" and parsed.username=="pd_ci"):
            raise RuntimeError("refusing_non_local_synthetic_postgres")
        cls.conn=psycopg.connect(raw)
        with cls.conn.cursor() as cur:
            for statement in SYNTHETIC_OLD_SCHEMA:
                cur.execute(statement)
            cur.execute("""CREATE TABLE native_twilio_challenges(
                  id TEXT PRIMARY KEY, phone TEXT NOT NULL, created_at BIGINT NOT NULL,
                  expires_at BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                  consumed_at BIGINT)""")
            cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cur.execute("""INSERT INTO native_auth_users (id,channel,destination,created_at)
               VALUES ('ci-other','phone','+37060000009',1)""")
            cur.execute("""INSERT INTO native_auth_roles (user_id,role)
               VALUES ('ci-other','admin')""")
        cls.conn.commit()
        install_synthetic_phone_auth_grants(cls.conn)
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.db=self.__class__.conn
        self.db.rollback()
        self.db.execute("SELECT 1") # outer rollback-only transaction

    def tearDown(self):
        self.db.rollback()

    def as_phone_auth(self,sql,params=None):
        self.db.execute("SET LOCAL ROLE "+ROLE)
        return self.db.execute(sql,params)

    def test_request_code_and_verify_code_database_operations(self):
        # Mirrors exact SQL permissions required by existing native auth.
        with self.db.transaction():
            self.as_phone_auth("SELECT pg_advisory_xact_lock(hashtext(%s))",
                               ("+37060000010",))
            self.as_phone_auth("""SELECT created_at FROM native_twilio_challenges
                              WHERE phone=%s ORDER BY created_at DESC LIMIT 1""",
                               ("+37060000010",))
            self.as_phone_auth("""INSERT INTO native_twilio_challenges
                              (id,phone,created_at,expires_at)
                              VALUES ('challenge-ci','+37060000010',100,400)""")
            row=self.as_phone_auth("""SELECT phone,expires_at,attempts,consumed_at
                                    FROM native_twilio_challenges
                                    WHERE id=%s FOR UPDATE""",("challenge-ci",)).fetchone()
            self.assertEqual(row[2],0)
            self.as_phone_auth("""UPDATE native_twilio_challenges
                    SET attempts=attempts+1 WHERE id=%s""",("challenge-ci",))
            self.as_phone_auth("""UPDATE native_twilio_challenges
                    SET consumed_at=%s WHERE id=%s""",(110,"challenge-ci"))
            self.as_phone_auth("""INSERT INTO native_auth_users
                    (id,channel,destination,created_at)
                    VALUES ('ci-registered','phone','+37060000010',110)
                    ON CONFLICT(channel,destination) DO NOTHING""")
            uid=self.as_phone_auth("""SELECT id FROM native_auth_users
                    WHERE channel='phone' AND destination=%s""",
                    ("+37060000010",)).fetchone()[0]
            self.assertEqual(uid,"ci-registered")
            # Role is absent: normal new users fall back to passenger.
            self.assertIsNone(self.as_phone_auth(
                "SELECT role FROM native_auth_roles WHERE user_id=%s",
                (uid,)).fetchone())
            self.as_phone_auth("""INSERT INTO native_auth_sessions
                    (token_hash,user_id,created_at,expires_at)
                    VALUES ('synthetic-hash',%s,110,999999)""",(uid,))
            self.assertEqual(self.as_phone_auth("""SELECT role FROM native_auth_roles
                   WHERE user_id='ci-other'""").fetchone()[0],"admin")
        self.db.execute("RESET ROLE")
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM native_auth_users WHERE id='ci-registered'"
        ).fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM native_auth_sessions WHERE user_id='ci-registered'"
        ).fetchone()[0],1)

    def test_no_role_assignment_or_other_user_role_change(self):
        denied=(
            "INSERT INTO native_auth_roles(user_id,role) VALUES ('ci-registered','admin')",
            "UPDATE native_auth_roles SET role='admin' WHERE user_id='ci-other'",
            "DELETE FROM native_auth_roles WHERE user_id='ci-other'",
            "ALTER TABLE native_auth_roles ADD COLUMN dangerous integer",
            "CREATE TABLE pd_ci_injected_role(id integer)",
        )
        for sql in denied:
            with self.subTest(sql=sql),self.assertRaises(InsufficientPrivilege):
                with self.db.transaction():
                    self.as_phone_auth(sql)

    def test_cannot_read_photo_or_existing_token_hashes(self):
        for sql in (
            "SELECT photo FROM native_identity_checks",
            "SELECT token_hash FROM native_auth_sessions",
            "SELECT destination FROM native_auth_users WHERE id='ci-other' FOR UPDATE",
        ):
            with self.subTest(sql=sql),self.assertRaises(InsufficientPrivilege):
                with self.db.transaction():
                    self.as_phone_auth(sql)

    def test_cannot_update_existing_users_or_sessions_or_sms_phone(self):
        denied=(
            "UPDATE native_auth_users SET destination='+37060000888' WHERE id='ci-other'",
            "DELETE FROM native_auth_users WHERE id='ci-other'",
            "UPDATE native_auth_sessions SET revoked_at=1",
            "UPDATE native_twilio_challenges SET phone='+37060000099'",
            "GRANT pg_read_all_data TO pd_ci_phone_auth",
        )
        for sql in denied:
            with self.subTest(sql=sql),self.assertRaises(InsufficientPrivilege):
                with self.db.transaction():
                    self.as_phone_auth(sql)

    def test_authorization_role_not_public_or_smartphone(self):
        # Explicit grants go only to dedicated NOLOGIN PostgreSQL service role.
        self.assertEqual(self.db.execute("""SELECT rolcanlogin,rolcreaterole
                  FROM pg_roles WHERE rolname=%s""",(ROLE,)).fetchone(),(False,False))
        granted=self.db.execute("""SELECT privilege_type
            FROM information_schema.role_table_grants
            WHERE grantee=%s AND table_name='native_auth_roles'""",
            (ROLE,)).fetchall()
        self.assertFalse(any(v[0] in ('INSERT','UPDATE','DELETE','TRUNCATE')
                             for v in granted))


if __name__=="__main__":
    unittest.main()
