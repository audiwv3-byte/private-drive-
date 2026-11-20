"""Browser CORS + two-device messaging contract for the isolated demo only."""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from pd_demo_server import ApiServer, DemoStore

ORIGIN = "https://preview.example.test"
TOKENS = {role: (letter * 40) for role, letter in
          (("passenger", "p"), ("pilot", "i"), ("dispatcher", "d"))}


class BrowserCorsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DemoStore(str(Path(self.temp.name) / "browser.sqlite"))
        credentials = {hashlib.sha256(token.encode()).digest(): (role, role + "_test")
                       for role, token in TOKENS.items()}
        self.server = ApiServer(("127.0.0.1", 0), self.store, credentials,
                                browser_origin=ORIGIN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.temp.cleanup()

    def request(self, method, path, role="passenger", data=None, origin=ORIGIN,
                extra_headers=None):
        headers = {"Authorization": "Bearer " + TOKENS[role]}
        if origin is not None:
            headers["Origin"] = origin
        if extra_headers:
            headers.update(extra_headers)
        body = None if data is None else json.dumps(data).encode("utf-8")
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers)
            res = conn.getresponse()
            raw = res.read()
            return res.status, dict(res.getheaders()), json.loads(raw) if raw else {}
        finally:
            conn.close()

    def test_authorized_browser_preflight(self):
        status, headers, _ = self.request(
            "OPTIONS", "/v1/trips/123/messages", extra_headers={
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type",
            })
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertIn("Authorization", headers["Access-Control-Allow-Headers"])
        self.assertNotIn("Access-Control-Allow-Credentials", headers)

    def test_refuse_untrusted_origin_and_headers(self):
        status, headers, data = self.request("GET", "/v1/me", origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(data["error"], "browser_origin_not_allowed")
        status, headers, _ = self.request(
            "OPTIONS", "/v1/me", extra_headers={
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization, x-extra",
            })
        self.assertEqual(status, 403)
        # Trusted origin may read the explicit preflight rejection, but not use
        # an unauthorized method or request header.
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)

    def test_safari_and_android_separate_tokens_share_one_chat(self):
        # Safari attaches Origin; Android/native HTTP clients do not.
        status, headers, data = self.request("POST", "/v1/trips", data={
            "from": "DEMO A", "to": "DEMO B", "payment": "Карта"})
        self.assertEqual(status, 201)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        trip = data["trip"]
        tid = trip["id"]
        self.assertEqual(self.request("POST", "/v1/trips/" + tid + "/assign",
            role="dispatcher", origin=None,
            data={"pilot": "pilot_test", "version": trip["version"]})[0], 200)
        route = "/v1/trips/" + tid + "/messages"
        status, _, first = self.request("POST", route, data={
            "client_id": uuid.uuid4().hex, "text": "Safari to Android"})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("GET", route, role="pilot", origin=None)
                         [2]["messages"][0]["body"], "Safari to Android")
        self.assertEqual(self.request("POST", route, role="pilot", origin=None,
            data={"client_id": uuid.uuid4().hex,
                  "text": "Android to Safari"})[0], 201)
        status, headers, result = self.request(
            "GET", route + "?after=" + str(first["message"]["seq"]))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual([m["body"] for m in result["messages"]],
                         ["Android to Safari"])


if __name__ == "__main__":
    unittest.main()
