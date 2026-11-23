"""Real PostgreSQL 18 concurrent native-auth WSGI exercises, synthetic-only.

Database is a separate disposable GitHub Actions container. The SMS provider
is replaced with an in-memory stub. Tokens are checked only by their hashes.
No remote DB, provider, Render, or production access.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
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

DB = "pd_concurrent_ci"
LOGIN = "pd_concurrent_auth_login"
PASSWORD = "synthetic-concurrency-only"
NOW = 250000
PHONES = {
    "race_request": "+37060000101",
    "one_challenge": "+37060000102",
    "two_challenges": "+37060000103",
    "new_account": "+37060000104",
}


def wsgi(app, endpoint, data):
    raw = json.dumps(data).encode("utf-8")
    environ = {
        "REQUEST_METHOD": "POST", "PATH_INFO": endpoint,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
    }
    status = []
    response = b"".join(app(environ, lambda s, h: status.append(s)))
    return status[0], json.loads(response)


def parallel(count, action):
    gate = Barrier(count)
    def invoke(i):
        gate.wait(timeout=10)
        return action(i)
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = [executor.submit(invoke, i) for i in range(count)]
        return [f.result(timeout=25) for f in futures]


class ConcurrentNativeAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("PD_CI_POSTGRES_URL", "")
        u = urlsplit(root)
        if not (os.environ.get("PD_CI_FAKE_DB_ONLY") == "YES"
                and u.scheme == "postgresql" and u.hostname == "127.0.0.1"
                and u.port == 5432 and u.path == "/pd_schema_ci"
                and u.username == "pd_ci"):
            raise RuntimeError("not_disposable_ci_postgres")

        cls.owner_dsn = root.replace("/pd_schema_ci", "/" + DB)
        cls.runtime_dsn = (f"postgresql://{LOGIN}:{PASSWORD}"
                           f"@127.0.0.1:5432/{DB}")
        with psycopg.connect(root, autocommit=True) as root_db:
            root_db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            root_db.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT "
                "NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(LOGIN), sql.Literal(PASSWORD)))

        initialize_database(cls.owner_dsn)
        with psycopg.connect(cls.owner_dsn) as owner:
            owner.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            install_synthetic_phone_auth_grants(owner)
            owner.execute(sql.SQL("GRANT pd_ci_phone_auth TO {}").format(
                sql.Identifier(LOGIN)))
            owner.execute("""INSERT INTO native_auth_users
                (id,channel,destination,created_at) VALUES
                ('ci-pilot','phone',%s,1),
                ('ci-admin','phone','+37060000999',1)""",
                (PHONES["two_challenges"],))
            owner.execute("""INSERT INTO native_auth_roles(user_id,role)
                VALUES ('ci-pilot','pilot'),('ci-admin','admin')""")
        cls.sms_calls = []
        cls.sms_lock = Lock()

        def fake_start(phone, *, env):
            with cls.sms_lock:
                cls.sms_calls.append(phone)

        def fake_verify(phone, code, *, env):
            return code == "123456"

        cls.app = make_app(
            cls.runtime_dsn, live=True,
            start_sms=fake_start, check_sms=fake_verify,
            clock=lambda: NOW,
        )

    @classmethod
    def tearDownClass(cls):
        pass

    def owner_query(self, statement, params=None):
        with psycopg.connect(self.owner_dsn) as db:
            return db.execute(statement, params).fetchall()

    def insert_challenge(self, challenge_id, phone):
        with psycopg.connect(self.owner_dsn) as db:
            db.execute("""INSERT INTO native_twilio_challenges
              (id,phone,created_at,expires_at,attempts)
              VALUES (%s,%s,%s,%s,0)""",
              (challenge_id, phone, NOW - 1, NOW + 300))

    def verify(self, challenge_id, **extra):
        return wsgi(self.app, "/native-auth/verify-code", {
            "challenge_id": challenge_id, "code": "123456", **extra
        })

    def test_01_concurrent_request_code_one_challenge_per_cooldown(self):
        phone = PHONES["race_request"]
        results = parallel(8, lambda i: wsgi(self.app,
            "/native-auth/request-code", {"channel":"phone","destination":phone}))
        self.assertEqual(sum(status == "202 Accepted" for status, _ in results), 1)
        self.assertEqual(sum(status == "429 Too Many Requests" for status, _ in results), 7)
        with self.sms_lock:
            self.assertEqual(self.sms_calls.count(phone), 1)
        self.assertEqual(self.owner_query(
            "SELECT count(*) FROM native_twilio_challenges WHERE phone=%s",
            (phone,))[0][0], 1)

    def test_02_parallel_reuse_of_exact_challenge_has_only_one_success(self):
        phone = PHONES["one_challenge"]
        self.insert_challenge("single-use-concurrent", phone)
        results = parallel(8, lambda _: self.verify("single-use-concurrent"))
        successes = [payload for status, payload in results if status == "200 OK"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(sum(status == "401 Unauthorized" for status, _ in results), 7)
        uid = successes[0]["user_id"]
        self.assertEqual(successes[0]["role"], "passenger")
        self.assertEqual(self.owner_query(
            "SELECT count(*) FROM native_auth_users WHERE channel='phone' AND destination=%s",
            (phone,))[0][0], 1)
        self.assertEqual(self.owner_query(
            "SELECT count(*) FROM native_auth_sessions WHERE user_id=%s",
            (uid,))[0][0], 1)
        self.assertEqual(self.owner_query(
            "SELECT consumed_at FROM native_twilio_challenges WHERE id='single-use-concurrent'"
        )[0][0], NOW)
        status, _ = self.verify("single-use-concurrent")
        self.assertEqual(status, "401 Unauthorized")

    def test_03_two_distinct_challenges_one_pilot_multiple_valid_sessions(self):
        phone = PHONES["two_challenges"]
        self.insert_challenge("pilot-concurrent-A", phone)
        self.insert_challenge("pilot-concurrent-B", phone)
        results = parallel(2, lambda i: self.verify(
            ("pilot-concurrent-A", "pilot-concurrent-B")[i], role="admin"))
        self.assertTrue(all(status == "200 OK" for status, _ in results))
        self.assertEqual({payload["user_id"] for _, payload in results}, {"ci-pilot"})
        self.assertEqual({payload["role"] for _, payload in results}, {"pilot"})
        tokens = [payload["access_token"] for _, payload in results]
        self.assertEqual(len(set(tokens)), 2)
        digests = {hashlib.sha256(t.encode()).hexdigest() for t in tokens}
        rows = self.owner_query("SELECT token_hash FROM native_auth_sessions WHERE user_id='ci-pilot'")
        self.assertEqual({x[0] for x in rows}, digests)
        self.assertEqual(self.owner_query(
            "SELECT count(*) FROM native_auth_users WHERE destination=%s",
            (phone,))[0][0], 1)
        self.assertEqual(self.owner_query(
            "SELECT role FROM native_auth_roles WHERE user_id='ci-pilot'")[0][0], "pilot")
        self.assertEqual(self.owner_query(
            "SELECT role FROM native_auth_roles WHERE user_id='ci-admin'")[0][0], "admin")
        self.assertEqual(self.owner_query(
            "SELECT count(*) FROM native_auth_roles WHERE role='admin'")[0][0], 1)

    def test_04_new_user_cannot_self_assign_admin_and_cannot_update_roles(self):
        self.insert_challenge("new-role-concurrent", PHONES["new_account"])
        status, payload = self.verify("new-role-concurrent", role="admin",
                                      user_id="ci-admin")
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["role"], "passenger")
        self.assertNotEqual(payload["user_id"], "ci-admin")
        self.assertEqual(self.owner_query(
            "SELECT count(*) FROM native_auth_roles WHERE role='admin'")[0][0], 1)
        with psycopg.connect(self.runtime_dsn) as db:
            with self.assertRaises(InsufficientPrivilege):
                with db.transaction():
                    db.execute("""UPDATE native_auth_roles
                       SET role='admin' WHERE user_id=%s""", (payload["user_id"],))


if __name__ == "__main__":
    unittest.main()
