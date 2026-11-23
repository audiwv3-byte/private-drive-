"""End-to-end synthetic PostgreSQL 18 phone-auth startup with no runtime DDL.

Only a local GitHub Actions PostgreSQL fixture. SMS callbacks are in-memory
stubs; no provider, no Render access, no production credentials or migrations.
"""
import io
import json
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.errors import InsufficientPrivilege

from pd_native_auth_postgres_http import make_app
from pd_native_auth_schema_migration import install_native_phone_schema_from_ci_only
from pd_native_phone_grants_ci import install_synthetic_phone_auth_grants

AUTH_PASSWORD = "ci-synthetic-not-real"
USER = "pd_ci_auth_login"


class PhoneAuthStartupWithoutDDLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get("PD_CI_POSTGRES_URL", "")
        p = urlsplit(raw)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES"
            or p.scheme != "postgresql" or p.hostname != "127.0.0.1"
            or p.port != 5432 or p.path != "/pd_schema_ci"
            or p.username != "pd_ci"):
            raise RuntimeError("synthetic_ci_database_required")

        # Explicit migration stage: privileged owner creates the schema once.
        install_native_phone_schema_from_ci_only(raw)
        cls.owner = psycopg.connect(raw)
        with cls.owner.cursor() as cur:
            cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cls.owner.commit()
        install_synthetic_phone_auth_grants(cls.owner)
        with cls.owner.cursor() as cur:
            cur.execute(sql.SQL("""CREATE ROLE pd_ci_auth_login LOGIN INHERIT
                         NOCREATEDB NOCREATEROLE PASSWORD {}""").format(
                             sql.Literal(AUTH_PASSWORD)))
            cur.execute("GRANT pd_ci_phone_auth TO pd_ci_auth_login")
        cls.owner.commit()
        cls.runtime_dsn = (
            f"postgresql://{USER}:{AUTH_PASSWORD}@127.0.0.1:5432/pd_schema_ci"
        )
        # Separate disposable databases model missing/incomplete migrations.
        with psycopg.connect(raw, autocommit=True) as owner_admin:
            owner_admin.execute("CREATE DATABASE pd_schema_empty")
            owner_admin.execute("CREATE DATABASE pd_schema_partial")
        partial_owner_dsn=raw.replace("/pd_schema_ci","/pd_schema_partial")
        with psycopg.connect(partial_owner_dsn) as partial_owner:
            partial_owner.execute("CREATE TABLE native_auth_users(id TEXT PRIMARY KEY)")
        cls.empty_dsn=cls.runtime_dsn.replace("/pd_schema_ci","/pd_schema_empty")
        cls.partial_dsn=cls.runtime_dsn.replace("/pd_schema_ci","/pd_schema_partial")

    @classmethod
    def tearDownClass(cls):
        cls.owner.close()

    @staticmethod
    def request(app, endpoint, payload):
        body = json.dumps(payload).encode()
        environ = {
            "REQUEST_METHOD":"POST", "PATH_INFO":endpoint,
            "CONTENT_TYPE":"application/json",
            "CONTENT_LENGTH":str(len(body)), "wsgi.input":io.BytesIO(body)
        }
        status=[]
        response=b"".join(app(environ,lambda s,h: status.append(s)))
        return status[0],json.loads(response)

    def test_missing_schema_returns_503_and_never_sends_sms(self):
        invoked=[]
        app=make_app(self.empty_dsn,live=True,
                     start_sms=lambda *a,**k: invoked.append("start"),
                     check_sms=lambda *a,**k: invoked.append("verify"))
        health_status,health=self.request(app,"/health",{})
        self.assertEqual(health_status,"503 Service Unavailable")
        self.assertEqual(health["status"],"not_ready")
        self.assertEqual(health["error"],"schema_not_ready")
        self.assertFalse(health["sms_enabled"])
        for endpoint,payload in (
            ("/native-auth/request-code",{"channel":"phone","destination":"+37060001234"}),
            ("/native-auth/verify-code",{"challenge_id":"test","code":"123456"}),
        ):
            status,data=self.request(app,endpoint,payload)
            self.assertEqual(status,"503 Service Unavailable")
            self.assertEqual(data,{"error":"schema_not_ready"})
        self.assertEqual(invoked,[])
        with psycopg.connect(self.empty_dsn) as conn:
            self.assertIsNone(conn.execute(
                "SELECT to_regclass('public.native_auth_users')").fetchone()[0])

    def test_incomplete_schema_returns_503_without_auto_repair(self):
        app=make_app(self.partial_dsn,live=False)
        status,data=self.request(app,"/health",{})
        self.assertEqual(status,"503 Service Unavailable")
        self.assertEqual(data["error"],"schema_not_ready")
        with psycopg.connect(self.partial_dsn) as conn:
            self.assertIsNone(conn.execute(
                "SELECT to_regclass('public.native_auth_sessions')").fetchone()[0])

    def test_ready_database_returns_healthy_status(self):
        app=make_app(self.runtime_dsn,live=False)
        status,data=self.request(app,"/health",{})
        self.assertEqual(status,"200 OK")
        self.assertEqual(data,{"status":"ok","sms_enabled":False})

    def test_normal_startup_does_not_execute_migration_or_create_tables(self):
        # If startup still executes initialize_database, the restricted
        # connection would fail and the test would catch the regression.
        app=make_app(self.runtime_dsn,live=False)
        result=self.request(app,"/native-auth/request-code",
                            {"channel":"phone","destination":"+37060001234"})
        self.assertEqual(result[0],"503 Service Unavailable")
        self.assertEqual(result[1]["error"],"sms_disabled")
        with psycopg.connect(self.runtime_dsn) as conn:
            with self.assertRaises(InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("CREATE TABLE pd_forbidden_runtime_ddl(id INT)")

    def test_registration_and_relogin_with_minimal_grants(self):
        calls=[]
        def fake_start(phone,*,env):
            calls.append(("start",phone))
        def fake_check(phone,code,*,env):
            calls.append(("check",phone))
            return code=="123456"
        app=make_app(self.runtime_dsn,live=True,start_sms=fake_start,
                     check_sms=fake_check,clock=lambda:110000)
        a,challenge=self.request(app,"/native-auth/request-code",
                        {"channel":"phone","destination":"+37060001234"})
        self.assertEqual(a,"202 Accepted")
        b,verified=self.request(app,"/native-auth/verify-code",
                        {"challenge_id":challenge["challenge_id"],"code":"123456"})
        self.assertEqual(b,"200 OK")
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["role"],"passenger")
        self.assertEqual(len(calls),2)
        with self.owner.cursor() as cur:
            cur.execute("""SELECT count(*) FROM native_auth_users
                        WHERE id=%s""",(verified["user_id"],))
            self.assertEqual(cur.fetchone()[0],1)
            cur.execute("""SELECT count(*) FROM native_auth_sessions
                        WHERE user_id=%s""",(verified["user_id"],))
            self.assertEqual(cur.fetchone()[0],1)

    def test_auth_login_cannot_grant_admin_or_change_existing_role(self):
        with psycopg.connect(self.runtime_dsn) as conn:
            for sql in (
                "INSERT INTO native_auth_roles(user_id,role) VALUES ('fake','admin')",
                "UPDATE native_auth_roles SET role='admin' WHERE role='pilot'",
                "DELETE FROM native_auth_roles",
                "CREATE TABLE forbidden_ddl(id INT)",
            ):
                with self.subTest(sql=sql),self.assertRaises(InsufficientPrivilege):
                    with conn.transaction():
                        conn.execute(sql)

    def test_schema_migration_rejects_runtime_connection(self):
        with self.assertRaises(PermissionError):
            install_native_phone_schema_from_ci_only(self.runtime_dsn)


if __name__=="__main__":
    unittest.main()
