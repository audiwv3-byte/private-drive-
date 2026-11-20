"""No socket is opened. Unit checks for Safari private HTTPS gateway."""
import base64
import io
import json
import unittest

from pd_private_safari_gateway import make_private_gateway, private_ipv4


class PrivateSafariGatewayTests(unittest.TestCase):
    def setUp(self):
        self.app, self.inbox = make_private_gateway("192.168.1.50", "only-for-testing-password-123456789", clock=lambda: 1000)
        self.auth = "Basic " + base64.b64encode(b"pd-test:only-for-testing-password-123456789").decode()

    def call(self, route, data=None, **change):
        body = json.dumps(data).encode() if data is not None else b""
        env = {
            "REMOTE_ADDR": "192.168.1.50", "wsgi.url_scheme": "https",
            "HTTP_HOST": "pd-test.local:8443", "HTTP_AUTHORIZATION": self.auth,
            "HTTP_ORIGIN": "https://pd-test.local:8443",
            "HTTP_X_PD_TEST": "1",
            "PATH_INFO": route, "REQUEST_METHOD": "POST" if data is not None else "GET",
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(body),
        }
        env.update(change)
        status = []
        raw = b"".join(self.app(env, lambda s, h: status.append(s)))
        code = int(status[0].split()[0])
        return code, json.loads(raw) if route.startswith("/test-registration") or code != 200 else raw.decode()

    def test_no_public_or_unauthenticated_access(self):
        for changes in (
            {"REMOTE_ADDR": "192.168.1.51"},
            {"REMOTE_ADDR": "203.0.113.2"},
            {"wsgi.url_scheme": "http"},
            {"HTTP_HOST": "privatedrive.lt"},
            {"HTTP_AUTHORIZATION": ""},
        ):
            code, _ = self.call("/registration.html", **changes)
            self.assertIn(code, (401, 403))
        self.assertEqual(self.call("/test-registration/request-code",
            {"role":"passenger","channel":"email","destination":"test@example.test"},
            HTTP_ORIGIN="https://other.local")[0],403)

    def test_static_assets_bootstrap_and_api_scope(self):
        code, html = self.call("/registration.html")
        self.assertEqual(code,200)
        self.assertIn("registration-client.mjs", html)
        self.assertIn("private-test-bootstrap.js",html)
        code, js = self.call("/private-test-bootstrap.js")
        self.assertEqual(code,200)
        self.assertIn("__PD_PRIVATE_TEST_ENABLED__",js)
        self.assertEqual(self.call("/")[0],404)
        self.assertEqual(self.call("/native-auth/request-code")[0],404)

    def test_only_dummy_email_and_no_http_token(self):
        for destination in ("real@gmail.com", "+37060000000"):
            code, _ = self.call("/test-registration/request-code",
                {"role":"passenger","channel":"email","destination":destination})
            self.assertEqual(code,400)
        data={"role":"pilot","channel":"email","destination":"pilot@example.test"}
        code, request=self.call("/test-registration/request-code",data)
        self.assertEqual(code,202)
        self.assertNotIn("code",request)
        code, response=self.call("/test-registration/verify-code",
          {"challenge_id":request["challenge_id"],"code":self.inbox[("email","pilot@example.test")]})
        self.assertEqual(code,200)
        self.assertEqual(response["role"],"pilot")
        self.assertEqual(response["approval_status"],"pending")
        self.assertFalse(response["pilot_access"])
        self.assertNotIn("access_token",response)
        self.assertNotIn("destination",response)

    def test_reject_unapproved_cors_and_header(self):
        target={"role":"passenger","channel":"email","destination":"safe@example.test"}
        self.assertEqual(self.call("/test-registration/request-code",target,HTTP_X_PD_TEST="")[0],403)
        self.assertEqual(self.call("/test-registration/request-code",target,HTTP_ORIGIN="null")[0],403)
        self.assertEqual(self.call("/test-registration/request-code",target,HTTP_ORIGIN="https://pd-test.local")[0],403)

    def test_reject_invalid_configuration(self):
        for ip in ("127.0.0.1","0.0.0.0","203.0.113.4","169.254.1.9"):
            with self.assertRaises(ValueError):
                private_ipv4(ip)
        with self.assertRaises(ValueError):
            make_private_gateway("192.168.1.50","short")


if __name__=="__main__":
    unittest.main()
