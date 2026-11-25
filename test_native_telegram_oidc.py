import io
import json
import os
import re
import secrets
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg

from pd_native_auth_postgres_http import make_app
from pd_native_telegram_oidc import TelegramOidc, verified_phone_claim

TEST_PHONE = "+12025550110"


class TelegramClaimsTests(unittest.TestCase):
    def test_telegram_phone_is_required_and_normalized(self):
        self.assertEqual(verified_phone_claim({"sub": "account", "phone_number": TEST_PHONE[1:]}),
                         ("account", TEST_PHONE))
        for claims in (
            {"sub": "account"},
            {"sub": "account", "phone_number": TEST_PHONE, "phone_number_verified": False},
            {"sub": "", "phone_number": TEST_PHONE},
        ):
            with self.subTest(claims=claims), self.assertRaises(ValueError):
                verified_phone_claim(claims)

    def test_authorization_requests_phone_with_pkce(self):
        oidc = TelegramOidc("12345", "synthetic-secret",
                            "https://example.test/native-auth/telegram/callback")
        url = urlsplit(oidc.authorization_url("state", "verifier"))
        query = parse_qs(url.query)
        self.assertEqual(url.hostname, "oauth.telegram.org")
        self.assertEqual(query["scope"], ["openid profile phone"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("client_secret", query)
        self.assertNotEqual(query["code_challenge"], ["verifier"])


class FakeTelegram(TelegramOidc):
    def verified_identity(self, code, verifier):
        if code != "provider-auth-code" or len(verifier) != 43:
            raise ValueError("Invalid provider response")
        return "telegram-test-account", TEST_PHONE


@unittest.skipUnless(os.environ.get("PD_IDENTITY_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class MobileSignInTests(unittest.TestCase):
    def setUp(self):
        db = os.environ["PD_IDENTITY_TEST_DATABASE_URL"]
        self.sent = []
        self.now = 1800000000
        oidc = FakeTelegram("12345", "synthetic-secret",
                            "https://example.test/native-auth/telegram/callback")
        self.app = make_app(
            db, clock=lambda: self.now, telegram_oidc=oidc, live=True,
            sms_test_phone=TEST_PHONE,
            start_sms=lambda phone, **_: self.sent.append(phone),
            check_sms=lambda phone, code, **_: phone == TEST_PHONE and code == "123456")
        with psycopg.connect(db) as conn:
            conn.execute("""TRUNCATE native_telegram_attempts, native_telegram_links,
                native_twilio_challenges, native_auth_users CASCADE""")

    def request(self, route, payload=None, query=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        env = {"REQUEST_METHOD": "POST" if payload is not None else "GET",
               "PATH_INFO": "/native-auth/" + route, "QUERY_STRING": urlencode(query or {}),
               "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
               "wsgi.input": io.BytesIO(body)}
        statuses = []
        result = b"".join(self.app(env, lambda status, headers: statuses.append(status)))
        return int(statuses[0][:3]), result.decode() if query else json.loads(result)

    def begin_telegram(self):
        secret = secrets.token_urlsafe(32)
        status, started = self.request("telegram/start", {"app_secret": secret})
        self.assertEqual(status, 201)
        return secret, started["state"]

    def test_automatic_telegram_finishes_only_in_initiating_app(self):
        secret = secrets.token_urlsafe(32)
        status, started = self.request("telegram/start", {
            "app_secret": secret, "mode": "automatic",
        })
        self.assertEqual(status, 201)
        self.assertTrue(started["automatic"])
        payload = {"state": started["state"], "app_secret": secret}
        self.assertEqual(self.request("telegram/finish", payload), (202, {"pending": True}))
        query = {"state": started["state"], "code": "provider-auth-code"}
        status, page = self.request("telegram/callback", query=query)
        self.assertEqual(status, 200)
        self.assertNotIn("Код входа", page)
        self.assertEqual(self.request("telegram/finish", {
            **payload, "app_secret": secrets.token_urlsafe(32),
        })[0], 401)
        self.assertEqual(self.request("telegram/finish", payload)[0], 200)
        self.assertEqual(self.request("telegram/finish", payload)[0], 401)

    def test_sms_and_telegram_use_one_account_and_callback_is_single_use(self):
        status, result = self.request("request-code",
            {"channel": "phone", "destination": "+12025550111"})
        self.assertEqual((status, result["error"]), (403, "sms_number_not_enabled"))
        self.assertEqual(self.sent, [])
        status, result = self.request("request-code", {"channel": "phone", "destination": TEST_PHONE})
        self.assertEqual(status, 202)
        self.assertEqual(self.sent, [TEST_PHONE])
        status, sms_session = self.request("verify-code",
            {"challenge_id": result["challenge_id"], "code": "123456"})
        self.assertEqual(status, 200)
        secret, state = self.begin_telegram()
        query = {"state": state, "code": "provider-auth-code"}
        status, page = self.request("telegram/callback", query=query)
        self.assertEqual(status, 200)
        code = re.search(r"Код входа: ([0-9]{8})", page).group(1)
        self.assertEqual(self.request("telegram/callback", query=query)[0], 400)
        result = {"state": state, "code": code, "app_secret": secrets.token_urlsafe(32)}
        self.assertEqual(self.request("telegram/finish", result)[0], 401)
        result["app_secret"] = secret
        status, telegram_session = self.request("telegram/finish", result)
        self.assertEqual(status, 200)
        self.assertEqual(telegram_session["user_id"], sms_session["user_id"])
        self.assertNotEqual(telegram_session["access_token"], sms_session["access_token"])
        self.assertEqual(self.request("telegram/finish", result)[0], 401)
