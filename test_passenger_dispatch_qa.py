"""Integration checks for the isolated mobile-to-dispatcher QA order path.

No real SMS, payments, customer accounts or production services.
"""
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch

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

    @staticmethod
    def source_payload(source="telegram_miniapp", source_order_id="451"):
        return {"source": source, "source_order_id": source_order_id,
                "from": "Вильнюс, тестовая улица 1",
                "to": "Аэропорт Вильнюса", "trip_date": "2026-11-24",
                "trip_time": "14:30"}

    def signed_source_request(self, payload, *, secret="test-secret" * 5,
                              issued=None, signature_override=None):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        issued = str(int(time.time())) if issued is None else str(issued)
        signature = hmac.new(secret.encode(), issued.encode() + b"." + raw,
                             hashlib.sha256).hexdigest()
        return self.client.post("/v1/qa-source/import", data=raw, headers={
            "Content-Type": "application/json",
            "X-PD-QA-Timestamp": issued,
            "X-PD-QA-Signature": signature_override or signature,
        })

    def test_telegram_source_bridge_disabled_without_staging_secret(self):
        with patch.dict(os.environ, {"PD_DISPATCH_STAGING_ONLY": "1"}, clear=True):
            result = self.signed_source_request(self.source_payload())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.get_json()["error"], "bridge_disabled")

    def test_telegram_source_bridge_preserves_ids_and_prevents_duplicates(self):
        with patch.dict(os.environ, {"PD_DISPATCH_STAGING_ONLY": "1",
                                     "PD_QA_SOURCE_BRIDGE_SECRET": "test-secret" * 5}):
            first = self.signed_source_request(self.source_payload())
            self.assertEqual(first.status_code, 201, first.get_json())
            first_id = first.get_json()["trip"]["id"]
            board = self.client.get("/dispatch/test-sync/state").get_json()["trips"]
            self.assertEqual(board[0]["id"], first_id)
            self.assertEqual(board[0]["source"], "telegram_miniapp")
            self.assertEqual(board[0]["source_order_id"], "451")
            self.assertEqual(board[0]["trip_date"], "2026-11-24")
            self.assertEqual(board[0]["trip_time"], "14:30")

            replay = self.signed_source_request(self.source_payload())
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.get_json()["replayed"])
            self.assertEqual(replay.get_json()["trip"]["id"], first_id)
            self.assertEqual(len(self.client.get(
                "/dispatch/test-sync/state").get_json()["trips"]), 1)

            conflict = self.source_payload()
            conflict["to"] = "Каунас"
            result = self.signed_source_request(conflict)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.get_json()["error"], "source_order_conflict")

            # Same number from a separate channel must remain a distinct order.
            bot = self.signed_source_request(
                self.source_payload("telegram_bot", "451"))
            self.assertEqual(bot.status_code, 201)
            self.assertNotEqual(bot.get_json()["trip"]["id"], first_id)
            board = self.client.get("/dispatch/test-sync/state").get_json()["trips"]
            self.assertEqual({x["source"] for x in board},
                             {"telegram_miniapp", "telegram_bot"})
            self.assertEqual(len(board), 2)

    def test_telegram_bridge_requires_valid_fresh_signature_and_source(self):
        with patch.dict(os.environ, {"PD_DISPATCH_STAGING_ONLY": "1",
                                     "PD_QA_SOURCE_BRIDGE_SECRET": "test-secret" * 5}):
            payload = self.source_payload()
            self.assertEqual(self.client.post(
                "/v1/qa-source/import", json=payload).status_code, 401)
            self.assertEqual(self.signed_source_request(
                payload, signature_override="0" * 64).status_code, 401)
            self.assertEqual(self.signed_source_request(
                payload, issued=int(time.time()) - 900).status_code, 401)
            payload["source"] = "production"
            self.assertEqual(self.signed_source_request(payload).status_code, 400)
            self.assertFalse(self.client.get(
                "/dispatch/test-sync/state").get_json()["trips"])

    def test_website_booking_shares_dispatcher_queue_and_is_idempotent(self):
        payload = {
            "from": "Вильнюс, Лукишкю 10", "to": "Аэропорт Вильнюса",
            "reference": "a" * 32, "source": "detailed",
        }
        headers = {"Origin": "http://localhost"}
        created = self.client.post("/preview/api/qa-booking",
                                   json=payload, headers=headers)
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertTrue(created.get_json()["qa_only"])
        trip_id = created.get_json()["trip"]["id"]
        board = self.client.get("/dispatch/test-sync/state").get_json()
        self.assertEqual(board["trips"][0]["id"], trip_id)

        # Lost HTTP responses must not create duplicate records.
        retry = self.app.test_client().post(
            "/preview/api/qa-booking", json=payload, headers=headers)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json()["trip"]["id"], trip_id)
        self.assertEqual(len(
            self.client.get("/dispatch/test-sync/state").get_json()["trips"]), 1)

    def test_website_booking_rejects_cross_origin_and_limits_spam(self):
        payload = {"from": "A", "to": "B",
                   "reference": "1" * 32, "source": "quick"}
        self.assertEqual(self.client.post("/preview/api/qa-booking",
            json=payload, headers={"Origin": "https://evil.example"}).status_code, 403)
        for i in range(3):
            payload["reference"] = f"{i+1:032x}"
            self.assertEqual(self.client.post("/preview/api/qa-booking",
                json=payload, headers={"Origin": "http://localhost"}).status_code, 201)
        payload["reference"] = "f" * 32
        limited = self.client.post("/preview/api/qa-booking",
            json=payload, headers={"Origin": "http://localhost"})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(len(self.client.get(
            "/dispatch/test-sync/state").get_json()["trips"]), 3)

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
