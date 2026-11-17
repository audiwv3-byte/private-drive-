import hashlib
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from pd_demo_server import ApiServer, DemoStore, demo_credentials, TripError

TOKENS = {
    "passenger": "p" * 40,
    "pilot": "d" * 40,
    "dispatcher": "a" * 40,
}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "demo.sqlite")
        self.store = DemoStore(self.db_path)
        creds = {hashlib.sha256(value.encode()).digest(): (role, role + "_test")
                 for role, value in TOKENS.items()}
        self.server = ApiServer(("127.0.0.1", 0), self.store, creds)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.temp.cleanup()

    def req(self, method, path, role="passenger", payload=None, token=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {
            "Authorization": "Bearer " + (TOKENS.get(role, "") if token is None else token),
        }
        if headers:
            request_headers.update(headers)
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=request_headers)
        response = conn.getresponse()
        status = response.status
        data = json.loads(response.read())
        conn.close()
        return status, data

    def create(self):
        status, value = self.req("POST", "/v1/trips", payload={
            "from": "Вильнюс", "to": "Каунас", "payment": "PayPal"})
        self.assertEqual(status, 201)
        self.assertEqual(value["trip"]["status"], "requested")
        return value["trip"]

    def test_full_lifecycle_replay_and_restart(self):
        trip = self.create()
        tid, v = trip["id"], trip["version"]
        status, _ = self.req("POST", f"/v1/trips/{tid}/action", role="pilot",
                             payload={"action": "advance", "version": v})
        self.assertEqual(status, 404)  # pilot cannot access unassigned trip
        status, _ = self.req("POST", f"/v1/trips/{tid}/assign", role="passenger",
                             payload={"pilot": "pilot_test", "version": v})
        self.assertEqual(status, 403)
        status, out = self.req("POST", f"/v1/trips/{tid}/assign", role="dispatcher",
                               payload={"pilot": "pilot_test", "version": v})
        self.assertEqual(status, 200)
        self.assertEqual(out["trip"]["status"], "assigned")
        v += 1
        status, _ = self.req("POST", f"/v1/trips/{tid}/assign", role="dispatcher",
                             payload={"pilot": "pilot_test", "version": v - 1})
        self.assertEqual(status, 409)
        for action, state in (("advance", "approaching"), ("pause", "approaching"),
                              ("resume", "approaching"), ("advance", "underway"),
                              ("advance", "finished")):
            status, out = self.req("POST", f"/v1/trips/{tid}/action", role="pilot",
                                   payload={"action": action, "version": v})
            self.assertEqual(status, 200, action)
            self.assertEqual(out["trip"]["status"], state)
            v += 1
        status, result = self.req("GET", "/v1/current")
        self.assertEqual(status, 200)
        self.assertEqual(result["trip"]["status"], "finished")
        status, result = self.req("GET", f"/v1/trips/{tid}/events?after=0", role="pilot")
        self.assertEqual(status, 200)
        self.assertEqual([x["event"] for x in result["events"]],
                         ["created", "assigned", "advance", "pause", "resume", "advance", "advance"])
        seq = result["events"][3]["seq"]
        status, subsequent = self.req("GET", f"/v1/trips/{tid}/events?after={seq}")
        self.assertEqual(status, 200)
        self.assertEqual(len(subsequent["events"]), 3)
        # Verify state durability after closing and reopening SQLite.
        self.store.close()
        restored = DemoStore(self.db_path)
        self.server.store = restored
        self.store = restored
        status, result = self.req("GET", "/v1/current", role="pilot")
        self.assertEqual(status, 200)
        self.assertEqual(result["trip"]["version"], v)
        self.assertEqual(result["trip"]["status"], "finished")

    def test_isolation_inputs_duplicate_and_no_payment_side_effects(self):
        trip = self.create()
        tid = trip["id"]
        self.assertEqual(self.req("POST", "/v1/trips", payload={
            "from": "Вильнюс", "to": "Варшава"})[0], 409)
        self.assertEqual(self.req("GET", f"/v1/trips/{tid}", role="pilot")[0], 404)
        self.assertEqual(self.req("GET", f"/v1/trips/{tid}/events", role="pilot")[0], 404)
        self.assertEqual(self.req("POST", "/v1/trips", role="dispatcher",
                                  payload={"from": "A", "to": "B"})[0], 403)
        self.assertEqual(self.req("GET", "/v1/current", token="wrong")[0], 401)
        self.assertEqual(self.req("GET", "/v1/current", headers={
            "Origin": "https://unknown.site"})[0], 403)
        self.assertEqual(self.req("POST", f"/v1/trips/{tid}/assign",
                                  role="dispatcher", payload={"pilot": "other",
                                  "version": 1})[0], 200)
        self.assertEqual(self.req("GET", f"/v1/trips/{tid}", role="pilot")[0], 404)
        self.assertEqual(self.req("POST", f"/v1/trips/{tid}/action", role="pilot",
                                  payload={"action": "advance", "version": 2})[0], 404)
        self.assertEqual(self.req("GET", "/v1/current", role="pilot")[1], {"trip": None})
        self.assertEqual(self.req("POST", "/v1/trips", payload={
            "from": "A", "to": "B", "payment": "Наличные"})[0], 400)

    def test_unavailable_without_explicit_opt_in_and_credentials(self):
        from pd_demo_server import demo_credentials
        saved = dict(os.environ)
        try:
            for key in list(os.environ):
                if key.startswith("PD_DEMO_"):
                    del os.environ[key]
            with self.assertRaises(RuntimeError):
                demo_credentials()
            for role, token in TOKENS.items():
                os.environ["PD_DEMO_" + role.upper() + "_TOKEN"] = token
            self.assertEqual(len(demo_credentials()), 3)
            os.environ["PD_DEMO_PILOT_TOKEN"] = TOKENS["passenger"]
            with self.assertRaises(RuntimeError):
                demo_credentials()
        finally:
            os.environ.clear()
            os.environ.update(saved)


if __name__ == "__main__":
    unittest.main()
