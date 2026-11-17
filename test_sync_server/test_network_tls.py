"""HTTPS network integration tests with ephemeral trust and three HTTP clients.

Tests are LAN-independent: no real Cloudflare Tunnel, payment or external host.
Each request uses a separate verified TLS connection to the isolated backend.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pd_demo_server import ApiServer, DemoStore

TOKENS = {
    "passenger": "test-passenger-" + "p" * 40,
    "dispatcher": "test-dispatcher-" + "d" * 40,
    "pilot": "test-pilot-" + "i" * 40,
}


@unittest.skipUnless(shutil.which("openssl"), "openssl required for local TLS smoke tests")
class TlsNetworkIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pd-ephemeral-tls-")
        folder = Path(self.temp.name)
        self.cert, self.key = folder / "cert.pem", folder / "key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-nodes", "-days", "1", "-keyout", str(self.key),
            "-out", str(self.cert), "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.path = folder / "test.sqlite"
        self.store = DemoStore(str(self.path))
        principals = {
            hashlib.sha256(token.encode()).digest(): (role, role + "_test")
            for role, token in TOKENS.items()
        }
        self.server = ApiServer(("127.0.0.1", 0), self.store, principals)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert), str(self.key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.trust = ssl.create_default_context(cafile=str(self.cert))
        self.trust.check_hostname = True
        self.trust.verify_mode = ssl.CERT_REQUIRED

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.temp.cleanup()

    def request(self, role, method, path, payload=None, token=None):
        conn = http.client.HTTPSConnection(
            "localhost", self.server.server_port, timeout=3, context=self.trust,
        )
        headers = {"Authorization": "Bearer " +
                   (TOKENS[role] if token is None else token)}
        body = None if payload is None else json.dumps(payload).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            conn.close()

    def test_verified_tls_rejects_untrusted_certificate(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            conn = http.client.HTTPSConnection("localhost", self.server.server_port, timeout=3)
            try:
                conn.request("GET", "/v1/me", headers={
                    "Authorization": "Bearer " + TOKENS["passenger"],
                })
            finally:
                conn.close()
        code, headers, data = self.request("passenger", "GET", "/v1/me")
        self.assertEqual(code, 200)
        self.assertEqual(data["role"], "passenger")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_three_network_clients_and_restart_recovery(self):
        passenger = self.request("passenger", "POST", "/v1/trips",
                                 {"from": "Вильнюс", "to": "Каунас", "payment": "Карта"})
        self.assertEqual(passenger[0], 201)
        trip_id, version = passenger[2]["trip"]["id"], passenger[2]["trip"]["version"]
        self.assertEqual(self.request("pilot", "GET", "/v1/current")[2]["trip"], None)
        self.assertEqual(
            self.request("pilot", "GET", "/v1/trips/" + trip_id)[0], 404,
        )
        self.assertEqual(self.request(
            "passenger", "POST", "/v1/trips/" + trip_id + "/assign",
            {"pilot": "pilot_test", "version": version})[0], 403)
        assigned = self.request(
            "dispatcher", "POST", "/v1/trips/" + trip_id + "/assign",
            {"pilot": "pilot_test", "version": version})
        self.assertEqual(assigned[0], 200)
        self.assertEqual(assigned[2]["trip"]["status"], "assigned")
        self.assertEqual(self.request(
            "pilot", "GET", "/v1/current")[2]["trip"]["status"], "assigned")

        # Two separate TLS connections race with the same version.
        def advance():
            return self.request(
                "pilot", "POST", "/v1/trips/" + trip_id + "/action",
                {"action": "advance", "version": version + 1})[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(lambda _: advance(), range(2)))
        self.assertEqual(statuses, [200, 409])
        self.assertEqual(self.request(
            "passenger", "GET", "/v1/current")[2]["trip"]["status"], "approaching")
        self.assertEqual(self.request(
            "passenger", "GET", "/v1/trips/" + trip_id + "/events?after=0")[0], 200)
        self.assertEqual(self.request(
            "pilot", "GET", "/v1/me", token="incorrect-token")[0], 401)

        self.store.close()
        self.store = DemoStore(str(self.path))
        self.server.store = self.store
        recovered = self.request("passenger", "GET", "/v1/current")
        self.assertEqual(recovered[0], 200)
        self.assertEqual(recovered[2]["trip"]["status"], "approaching")
        self.assertEqual(recovered[2]["trip"]["version"], 3)

    def test_rejects_unsafe_requests_and_has_no_side_effects(self):
        self.assertEqual(self.request(
            "passenger", "POST", "/v1/trips",
            {"from": "A", "to": "B", "payment": "Наличные"})[0], 400)
        self.assertEqual(self.request(
            "dispatcher", "POST", "/v1/trips", {"from": "A", "to": "B"})[0], 403)
        self.assertIsNone(self.request("passenger", "GET", "/v1/current")[2]["trip"])


if __name__ == "__main__":
    unittest.main()
