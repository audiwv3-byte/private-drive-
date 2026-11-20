"""Offline tests: zero network, zero SMS/email, zero production access."""
import io
import json
import unittest

from pd_test_registration import make_test_registration_app


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.app, self.inbox = make_test_registration_app(clock=lambda: 1000)

    def request(self, path, payload, ip="127.0.0.1", method="POST"):
        body = json.dumps(payload).encode("utf-8")
        status = []
        raw = b"".join(self.app({
            "PATH_INFO": path, "REQUEST_METHOD": method,
            "REMOTE_ADDR": ip, "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(body)
        }, lambda s, h: status.append(s)))
        return int(status[0].split(" ", 1)[0]), json.loads(raw)

    def start(self, role, email):
        status, data = self.request("/test-registration/request-code", {
            "role": role, "channel": "email", "destination": email
        })
        self.assertEqual(status, 202)
        self.assertNotIn("code", data)
        return data["challenge_id"], self.inbox[("email", email)]

    def test_passenger_verifies_without_telegram(self):
        challenge, code = self.start("passenger", "passenger@example.test")
        status, data = self.request("/test-registration/verify-code", {
            "challenge_id": challenge, "code": code
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["role"], "passenger")
        self.assertEqual(data["approval_status"], "not_required")
        self.assertFalse(data["pilot_access"])
        self.assertTrue(data["access_token"])
        self.assertNotEqual(data["access_token"], code)

    def test_pilot_pending_not_approved(self):
        challenge, code = self.start("pilot", "pilot@example.test")
        status, data = self.request("/test-registration/verify-code", {
            "challenge_id": challenge, "code": code, "role": "passenger"
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["role"], "pilot")
        self.assertEqual(data["approval_status"], "pending")
        self.assertFalse(data["pilot_access"])

    def test_no_reuse_or_role_forgery(self):
        challenge, code = self.start("passenger", "once@example.test")
        payload = {"challenge_id": challenge, "code": code}
        self.assertEqual(self.request("/test-registration/verify-code", payload)[0], 200)
        self.assertEqual(self.request("/test-registration/verify-code", payload)[0], 401)

    def test_invalid_code(self):
        challenge, code = self.start("pilot", "wrong@example.test")
        status, _ = self.request("/test-registration/verify-code", {
            "challenge_id": challenge, "code": "000000" if code != "000000" else "111111"
        })
        self.assertEqual(status, 401)

    def test_network_and_unknown_endpoint_forbidden(self):
        self.assertEqual(self.request("/test-registration/request-code", {
            "role": "passenger", "channel": "email", "destination": "a@example.test"
        }, ip="192.0.2.15")[0], 403)
        self.assertEqual(self.request("/native-auth/request-code", {
            "role": "passenger", "channel": "email", "destination": "a@example.test"
        })[0], 404)
        self.assertEqual(self.request("/test-registration/request-code", {
            "role": "dispatcher", "channel": "email", "destination": "a@example.test"
        })[0], 400)

    def test_no_get_and_no_credentials_over_http(self):
        self.assertEqual(self.request("/test-registration/request-code", {
            "role": "passenger", "channel": "email", "destination": "a@example.test"
        }, method="GET")[0], 405)
        code, result = self.request("/test-registration/request-code", {
            "role": "passenger", "channel": "email", "destination": "a@example.test"
        })
        self.assertEqual(code, 202)
        self.assertNotIn("access_token", result)
        self.assertNotIn("code", result)


if __name__ == "__main__":
    unittest.main()
