import json
import threading
import unittest
from datetime import timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pd_native_auth_sessions import revoke_session
from pd_native_cabinet_mock import CabinetStore, PHOTO, make_mock_server, utc_now


class NativeCabinetMockTest(unittest.TestCase):
    def setUp(self):
        self.now = utc_now()
        self.store = CabinetStore(":memory:", clock=lambda: self.now)
        self.inbox = {}
        self.server = make_mock_server(self.store, self.inbox.__setitem__)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.store.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path, bearer=None, body=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        req = Request(f"http://127.0.0.1:{self.server.server_port}{path}",
                      headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req, timeout=3) as response:
                self.assertEqual(response.status, expected)
                return json.load(response)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, expected)
                return json.load(error)

    def sign_in(self, suffix, role):
        phone = f"+1202555010{suffix}"
        challenge = self.request("/native-auth/request-code", body={
            "channel": "phone", "destination": phone, "role": "dispatcher",
        }, expected=202)
        self.assertNotIn("code", challenge)
        body = {"challenge_id": challenge["challenge_id"],
                "code": self.inbox[phone], "role": "dispatcher"}
        session = self.request("/native-auth/verify-code", body=body)
        self.request("/native-auth/verify-code", body=body, expected=401)
        token = session["access_token"]
        self.assertEqual(self.request("/v1/me", token)["role"], role)
        return token

    def test_native_cabinet_contract(self):
        passenger = self.sign_in(1, "passenger")
        pilot = self.sign_in(2, "pilot")
        dispatcher = self.sign_in(3, "dispatcher")
        stranger = self.sign_in(4, "passenger")
        self.request("/v1/current", expected=401)
        self.request("/v1/gps", pilot, {"online": True}, expected=403)
        self.request("/native-identity/submit", pilot, {"photo": PHOTO})
        photo_id = self.request("/native-identity/queue", dispatcher)["items"][0]["id"]
        self.request("/native-identity/decision/" + photo_id, passenger,
                     {"decision": "approved"}, expected=403)
        self.request("/native-identity/decision/" + photo_id, dispatcher, {"decision": "approved"})

        booking = {"from": "Synthetic A", "to": "Synthetic B",
                   "departure": self.now.isoformat(), "client_id": "a" * 32}
        original = self.request("/v1/trips", passenger, booking, expected=201)["trip"]
        trip = "/v1/trips/" + original["id"]
        repeated = self.request("/v1/trips", passenger, booking, expected=201)["trip"]
        self.assertEqual(repeated["id"], original["id"])
        self.request(trip, stranger, expected=404)
        self.request(trip + "/assign", passenger, {"version": 1}, expected=403)
        self.request("/v1/gps", pilot, {"online": True})
        self.assertIsNone(self.request("/v1/current", dispatcher)["gps"])
        self.request("/v1/gps", pilot, {"online": True, "latitude": 0, "longitude": 0,
                                       "seen_at": self.now.isoformat()}, expected=400)
        fix = {"online": True, "latitude": 54.7, "longitude": 25.3, "seen_at": self.now.isoformat()}
        self.request("/v1/gps", pilot, fix)
        self.assertEqual(self.request("/v1/current", dispatcher)["gps"]["latitude"], 54.7)
        self.assertIsNone(self.request("/v1/current", passenger)["gps"])
        result = self.request(trip + "/assign", dispatcher, {"version": 1})["trip"]
        self.assertFalse(result["accepted"])
        self.assertEqual(self.request("/v1/current", passenger)["gps"]["longitude"], 25.3)
        self.assertIsNone(self.request("/v1/current", stranger)["gps"])

        version = result["version"]

        def action(name):
            nonlocal version
            result = self.request(trip + "/action", pilot, {"version": version, "action": name})["trip"]
            version = result["version"]
            return result

        action("accept")
        action("advance")
        self.request(trip + "/action", pilot, {"version": version, "action": "advance"}, expected=409)
        self.assertIsNotNone(action("arrive")["arrived_at"])
        self.now += timedelta(seconds=180)
        self.assertIsNotNone(action("advance")["departed_at"])
        self.assertIsNone(self.request("/v1/current", dispatcher)["gps"])
        self.assertEqual(action("pause")["paused"], 1)
        self.now += timedelta(seconds=40)
        self.assertEqual(action("resume")["stop_ms"], [40000])
        for n, token in enumerate((passenger, pilot, dispatcher)):
            message = {"text": f"Synthetic message {n}", "client_id": str(n) * 32}
            first = self.request(trip + "/messages", token, message, expected=201)
            second = self.request(trip + "/messages", token, message, expected=201)
            self.assertEqual(second, first)
        self.assertEqual(len(self.request(trip + "/messages", pilot)["messages"]), 3)
        self.request(trip + "/messages", stranger, expected=404)
        self.assertEqual(action("advance")["status"], "finished")
        self.assertEqual(self.request("/v1/current", passenger)["trip"]["status"], "finished")
        self.assertIsNone(self.request("/v1/current", passenger)["gps"])
        with self.store.db:
            revoke_session(self.store.db, passenger)
        self.request("/v1/current", passenger, expected=401)
