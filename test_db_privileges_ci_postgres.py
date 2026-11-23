"""Only synthetic PostgreSQL 18; no Render and no real credentials."""
import hashlib
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from psycopg.errors import InsufficientPrivilege

from pd_db_privileges_ci import install_synthetic_acl
from pd_unified_accounts_schema import install_schema
from test_unified_accounts_postgres_integration import SYNTHETIC_OLD_SCHEMA

TOKEN = "synthetic-server-owner-token-for-ci-" + "x" * 40
HASH = hashlib.sha256(TOKEN.encode()).hexdigest()


class LeastPrivilegePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url=os.environ.get("PD_CI_POSTGRES_URL","")
        p=urlsplit(url)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY")!="YES"
                or p.scheme!="postgresql" or p.hostname!="127.0.0.1"
                or p.port!=5432 or p.path!="/pd_schema_ci"
                or p.username!="pd_ci"):
            raise RuntimeError("Refusing non-CI Postgres")
        cls.db=psycopg.connect(url)
        with cls.db.cursor() as cur:
            for statement in SYNTHETIC_OLD_SCHEMA:
                cur.execute(statement)
        install_schema(cls.db)
        with cls.db.cursor() as cur:
            cur.execute("""INSERT INTO native_auth_users (id,channel,destination,created_at)
                        VALUES ('ci-owner','phone','+37060000001',1),
                               ('ci-pilot','phone','+37060000002',1),
                               ('ci-passenger','phone','+37060000003',1)""")
            cur.execute("""INSERT INTO native_auth_roles (user_id,role)
                        VALUES ('ci-owner','admin'),('ci-pilot','pilot'),
                               ('ci-passenger','passenger')""")
            cur.execute("""INSERT INTO native_auth_sessions
                        (token_hash,user_id,created_at,expires_at)
                        VALUES (%s,'ci-owner',1,9999999999)""",(HASH,))
            cur.execute("""INSERT INTO pd_pilot_reviews(user_id,review_status)
                        VALUES ('ci-pilot','pending')""")
        cls.db.commit()
        install_synthetic_acl(cls.db)
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db=self.__class__.db
        self.db.rollback()
        # Keep one outer transaction for each test; nested transaction() uses
        # SAVEPOINT, so successful approval is never committed into later tests.
        self.db.execute("SELECT 1")

    def tearDown(self):
        self.db.rollback()

    def role_sql(self, role, statement, args=None):
        # SET ROLE only simulates separate credentials in isolated CI.
        self.db.execute("SET LOCAL ROLE "+role)
        return self.db.execute(statement,args)

    def test_application_cannot_change_roles_or_reviews_or_schema(self):
        for statement in (
            "UPDATE native_auth_roles SET role='admin' WHERE user_id='ci-pilot'",
            "UPDATE pd_pilot_reviews SET review_status='approved' WHERE user_id='ci-pilot'",
            "INSERT INTO native_auth_roles (user_id,role) VALUES ('x','admin')",
            "CREATE TABLE pd_unauthorized (id int)",
        ):
            with self.subTest(statement=statement),self.assertRaises(InsufficientPrivilege):
                with self.db.transaction():
                    self.role_sql("pd_ci_runtime",statement)

    def test_application_cannot_read_sensitive_native_tables(self):
        for table in ("native_auth_roles","native_auth_sessions",
                      "native_identity_checks","pd_pilot_reviews"):
            with self.subTest(table=table),self.assertRaises(InsufficientPrivilege):
                with self.db.transaction():
                    self.role_sql("pd_ci_runtime","SELECT * FROM "+table)

    def test_application_reads_only_masked_projection(self):
        with self.db.transaction():
            rows=self.role_sql("pd_ci_runtime",
                "SELECT user_id,phone_masked,role FROM pd_ci_public_accounts ORDER BY user_id").fetchall()
            self.assertEqual(len(rows),3)
            self.assertTrue(all("••••" in row[1] for row in rows))
            self.assertEqual(sum(1 for row in rows if row[2]=='admin'),1)

    def test_reviewer_cannot_forge_direct_update_or_role_grant(self):
        for statement in (
            "UPDATE pd_pilot_reviews SET review_status='approved', reviewed_by='ci-owner', reviewed_at=now() WHERE user_id='ci-pilot'",
            "UPDATE native_auth_roles SET role='admin' WHERE user_id='ci-pilot'",
            "GRANT pd_ci_migrator TO pd_ci_runtime",
        ):
            with self.subTest(statement=statement),self.assertRaises(InsufficientPrivilege):
                with self.db.transaction():
                    self.role_sql("pd_ci_reviewer",statement)

    def test_reviewer_function_denies_fake_or_non_admin_tokens(self):
        with self.db.transaction():
            for fake in ("f"*64,""):
                row=self.role_sql("pd_ci_reviewer",
                    "SELECT pd_ci_approve_pilot(%s,%s)",(fake,"ci-pilot")).fetchone()
                self.assertEqual(row,(False,))
        self.assertEqual(self.db.execute(
            "SELECT pilot_review_status FROM pd_ci_public_accounts WHERE user_id='ci-pilot'").fetchone()[0],"pending")

    def test_reviewer_function_allows_real_admin_and_preserves_roles(self):
        with self.db.transaction():
            row=self.role_sql("pd_ci_reviewer",
                "SELECT pd_ci_approve_pilot(%s,%s)",(HASH,"ci-pilot")).fetchone()
            self.assertEqual(row,(True,))
        self.assertEqual(self.db.execute(
            "SELECT pilot_review_status FROM pd_ci_public_accounts WHERE user_id='ci-pilot'").fetchone()[0],"approved")
        with self.db.cursor() as cur:
            cur.execute("SELECT role FROM native_auth_roles WHERE user_id='ci-pilot'")
            self.assertEqual(cur.fetchone()[0],"pilot")

    def test_app_cannot_execute_admin_function_and_reviewer_cannot_ddl(self):
        with self.assertRaises(InsufficientPrivilege):
            with self.db.transaction():
                self.role_sql("pd_ci_runtime",
                   "SELECT pd_ci_approve_pilot(%s,%s)",(HASH,"ci-pilot"))
        with self.assertRaises(InsufficientPrivilege):
            with self.db.transaction():
                self.role_sql("pd_ci_reviewer","CREATE TABLE pd_bad (id int)")


if __name__=="__main__":
    unittest.main()
