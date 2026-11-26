import hashlib
import json
import os
import unittest
from unittest.mock import patch

import psycopg
from pd_native_auth_postgres_http import session_request

DSN = os.environ.get("PD_AUTH_TEST_DATABASE_URL")
NOW = 1800000000
FLAGS = {"PD_NATIVE_SESSION_FUNCTIONS": "1", "PD_DISPATCH_STAGING_ONLY": "1", "PD_PAYMENT_MODE": "disabled"}


class SessionSecurity(unittest.TestCase):
    def setUp(self):
        if not DSN:
            self.fail("Isolated test database required")
        self.conn = psycopg.connect(DSN, autocommit=True)
        self.addCleanup(self.conn.close)
        self.assertEqual(self.conn.execute("SELECT current_database()").fetchone()[0], "private_drive_test")
        self.conn.execute("BEGIN")
        self.addCleanup(lambda: self.conn.execute("ROLLBACK"))
        self.conn.execute("CREATE ROLE pd_qa_session_runtime NOLOGIN")
        self.conn.execute("INSERT INTO native_auth_users(id,channel,destination,created_at) VALUES ('qa-security','phone','qa-security',0)")
        self.conn.execute("INSERT INTO native_auth_roles VALUES ('qa-security','pilot')")
        for char, created, expires, revoked in [('a',NOW-1,NOW+10,None),('b',NOW-1,NOW,None),('c',NOW+1,NOW+10,None),('d',NOW-1,NOW+10,NOW-1),('e',NOW-1,NOW+10,None)]:
            self.conn.execute("INSERT INTO native_auth_sessions VALUES (%s,'qa-security',%s,%s,%s)", (self.digest(char),created,expires,revoked))

    @staticmethod
    def digest(char):
        return hashlib.sha256((char*48).encode()).hexdigest()

    def restricted(self):
        self.conn.execute("GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint), public.pd_revoke_current_session(text,bigint) TO pd_qa_session_runtime")
        self.conn.execute("SET LOCAL ROLE pd_qa_session_runtime")

    def denied(self, query):
        self.conn.execute("SAVEPOINT denied")
        try:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.conn.execute(query)
        finally:
            self.conn.execute("ROLLBACK TO SAVEPOINT denied")

    def validate(self, char):
        return self.conn.execute("SELECT * FROM public.pd_validate_native_session(%s,%s)", (self.digest(char),NOW)).fetchall()

    def test_public_execution_denied(self):
        self.conn.execute("SET LOCAL ROLE pd_qa_session_runtime")
        self.denied("SELECT * FROM public.pd_validate_native_session(repeat('a',64),0)")
        self.denied("SELECT public.pd_revoke_current_session(repeat('a',64),0)")

    def test_restricted_role_cannot_read_or_write_tables(self):
        self.restricted()
        self.denied("SELECT * FROM public.native_auth_sessions")
        self.denied("UPDATE public.native_auth_sessions SET revoked_at=0")
        self.denied("SELECT * FROM public.native_auth_users")
        self.assertEqual(self.validate('a'), [('qa-security','pilot',NOW+10)])

    def test_invalid_session_boundaries(self):
        self.restricted()
        for char in 'bcdf':
            with self.subTest(char=char):
                self.assertEqual(self.validate(char), [])

    def test_revoke_only_presented_session(self):
        self.restricted()
        for expected in (True,False):
            self.assertEqual(self.conn.execute("SELECT public.pd_revoke_current_session(%s,%s)", (self.digest('a'),NOW)).fetchone()[0], expected)
        self.assertEqual(self.validate('a'), [])
        self.assertEqual(len(self.validate('e')), 1)

    def test_unsafe_flags_rejected(self):
        for key, value in [('PD_DISPATCH_STAGING_ONLY','0'),('PD_PAYMENT_MODE','live')]:
            with self.subTest(key=key), patch.dict(os.environ, {**FLAGS,key:value}):
                for route in ('/native-auth/session','/native-auth/sign-out'):
                    status = []
                    body = session_request(DSN, {"HTTP_AUTHORIZATION":"Bearer "+"a"*48}, lambda s,h: status.append(s), route, NOW)
                    self.assertEqual(status, ["503 Service Unavailable"])
                    self.assertEqual(json.loads(b"".join(body))["error"], "session_functions_disabled")
