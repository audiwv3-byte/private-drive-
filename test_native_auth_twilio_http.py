"""Offline-only integration tests. Never transmit SMS or use real credentials."""
import io
import json
import sqlite3
import unittest

from pd_native_auth_sessions import authenticate_session
from pd_native_auth_twilio_http import make_twilio_native_auth_app
from pd_twilio_verify import VerifyError


class TwilioHttpTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.now = 1000
        self.sent = []
        self.checked = []
        self.app = make_twilio_native_auth_app(
            self.db,
            start_sms=lambda phone: self.sent.append(phone),
            check_sms=lambda phone, code: self.checked.append((phone, code)) or code == "123456",
            clock=lambda: self.now,
        )

    def request(self, route, payload, ip="127.0.0.1"):
        raw = json.dumps(payload).encode()
        result = []
        body = b"".join(self.app({
            "REQUEST_METHOD": "POST", "PATH_INFO": route,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
            "REMOTE_ADDR": ip,
        }, lambda status, headers: result.append(status)))
        return int(result[0][:3]), json.loads(body)

    def begin(self, phone="+37060000000", ip="127.0.0.1"):
        return self.request("/native-auth/request-code",
                            {"channel": "phone", "destination": phone}, ip)

    def confirm(self, cid, code="123456"):
        return self.request("/native-auth/verify-code",
                            {"challenge_id": cid, "code": code})

    def test_only_phone_and_passenger_session(self):
        status, data = self.begin()
        self.assertEqual(status, 202)
        self.assertNotIn("code", data)
        self.assertEqual(self.sent, ["+37060000000"])
        status, session = self.confirm(data["challenge_id"])
        self.assertEqual(status, 200)
        self.assertEqual(session["role"], "passenger")
        self.assertEqual(session["token_type"], "Bearer")
        self.assertEqual(authenticate_session(self.db, session["access_token"], now=self.now)["destination"], "+37060000000")
        self.assertEqual(self.confirm(data["challenge_id"])[0], 401)
        self.assertEqual(len(self.checked), 1)
        # The adapter never stores a locally generated SMS/OTP code.
        self.assertNotIn("123456", str(self.db.execute(
            "SELECT * FROM native_twilio_challenges").fetchall()))

    def test_reuses_existing_passenger_account_no_pilot_escalation(self):
        _, first = self.begin()
        _, first_session = self.confirm(first["challenge_id"])
        self.now += 61
        _, second = self.begin()
        _, second_session = self.confirm(second["challenge_id"])
        self.assertEqual(first_session["user_id"], second_session["user_id"])
        self.assertEqual(second_session["role"], "passenger")

    def test_denies_wrong_or_expired_sms_and_locks_out_after_five(self):
        _, data = self.begin()
        for _ in range(5):
            self.assertEqual(self.confirm(data["challenge_id"], "000000")[0], 401)
        self.assertEqual(self.confirm(data["challenge_id"])[0], 401)
        self.assertEqual(len(self.checked), 5)
        self.now += 301
        self.assertEqual(self.confirm(data["challenge_id"])[0], 401)

    def test_rate_limits_phone_even_across_app_restarts(self):
        self.assertEqual(self.begin()[0], 202)
        other_app = make_twilio_native_auth_app(
            self.db, start_sms=lambda phone: self.sent.append(phone),
            check_sms=lambda phone, code: False, clock=lambda: self.now)
        self.assertEqual(self.begin(ip="different-ip")[0], 429)
        raw = json.dumps({"channel": "phone", "destination": "+37060000000"}).encode()
        statuses = []
        other_app({"REQUEST_METHOD": "POST", "PATH_INFO": "/native-auth/request-code",
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
                   "wsgi.input": io.BytesIO(raw), "REMOTE_ADDR": "second-ip"},
                  lambda status, headers: statuses.append(status))
        self.assertEqual(statuses[0][:3], "429")
        self.assertEqual(len(self.sent), 1)

    def test_invalid_targets_do_not_trigger_provider(self):
        self.assertEqual(self.request("/native-auth/request-code",
            {"channel": "email", "destination": "a@example.com"})[0], 400)
        self.assertEqual(self.begin("not-a-phone")[0], 400)
        self.assertEqual(self.sent, [])

    def test_provider_failure_is_redacted(self):
        def disabled(phone):
            raise VerifyError("Twilio Verify sending is disabled")
        app = make_twilio_native_auth_app(
            self.db, start_sms=disabled, check_sms=lambda *a: False,
            clock=lambda: self.now)
        raw = json.dumps({"channel": "phone", "destination": "+37060000000"}).encode()
        out = []
        data = b"".join(app({
            "REQUEST_METHOD": "POST", "PATH_INFO": "/native-auth/request-code",
            "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": io.BytesIO(raw), "REMOTE_ADDR": "127.0.0.1",
        }, lambda status, headers: out.append(status)))
        self.assertEqual(out[0][:3], "503")
        self.assertNotIn(b"Twilio", data)
        self.assertNotIn(b"code", data)


if __name__ == "__main__":
    unittest.main()
