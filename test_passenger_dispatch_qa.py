"""Integration checks for the isolated mobile-to-dispatcher QA order path.

No real SMS, payments, customer accounts or production services.
"""
import hashlib
import hmac
import time
import unittest

from flask import Flask
from pd_dispatch_test_sync import register


class PassengerToDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "unit-tests-only-not-a-real-token"
        register(self.app, lambda: True, lambda: True)
        self.client = self.app.test_client()

    def tearDown(self):
        directory, store = self.app.extensions["pd_dispatch_test_sync"]
        store.close()
        directory.cleanup()

    def bearer(self, role):
        purpose = (
            f"pd-dispatch-staging-mobile-test:v1:{role}:{int(time.time()) // 86400}"
        ).encode("ascii")
        token = hmac.new(self.app.secret_key.encode(), purpose, hashlib.sha256).hexdigest()
        return {"Authorization": f"Bearer {token}"}

    def test_passenger_order_appears_on_dispatcher_and_survives_client_reconnect(self):
        headers = self.bearer("passenger")
        created = self.client.post("/v1/trips", json={
            "from": "Vilnius, Gedimino pr. 12",
            "to": "Vilnius Airport",
            "payment": "Карта",
        }, headers=headers)
        self.assertEqual(created.status_code, 201)
        trip = created.get_json()["trip"]
        self.assertEqual(trip["status"], "requested")
        order_id = trip["id"]

        # The authenticated dispatcher obtains the same order on its polling endpoint.
        board = self.client.get("/dispatch/test-sync/state")
        self.assertEqual(board.status_code, 200)
        self.assertEqual(board.get_json()["trips"][0]["id"], order_id)
        self.assertEqual(board.get_json()["trips"][0]["status"], "requested")

        # A fresh HTTP client simulates closing and reopening passenger's app.
        reconnected = self.app.test_client().get("/v1/current", headers=headers)
        self.assertEqual(reconnected.status_code, 200)
        self.assertEqual(reconnected.get_json()["trip"]["id"], order_id)

        # Dispatcher can assign the exact server order and the new state is visible.
        assigned = self.client.post("/dispatch/test-sync/assign", data={
            "trip_id": order_id, "version": str(trip["version"])
        })
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.get_json()["trip"]["status"], "assigned")
        updated = self.client.get("/dispatch/test-sync/state").get_json()["trips"]
        self.assertEqual(updated[0]["status"], "assigned")

    def test_unauthorized_client_cannot_create_order_or_read_queue(self):
        self.assertEqual(self.client.post("/v1/trips", json={
            "from": "A", "to": "B"
        }).status_code, 401)
        self.assertEqual(self.client.get("/v1/current").status_code, 401)
        self.assertEqual(self.client.get("/dispatch/test-sync/state").status_code, 200)

    def test_duplicate_active_order_is_not_added_to_dispatcher_queue(self):
        headers = self.bearer("passenger")
        payload = {"from": "Vilnius", "to": "Kaunas", "payment": "Карта"}
        self.assertEqual(
            self.client.post("/v1/trips", json=payload, headers=headers).status_code, 201
        )
        duplicate = self.client.post("/v1/trips", json=payload, headers=headers)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.get_json()["error"], "active_trip_exists")
        self.assertEqual(len(self.client.get("/dispatch/test-sync/state").get_json()["trips"]), 1)


if __name__ == "__main__":
    unittest.main()
