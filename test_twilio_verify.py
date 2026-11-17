import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs

from pd_twilio_verify import VerifyError, start_verification, check_verification

ENV = {
    "TWILIO_ACCOUNT_SID": "AC" + "a" * 32,
    "TWILIO_AUTH_TOKEN": "fake-test-token-do-not-use",
    "TWILIO_VERIFY_SERVICE_SID": "VA" + "b" * 32,
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class TwilioVerifyTests(unittest.TestCase):
    def test_off_by_default_no_network(self):
        attempts = []
        with self.assertRaises(VerifyError):
            start_verification("+37060000000", env=ENV, transport=lambda *a, **kw: attempts.append(a))
        self.assertEqual(attempts, [])

    def test_start_uses_twilio_verify_not_local_otp(self):
        requests = []
        def fake(request, timeout):
            requests.append(request)
            return FakeResponse(b'{"status":"pending"}')
        result = start_verification("+37060000000",
                                    env={**ENV, "TWILIO_VERIFY_ENABLED": "true"},
                                    transport=fake)
        self.assertEqual(result, {"status": "pending"})
        self.assertTrue(requests[0].full_url.endswith("/Verifications"))
        fields = parse_qs(requests[0].data.decode())
        self.assertEqual(fields, {"To": ["+37060000000"], "Channel": ["sms"]})
        self.assertNotIn("Code", fields)

    def test_check_code_returns_boolean_and_no_session(self):
        requests = []
        def fake(request, timeout):
            requests.append(request)
            return FakeResponse(b'{"status":"approved","sid":"VEfake"}')
        result = check_verification("+37060000000", "123456",
                                    env={**ENV, "TWILIO_VERIFY_ENABLED": "true"},
                                    transport=fake)
        self.assertIs(result, True)
        self.assertTrue(requests[0].full_url.endswith("/VerificationCheck"))
        self.assertEqual(parse_qs(requests[0].data.decode())["Code"], ["123456"])

    def test_no_error_body_or_secret_leaks(self):
        def fail(request, timeout):
            raise HTTPError(request.full_url, 400, "sensitive provider text", {}, None)
        with self.assertRaisesRegex(VerifyError, "^Twilio Verify request failed$"):
            check_verification("+37060000000", "123456",
                               env={**ENV, "TWILIO_VERIFY_ENABLED": "true"},
                               transport=fail)

    def test_bad_number_and_code_do_not_send(self):
        attempts = []
        fake = lambda *args, **kwargs: attempts.append(args)
        enabled = {**ENV, "TWILIO_VERIFY_ENABLED": "true"}
        with self.assertRaises(ValueError):
            start_verification("60000000", env=enabled, transport=fake)
        with self.assertRaises(ValueError):
            check_verification("+37060000000", "not-a-code", env=enabled, transport=fake)
        self.assertEqual(attempts, [])


if __name__ == "__main__":
    unittest.main()
