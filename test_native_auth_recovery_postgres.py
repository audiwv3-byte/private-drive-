"""Synthetic-only PostgreSQL 18 recovery drills, no real SMS or Render.

Tests restart after missing schema and connection outage; prior users, roles,
and token digests remain stable. No production data or credentials.
"""
import hashlib
import io
import json
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.errors import InsufficientPrivilege

from pd_native_auth_postgres_http import make_app
from pd_native_auth_schema_migration import initialize_database
from pd_native_phone_grants_ci import install_synthetic_phone_auth_grants

CI_LOGIN = "pd_ci_recovery_login"
CI_PASSWORD = "ci-recovery-synthetic-password"
CI_PHONE = "+37060000077"


def wsgi(app, method, path, payload=None):
    body=json.dumps(payload or {}).encode()
    env={"REQUEST_METHOD":method,"PATH_INFO":path,"CONTENT_TYPE":"application/json",
         "CONTENT_LENGTH":str(len(body)),"wsgi.input":io.BytesIO(body)}
    result=[]
    raw=b"".join(app(env,lambda status,headers: result.append(status)))
    return result[0],json.loads(raw)


class NativeAuthRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=os.environ.get("PD_CI_POSTGRES_URL","")
        url=urlsplit(raw)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY")!="YES"
                or url.scheme!="postgresql" or url.hostname!="127.0.0.1"
                or url.port!=5432 or url.username!="pd_ci"
                or url.path!="/pd_schema_ci"):
            raise RuntimeError("refusing_non_synthetic_database")
        cls.db_root=raw
        with psycopg.connect(raw,autocommit=True) as admin:
            admin.execute("CREATE DATABASE pd_recovery_ci")
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {}").format(
                sql.Identifier(CI_LOGIN),sql.Literal(CI_PASSWORD)))
        cls.privileged=raw.replace("/pd_schema_ci","/pd_recovery_ci")
        cls.restricted=(f"postgresql://{CI_LOGIN}:{CI_PASSWORD}"
                        "@127.0.0.1:5432/pd_recovery_ci")
        cls.dead=(f"postgresql://{CI_LOGIN}:{CI_PASSWORD}"
                  "@127.0.0.1:5432/pd_recovery_unavailable_ci")
        cls.now=[100_000]
        cls.invocations=[]

    @staticmethod
    def start(phone,*,env):
        NativeAuthRecoveryTests.invocations.append(("start",phone))

    @staticmethod
    def verify(phone,code,*,env):
        NativeAuthRecoveryTests.invocations.append(("verify",phone))
        return code=="123456"

    @classmethod
    def serve(cls,dsn):
        return make_app(dsn,live=True,start_sms=cls.start,
                        check_sms=cls.verify,clock=lambda: cls.now[0])

    @classmethod
    def complete_login(cls,app):
        status,ch=wsgi(app,"POST","/native-auth/request-code",
                {"channel":"phone","destination":CI_PHONE})
        if status!="202 Accepted":
            raise AssertionError("request_failed: "+status)
        status,data=wsgi(app,"POST","/native-auth/verify-code",
                {"challenge_id":ch["challenge_id"],"code":"123456"})
        if status!="200 OK":
            raise AssertionError("verify_failed: "+status)
        return data

    def test_01_missing_schema_then_explicit_migration_restart(self):
        self.invocations.clear()
        app=self.serve(self.restricted)
        status,data=wsgi(app,"GET","/health")
        self.assertEqual(status,"503 Service Unavailable")
        self.assertEqual(data["error"],"schema_not_ready")
        status,data=wsgi(app,"POST","/native-auth/request-code",
                {"channel":"phone","destination":CI_PHONE})
        self.assertEqual(status,"503 Service Unavailable")
        self.assertEqual(self.invocations,[])

        # Privileged schema installer is invoked ONLY as a standalone CI step.
        initialize_database(self.privileged)
        with psycopg.connect(self.privileged) as owner:
            owner.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            install_synthetic_phone_auth_grants(owner)
            owner.execute("GRANT pd_ci_phone_auth TO "+CI_LOGIN)
        # The failed process does not magically enable itself; a new instance
        # checks the schema and can then operate with restricted SQL grants.
        status,data=wsgi(app,"GET","/health")
        self.assertEqual(status,"503 Service Unavailable")
        app=self.serve(self.restricted)
        self.assertEqual(wsgi(app,"GET","/health")[0],"200 OK")
        first=self.complete_login(app)
        self.assertEqual(first["role"],"passenger")
        self.__class__.first=first
        self.assertEqual(len(self.invocations),2)

    def test_02_outage_then_restart_preserves_session_and_identity(self):
        original=self.__class__.first
        original_hash=hashlib.sha256(original["access_token"].encode()).hexdigest()
        with psycopg.connect(self.privileged) as db:
            before_users=db.execute("SELECT id,channel,destination FROM native_auth_users").fetchall()
            before_sessions=db.execute(
                "SELECT token_hash,user_id,expires_at,revoked_at FROM native_auth_sessions").fetchall()
            before_roles=db.execute("SELECT user_id,role FROM native_auth_roles").fetchall()

        self.invocations.clear()
        outage=self.serve(self.dead)
        self.assertEqual(wsgi(outage,"GET","/health"),
                         ("503 Service Unavailable",{"status":"not_ready",
                           "error":"database_unavailable","sms_enabled":False}))
        self.assertEqual(wsgi(outage,"POST","/native-auth/request-code",
                {"channel":"phone","destination":CI_PHONE}),
                ("503 Service Unavailable",{"error":"database_unavailable"}))
        self.assertEqual(self.invocations,[])
        with psycopg.connect(self.privileged) as db:
            self.assertEqual(db.execute(
                "SELECT id,channel,destination FROM native_auth_users").fetchall(),before_users)
            self.assertEqual(db.execute(
                "SELECT token_hash,user_id,expires_at,revoked_at FROM native_auth_sessions").fetchall(),
                before_sessions)

        self.now[0]+=61  # Synthetic time passes cooldown before re-login
        restarted=self.serve(self.restricted)
        self.assertEqual(wsgi(restarted,"GET","/health")[0],"200 OK")
        second=self.complete_login(restarted)
        self.assertEqual(second["user_id"],original["user_id"])
        self.assertEqual(second["role"],"passenger")
        self.assertNotEqual(second["access_token"],original["access_token"])
        with psycopg.connect(self.privileged) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM native_auth_users WHERE channel='phone' AND destination=%s",
                (CI_PHONE,)).fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM native_auth_users").fetchone()[0],1)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM native_auth_sessions WHERE user_id=%s",
                (original["user_id"],)).fetchone()[0],2)
            self.assertEqual(db.execute(
                "SELECT token_hash FROM native_auth_sessions WHERE token_hash=%s",
                (original_hash,)).fetchone()[0],original_hash)
            self.assertEqual(db.execute("SELECT user_id,role FROM native_auth_roles").fetchall(),
                             before_roles)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM native_auth_roles WHERE role='admin'").fetchone()[0],0)
        with psycopg.connect(self.restricted) as runtime:
            for statement in ("UPDATE native_auth_roles SET role='admin'",
                              "INSERT INTO native_auth_roles(user_id,role) VALUES ('fake','admin')",
                              "CREATE TABLE illicit_runtime_migration(id int)"):
                with self.subTest(statement=statement),self.assertRaises(InsufficientPrivilege):
                    with runtime.transaction():
                        runtime.execute(statement)


if __name__=="__main__":
    unittest.main()
