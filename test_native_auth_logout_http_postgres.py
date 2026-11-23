"""Disposable PostgreSQL 18 integration test: Bearer-only current-device logout.

No external connections, real SMS, Render or production. Tests create and
destroy nothing outside the ephemeral GitHub Actions postgres service.
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

from pd_native_auth_schema_migration import initialize_database
from pd_native_phone_grants_ci import install_synthetic_phone_auth_grants
from pd_native_auth_logout_schema_ci import install_synthetic_logout_function
from pd_native_auth_postgres_http import make_app
from pd_native_auth_postgres_session_lifecycle import inspect_session

DATABASE="pd_logout_ci"
USERNAME="pd_ci_logout_service"
PASSWORD="ci-logout-synthetic"
NOW=200000
A="synthetic-device-A-"+"a"*48
B="synthetic-device-B-"+"b"*48
OTHER="synthetic-other-device-"+"o"*48
EXPIRED="synthetic-expired-device-"+"e"*48

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def call(app, token=None, *, method="POST", path="/native-auth/logout",
         payload=None, scheme="Bearer"):
    body=json.dumps(payload or {}).encode("utf-8")
    environ={"REQUEST_METHOD":method,"PATH_INFO":path,
             "CONTENT_TYPE":"application/json","CONTENT_LENGTH":str(len(body)),
             "wsgi.input":io.BytesIO(body)}
    if token is not None:
        environ["HTTP_AUTHORIZATION"]=scheme+" "+token
    result=[]
    raw=b"".join(app(environ,lambda status,headers:result.append(status)))
    return result[0],json.loads(raw)


class LogoutHttpPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=os.environ.get("PD_CI_POSTGRES_URL","")
        p=urlsplit(root)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY")!="YES"
            or p.scheme!="postgresql" or p.hostname!="127.0.0.1"
            or p.port!=5432 or p.path!="/pd_schema_ci"
            or p.username!="pd_ci"):
            raise RuntimeError("refusing_non_synthetic_database")
        cls.privileged=root.replace("/pd_schema_ci","/"+DATABASE)
        cls.runtime=f"postgresql://{USERNAME}:{PASSWORD}@127.0.0.1:5432/{DATABASE}"
        with psycopg.connect(root,autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {}").format(
                sql.Identifier(USERNAME),sql.Literal(PASSWORD)))
        initialize_database(cls.privileged)
        with psycopg.connect(cls.privileged) as db:
            db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            install_synthetic_phone_auth_grants(db)
            install_synthetic_logout_function(db)
            db.execute(sql.SQL("GRANT pd_ci_phone_auth TO {}").format(sql.Identifier(USERNAME)))
            db.execute("""INSERT INTO native_auth_users(id,channel,destination,created_at)
                VALUES ('pilot','phone','+37060000001',1),
                       ('other','phone','+37060000002',1)""")
            db.execute("""INSERT INTO native_auth_roles(user_id,role)
                VALUES ('pilot','pilot'),('other','passenger')""")
            for token,uid,expires in (
                (A,"pilot",NOW+500),
                (B,"pilot",NOW+500),
                (OTHER,"other",NOW+500),
                (EXPIRED,"pilot",NOW),
            ):
                db.execute("""INSERT INTO native_auth_sessions
                    (token_hash,user_id,created_at,expires_at)
                    VALUES (%s,%s,100,%s)""",(digest(token),uid,expires))
        # Real SMS flag stays false. Logout must not require SMS.
        cls.app=make_app(cls.runtime,live=False,clock=lambda:NOW)
        cls.events=[]

    def setUp(self):
        self.db=psycopg.connect(self.privileged)
        self.db.execute("SELECT 1")  # outer rollback-only transaction
        # The HTTP endpoint connects separately. Reset only synthetic A state,
        # without committing any changes to production or real accounts.
        self.db.rollback()
        with psycopg.connect(self.privileged) as fresh:
            fresh.execute("""UPDATE native_auth_sessions SET revoked_at=NULL
                           WHERE token_hash=ANY(%s)""",
                          ([digest(A),digest(B),digest(OTHER)],))
        self.db.execute("SELECT 1")

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def sessions(self):
        return dict(self.db.execute(
            "SELECT token_hash,revoked_at FROM native_auth_sessions").fetchall())

    def test_logout_only_presented_token_preserves_other_devices(self):
        status,body=call(type(self).app,A,payload={"user_id":"other","role":"admin",
                                                    "token_hash":digest(OTHER)})
        self.assertEqual(status,"200 OK")
        self.assertEqual(body,{"status":"logged_out"})
        self.db.rollback()
        self.assertEqual(self.sessions()[digest(A)],NOW)
        self.assertIsNone(self.sessions()[digest(B)])
        self.assertIsNone(self.sessions()[digest(OTHER)])
        self.assertEqual(inspect_session(self.db,B,now=NOW),("pilot","pilot"))
        self.assertEqual(inspect_session(self.db,OTHER,now=NOW),
                         ("other","passenger"))
        self.assertIsNone(inspect_session(self.db,A,now=NOW))

    def test_repeat_logout_is_denied_without_side_effect(self):
        self.assertEqual(call(type(self).app,A)[0],"200 OK")
        self.assertEqual(call(type(self).app,A),
                         ("401 Unauthorized",{"error":"invalid_session"}))
        self.db.rollback()
        self.assertIsNone(self.sessions()[digest(B)])

    def test_missing_invalid_or_expired_bearer_cannot_logout(self):
        attempts=(
            {"token":None},
            {"token":A,"scheme":"Basic"},
            {"token":"invalid"},
            {"token":"x"*70},
            {"token":EXPIRED},
            {"token":A,"method":"GET"},
        )
        for args in attempts:
            with self.subTest(args=list(args)):
                status,_=call(type(self).app,**args)
                self.assertNotEqual(status,"200 OK")
        self.db.rollback()
        self.assertIsNone(self.sessions()[digest(A)])
        self.assertIsNone(self.sessions()[digest(B)])

    def test_no_direct_session_updates_by_http_db_user(self):
        with psycopg.connect(self.runtime) as client:
            with self.assertRaises(InsufficientPrivilege):
                with client.transaction():
                    client.execute(
                        "UPDATE native_auth_sessions SET revoked_at=0")
            with self.assertRaises(InsufficientPrivilege):
                with client.transaction():
                    client.execute("SELECT token_hash FROM native_auth_sessions")

    def test_forbidden_client_body_cannot_override_bearer(self):
        status,_=call(type(self).app,B,payload={
            "access_token":A,"revoke_token":A,"user_id":"other","all_devices":True
        })
        self.assertEqual(status,"200 OK")
        self.db.rollback()
        self.assertIsNone(self.sessions()[digest(A)])
        self.assertEqual(self.sessions()[digest(B)],NOW)
        self.assertIsNone(self.sessions()[digest(OTHER)])


if __name__=="__main__":
    unittest.main()
