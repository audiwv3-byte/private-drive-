"""Isolated cross-device chat tests: synthetic users and ephemeral SQLite only."""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from pd_demo_server import ApiServer, DemoStore

TOKENS = {"passenger": "p" * 40, "pilot": "d" * 40, "dispatcher": "a" * 40}

class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "chat.sqlite")
        self.store = DemoStore(self.path)
        credentials = {
            hashlib.sha256(token.encode()).digest(): (role, role + "_test")
            for role, token in TOKENS.items()
        }
        self.server = ApiServer(("127.0.0.1", 0), self.store, credentials)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.temp.cleanup()

    def req(self, method, path, role="passenger", data=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Authorization": "Bearer " + (token if token is not None else TOKENS[role])}
        body = json.dumps(data).encode() if data is not None else None
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = (response.status, json.loads(response.read()))
        conn.close()
        return result

    def assigned(self):
        status, response = self.req("POST", "/v1/trips",
                                    data={"from": "A", "to": "B", "payment": "Карта"})
        self.assertEqual(status, 201)
        trip = response["trip"]
        status, _ = self.req("POST", "/v1/trips/" + trip["id"] + "/assign",
                             role="dispatcher",
                             data={"pilot": "pilot_test", "version": 1})
        self.assertEqual(status, 200)
        return trip["id"]

    def test_cross_device_delivery_cursor_idempotency_and_restart(self):
        tid = self.assigned()
        route = "/v1/trips/" + tid + "/messages"
        uid = uuid.uuid4().hex
        status, sent = self.req("POST", route, role="pilot",
                                data={"client_id": uid, "text": "Я на месте"})
        self.assertEqual(status, 201)
        first_seq = sent["message"]["seq"]
        self.assertEqual(sent["message"]["role"], "pilot")
        self.assertEqual(self.req("POST", route, role="pilot",
            data={"client_id": uid, "text": "Дубликат"})[1]["message"]["seq"], first_seq)
        self.assertEqual(self.req("GET", route, role="passenger")[1]["messages"],
                         [sent["message"]])
        self.assertEqual(self.req("GET", route + f"?after={first_seq}")[1]["messages"], [])
        status, answer = self.req("POST", route, role="passenger",
            data={"client_id": uuid.uuid4().hex, "text": "Выхожу"})
        self.assertEqual(status, 201)
        self.assertEqual(self.req("GET", route + f"?after={first_seq}",
                                  role="pilot")[1]["messages"], [answer["message"]])
        self.store.close()
        self.store = DemoStore(self.path)
        self.server.store = self.store
        self.assertEqual(len(self.req("GET", route, role="passenger")[1]["messages"]), 2)

    def test_denies_unassigned_nonmembers_invalid_messages_and_finished(self):
        status, created = self.req("POST", "/v1/trips", data={"from": "A", "to": "B"})
        self.assertEqual(status, 201)
        tid = created["trip"]["id"]
        route = "/v1/trips/" + tid + "/messages"
        message = {"client_id": uuid.uuid4().hex, "text": "test"}
        self.assertEqual(self.req("POST", route, role="pilot", data=message)[0], 404)
        self.assertEqual(self.req("GET", route)[0], 409)
        self.assertEqual(self.req("POST", route, role="dispatcher", data=message)[0], 403)
        self.assertEqual(self.req("GET", route, role="dispatcher")[0], 403)
        self.assertEqual(self.req("GET", route, token="invalid")[0], 401)
        self.assertEqual(self.req("POST", "/v1/trips/" + tid + "/assign",
            role="dispatcher", data={"pilot": "pilot_test", "version": 1})[0], 200)
        for invalid in ["", "  ", "x" * 501, 14]:
            self.assertEqual(self.req("POST", route, role="pilot",
                data={"client_id": uuid.uuid4().hex, "text": invalid})[0], 400)
        self.assertEqual(self.req("POST", route, role="pilot",
            data={"client_id": "not-an-id", "text": "x"})[0], 400)
        self.assertEqual(self.req("GET", route + "?after=-1")[0], 400)
        self.assertEqual(self.req("GET", route + "?after=0&other=1")[0], 400)
        for v in [2, 3, 4]:
            self.assertEqual(self.req("POST", "/v1/trips/" + tid + "/action",
                role="pilot", data={"action": "advance", "version": v})[0], 200)
        self.assertEqual(self.req("POST", route, role="pilot", data=message)[0], 409)
        self.assertEqual(self.req("GET", route, role="passenger")[0], 409)

if __name__ == "__main__":
    unittest.main()
