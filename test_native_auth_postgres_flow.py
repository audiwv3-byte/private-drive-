import io
import json
import os
import re
import unittest
from urllib.parse import urlencode

import psycopg

from pd_native_auth_postgres_http import SESSION_TTL, make_app
from pd_native_telegram_oidc import TelegramOidc


class TestTelegram(TelegramOidc):
    def verified_identity(self, code, verifier):
        if code != "provider-approved" or not verifier:
            raise ValueError("Invalid test authorization")
        return "telegram-test-subject", "+37060000123"


@unittest.skipUnless(os.environ.get("PD_AUTH_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class NativeAuthFlowTests(unittest.TestCase):
    def setUp(self):
        self.now = 1800000000
        self.db = os.environ["PD_AUTH_TEST_DATABASE_URL"]
        self.phone = "+37060000123"
        self.oidc = TestTelegram("12345", "test-only-secret",
                                 "https://example.test/native-auth/telegram/callback")
        self.app = make_app(
            self.db, live=True, sms_test_phone=self.phone, telegram_oidc=self.oidc,
            start_sms=lambda *args, **kwargs: None,
            check_sms=lambda phone, code, **kwargs: phone == self.phone and code == "123456",
            clock=lambda: self.now,
        )
        with psycopg.connect(self.db) as conn:
            conn.execute("""TRUNCATE native_telegram_attempts,native_telegram_links,
                native_auth_sessions,native_auth_roles,native_auth_users,native_twilio_challenges CASCADE""")

    def request(self, path, payload=None, *, token=None, query=None):
        raw = json.dumps(payload or {}).encode()
        environ = {
            "PATH_INFO": path, "REQUEST_METHOD": "GET" if query is not None else "POST",
            "QUERY_STRING": urlencode(query or {}), "wsgi.input": io.BytesIO(raw),
            "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
        }
        if token is not None:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        observed = []
        body = b"".join(self.app(environ, lambda status, headers: observed.append(status)))
        return int(observed[0][:3]), body.decode() if query is not None else json.loads(body)

    def sms_session(self):
        status, challenge = self.request("/native-auth/request-code", {
            "channel": "phone", "destination": self.phone,
        })
        self.assertEqual(status, 202)
        status, session = self.request("/native-auth/verify-code", {
            "challenge_id": challenge["challenge_id"], "code": "123456",
        })
        self.assertEqual(status, 200)
        return session

    def test_sms_and_telegram_share_account_and_each_session_can_be_revoked(self):
        sms = self.sms_session()
        proof = "a" * 43
        status, start = self.request("/native-auth/telegram/start", {
            "app_secret": proof, "language": "EN",
        })
        self.assertEqual(status, 201)
        query = {"state": start["state"], "code": "provider-approved"}
        status, page = self.request("/native-auth/telegram/callback", query=query)
        self.assertEqual(status, 200)
        self.assertIn('<html lang="en">', page)
        code = re.search(r"Sign-in code: ([0-9]{8})", page).group(1)
        finish = {"app_secret": proof, "state": start["state"], "code": code}
        self.assertEqual(self.request("/native-auth/telegram/finish", {
            **finish, "app_secret": "b" * 43,
        })[0], 401)
        status, telegram = self.request("/native-auth/telegram/finish", finish)
        self.assertEqual(status, 200)
        self.assertEqual(sms["user_id"], telegram["user_id"])
        self.assertNotEqual(sms["access_token"], telegram["access_token"])
        self.assertEqual(self.request("/native-auth/telegram/finish", finish)[0], 401)

        self.now += 100
        token = telegram["access_token"]
        status, resumed = self.request("/native-auth/session", token=token)
        self.assertEqual((status, resumed["user_id"]), (200, sms["user_id"]))
        self.assertEqual(resumed["expires_in"], SESSION_TTL - 100)
        self.assertNotIn("access_token", resumed)
        self.assertEqual(self.request("/native-auth/sign-out", token=token)[0], 200)
        self.assertEqual(self.request("/native-auth/session", token=token)[0], 401)
        self.assertEqual(self.request("/native-auth/session", token=sms["access_token"])[0], 200)
        self.now += SESSION_TTL
        self.assertEqual(self.request("/native-auth/session", token=sms["access_token"])[0], 401)
