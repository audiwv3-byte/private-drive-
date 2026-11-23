"""End-to-end isolated native-auth session and three-cabin sync via real PG18.

Uses ONLY disposable localhost PostgreSQL and SQLite, never Render or SMS.
Native bearer sessions are verified against the same restricted SQL function
used by /native-auth/session. No separate role token or manual login.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
import uuid

import psycopg
from psycopg import sql

from pd_native_auth_schema_migration import initialize_database
from pd_native_auth_role_migration import migrate_roles_on_connection
from pd_native_phone_grants_ci import install_synthetic_phone_auth_grants
from pd_native_auth_logout_schema_ci import install_synthetic_logout_function
from pd_demo_server import ApiServer, DemoStore
from pd_native_session_bridge import NativePostgresPrincipalLookup

DB="pd_native_sync_ci"
LOGIN="pd_native_sync_ci_app"
PW="synthetic-only-native-sync"
NOW=250000
IDENTITIES = ("passenger","pilot","dispatcher","other","admin","pilot_dispatcher")
TOKENS = {role: ("native-ci-session-"+role+"-"+"t"*50)
          for role in IDENTITIES}


def tokenhash(role):
    return hashlib.sha256(TOKENS[role].encode()).hexdigest()


class NativePostgresSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=os.environ.get("PD_CI_POSTGRES_URL","")
        u=urlsplit(base)
        if (os.environ.get("PD_CI_FAKE_DB_ONLY")!="YES" or
            u.scheme!="postgresql" or u.hostname!="127.0.0.1" or
            u.port!=5432 or u.username!="pd_ci" or u.path!="/pd_schema_ci"):
            raise RuntimeError("non_synthetic_postgres_refused")
        cls.owner=base.replace("/pd_schema_ci","/"+DB)
        cls.runtime=f"postgresql://{LOGIN}:{PW}@127.0.0.1:5432/{DB}"
        with psycopg.connect(base,autocommit=True) as pg:
            pg.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            pg.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT NOCREATEDB NOCREATEROLE PASSWORD {}")
                       .format(sql.Identifier(LOGIN),sql.Literal(PW)))
        initialize_database(cls.owner)
        with psycopg.connect(cls.owner) as pg:
            pg.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            install_synthetic_phone_auth_grants(pg)
            install_synthetic_logout_function(pg)
            migrate_roles_on_connection(pg)
            pg.execute(sql.SQL("GRANT pd_ci_phone_auth TO {}")
                       .format(sql.Identifier(LOGIN)))
            for i,role in enumerate(IDENTITIES):
                account_role="passenger" if role=="other" else role
                uid=role+"_test"
                pg.execute("""INSERT INTO native_auth_users
                    (id,channel,destination,created_at) VALUES
                    (%s,'phone',%s,%s)""",
                    (uid,f"+3706100{i:04d}",NOW-100))
                pg.execute("""INSERT INTO native_auth_roles(user_id,role)
                    VALUES (%s,%s)""",(uid,account_role))
                pg.execute("""INSERT INTO native_auth_sessions
                    (token_hash,user_id,created_at,expires_at)
                    VALUES (%s,%s,%s,%s)""",
                    (tokenhash(role),uid,NOW-100,NOW+1000))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=DemoStore(str(Path(self.temp.name)/"native.sqlite"))
        self.lookup=NativePostgresPrincipalLookup(self.runtime,clock=lambda:NOW)
        self.server=ApiServer(("127.0.0.1",0),self.store,{},
                              native_principal_lookup=self.lookup)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.temp.cleanup()

    def req(self, method,path,identity="passenger",cabin=None,body=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=4)
        headers={"Authorization":"Bearer "+TOKENS[identity]}
        if cabin is not None:
            headers["X-PD-Cabin"]=cabin
        raw=None if body is None else json.dumps(body).encode()
        if raw is not None:
            headers["Content-Type"]="application/json"
        conn.request(method,path,body=raw,headers=headers)
        res=conn.getresponse()
        output=res.status,json.loads(res.read())
        conn.close()
        return output

    def test_01_native_roles_and_explicit_cabin_claims(self):
        self.assertEqual(self.req("GET","/v1/me","passenger","passenger")[1]["role"],"passenger")
        self.assertEqual(self.req("GET","/v1/me","pilot","pilot")[1]["role"],"pilot")
        self.assertEqual(self.req("GET","/v1/me","dispatcher","dispatcher")[1]["role"],"dispatcher")
        self.assertEqual(self.req("GET","/v1/me","pilot_dispatcher","pilot")[0],200)
        self.assertEqual(self.req("GET","/v1/me","pilot_dispatcher","dispatcher")[0],200)
        self.assertEqual(self.req("GET","/v1/me","admin","dispatcher")[0],200)
        self.assertEqual(self.req("GET","/v1/me","passenger","dispatcher")[0],403)
        self.assertEqual(self.req("GET","/v1/me","pilot","dispatcher")[0],403)
        self.assertEqual(self.req("GET","/v1/me","dispatcher","pilot")[0],403)
        self.assertEqual(self.req("GET","/v1/me","pilot",None)[0],401)
        self.assertEqual(self.req("GET","/v1/me","pilot","admin")[0],401)

    def test_02_native_order_assignment_gps_chat_and_restart(self):
        # A connected native pilot is the only assignable candidate.
        self.assertEqual(self.req("GET","/v1/pilots","dispatcher","dispatcher")[1]["pilots"],[])
        self.assertEqual(self.req("GET","/v1/me","pilot","pilot")[0],200)
        self.assertEqual(self.req("GET","/v1/pilots","dispatcher","dispatcher")[1]["pilots"],["pilot_test"])
        status,created=self.req("POST","/v1/trips","passenger","passenger",
            {"from":"Synthetic Vilnius","to":"Synthetic Kaunas"})
        self.assertEqual(status,201)
        tid=created["trip"]["id"]
        assign=f"/v1/trips/{tid}/assign"
        self.assertEqual(self.req("POST",assign,"passenger","passenger",
            {"pilot":"pilot_test","version":1})[0],403)
        self.assertEqual(self.req("POST",assign,"dispatcher","dispatcher",
            {"pilot":"pilot_test","version":1})[0],200)
        self.assertEqual(self.req("GET","/v1/current","pilot","pilot")[1]["trip"]["id"],tid)
        gps=f"/v1/trips/{tid}/gps"
        self.assertEqual(self.req("GET",gps,"dispatcher","dispatcher")[1]["gps"],
                         {"available":False})
        self.assertEqual(self.req("POST",gps,"pilot","pilot",
            {"enabled":True,"latitude":54.6872,"longitude":25.2797})[0],200)
        self.assertTrue(self.req("GET",gps,"dispatcher","dispatcher")[1]["gps"]["available"])
        self.assertEqual(self.req("GET",gps,"other","passenger")[0],404)
        chat=f"/v1/trips/{tid}/messages"
        client_id=uuid.uuid4().hex
        payload={"text":"На месте","client_id":client_id}
        self.assertEqual(self.req("POST",chat,"pilot","pilot",payload)[0],201)
        self.assertEqual(self.req("POST",chat,"pilot","pilot",payload)[0],201)
        self.assertEqual(len(self.req("GET",chat,"passenger","passenger")[1]["messages"]),1)
        self.assertEqual(self.req("GET",chat,"other","passenger")[0],404)
        self.assertEqual(self.req("POST",chat,"dispatcher","dispatcher",
            {"text":"Проверено","client_id":uuid.uuid4().hex})[0],201)
        self.assertEqual(len(self.req("GET",chat,"pilot","pilot")[1]["messages"]),2)
        self.store.close()
        self.store=DemoStore(str(Path(self.temp.name)/"native.sqlite"))
        self.server.store=self.store
        self.assertEqual(len(self.req("GET",chat,"passenger","passenger")[1]["messages"]),2)

    def test_03_role_change_revocation_and_expiration_immediately_enforced(self):
        self.assertEqual(self.req("GET","/v1/me","pilot","pilot")[0],200)
        with psycopg.connect(self.owner) as pg:
            pg.execute("""UPDATE native_auth_roles SET role='passenger'
                         WHERE user_id='pilot_test'""")
        try:
            self.assertEqual(self.req("GET","/v1/me","pilot","pilot")[0],403)
        finally:
            with psycopg.connect(self.owner) as pg:
                pg.execute("""UPDATE native_auth_roles SET role='pilot'
                             WHERE user_id='pilot_test'""")
        with psycopg.connect(self.owner) as pg:
            pg.execute("""UPDATE native_auth_sessions SET revoked_at=%s
                WHERE token_hash=%s""",(NOW,tokenhash("other")))
        self.assertEqual(self.req("GET","/v1/me","other","passenger")[0],401)
        with psycopg.connect(self.owner) as pg:
            pg.execute("""UPDATE native_auth_sessions SET expires_at=%s
                WHERE token_hash=%s""",(NOW,tokenhash("other")))
        self.assertEqual(self.req("GET","/v1/me","other","passenger")[0],401)


if __name__=="__main__":
    unittest.main()
