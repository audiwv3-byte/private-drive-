"""No network, no real payment: synthetic Telegram-to-dispatch bridge tests."""
import io
import json
import os
import unittest
from unittest.mock import patch
from pd_miniapp_dispatch_bridge import (
    DispatchBridgeUnavailable, bridge_enabled, central_delivery_required, publish_telegram_order,
)
from pd_dispatch_persistent import verified_request


ORDER = dict(id=42, origin="Vilnius Airport", destination="Vilnius",
             trip_date="2026-12-02", trip_time="12:30")
ENDPOINT = "https://dispatcher.example.test/v1/dispatch/orders/import"
SECRET = "a" * 48


class FakeResponse:
    status = 201

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, max_bytes):
        return json.dumps(self.body).encode("utf-8")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PD_MINIAPP_DISPATCH_BRIDGE": "1",
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_PAYMENT_MODE": "disabled",
            "PD_DISPATCH_ORDERS_INGEST_SECRET": SECRET,
            "PD_MINIAPP_DISPATCH_IMPORT_URL": ENDPOINT,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_same_order_id_signed_and_forwarded(self):
        requests = []
        def send(req, timeout):
            self.assertEqual(timeout, 5)
            body = req.data
            self.assertEqual(json.loads(body)["source_order_id"], "42")
            self.assertEqual(json.loads(body)["source"], "telegram_miniapp")
            self.assertNotIn("payment_method", json.loads(body))
            headers = {k.lower(): v for k, v in req.header_items()}
            self.assertTrue(verified_request(body, {
                "X-PD-Order-Timestamp": headers["x-pd-order-timestamp"],
                "X-PD-Order-Signature": headers["x-pd-order-signature"],
            }, SECRET, now=1800000000))
            requests.append(body)
            return FakeResponse({
                "source": "telegram_miniapp", "source_order_id": "42",
                "order_id": "central-123", "payment_mode": "disabled",
            })
        self.assertEqual(publish_telegram_order(ORDER, open_url=send,
                          now=lambda: 1800000000), "central-123")
        self.assertEqual(publish_telegram_order(ORDER, open_url=send,
                          now=lambda: 1800000000), "central-123")
        self.assertEqual(requests[0], requests[1])

    def test_bot_source_delivers_once_with_idempotent_central_id(self):
        received = []
        def send(req, timeout):
            payload = json.loads(req.data)
            self.assertEqual(payload["source"], "telegram_bot")
            self.assertEqual(payload["source_order_id"], "42")
            self.assertNotIn("payment_method", payload)
            headers = {k.lower(): v for k, v in req.header_items()}
            self.assertTrue(verified_request(req.data, {
                "X-PD-Order-Timestamp": headers["x-pd-order-timestamp"],
                "X-PD-Order-Signature": headers["x-pd-order-signature"],
            }, SECRET, now=1800000000))
            received.append(payload)
            return FakeResponse({
                "source": "telegram_bot", "source_order_id": "42",
                "order_id": "same-central-order", "payment_mode": "disabled",
            })
        first = publish_telegram_order(ORDER, source="telegram_bot",
                                       open_url=send, now=lambda: 1800000000)
        replay = publish_telegram_order(ORDER, source="telegram_bot",
                                        open_url=send, now=lambda: 1800000000)
        self.assertEqual(first, replay)
        self.assertEqual(received[0], received[1])

    def test_bot_mismatched_ack_fails_closed(self):
        def send(req, timeout):
            return FakeResponse({
                "source": "telegram_miniapp", "source_order_id": "42",
                "order_id": "wrong-source", "payment_mode": "disabled",
            })
        with self.assertRaises(DispatchBridgeUnavailable):
            publish_telegram_order(ORDER, source="telegram_bot", open_url=send)

    def test_reject_client_defined_sources(self):
        with self.assertRaises(DispatchBridgeUnavailable):
            publish_telegram_order(ORDER, source="android",
                                   open_url=lambda *_: self.fail("network"))

    def test_legacy_date_converted_to_iso(self):
        def send(req, timeout):
            self.assertEqual(json.loads(req.data)["trip_date"], "2026-12-02")
            return FakeResponse({
                "source": "telegram_miniapp", "source_order_id": "42",
                "order_id": "central-123", "payment_mode": "disabled",
            })
        publish_telegram_order(dict(ORDER, trip_date="02.12.2026"), open_url=send)

    def test_staging_requires_central_ack_even_when_bridge_off(self):
        os.environ["PD_MINIAPP_DISPATCH_BRIDGE"] = "0"
        self.assertTrue(central_delivery_required())
        self.assertFalse(bridge_enabled())

    def test_nonstaging_does_not_force_central_ack(self):
        os.environ["PD_DISPATCH_STAGING_ONLY"] = "0"
        self.assertFalse(central_delivery_required())
        self.assertFalse(bridge_enabled())

    def test_disabled_is_no_network(self):
        os.environ["PD_PAYMENT_MODE"] = "live"
        self.assertFalse(bridge_enabled())
        self.assertIsNone(publish_telegram_order(ORDER, open_url=lambda *_: self.fail("network")))

    def test_no_success_without_central_ack(self):
        def send(req, timeout):
            return FakeResponse({"order_id": "central", "source": "wrong",
                                 "source_order_id": "42", "payment_mode": "disabled"})
        with self.assertRaises(DispatchBridgeUnavailable):
            publish_telegram_order(ORDER, open_url=send)

    def test_no_http_or_secret_in_url(self):
        os.environ["PD_MINIAPP_DISPATCH_IMPORT_URL"] = "http://dispatcher.example.test/v1/dispatch/orders/import"
        with self.assertRaises(DispatchBridgeUnavailable):
            publish_telegram_order(ORDER, open_url=lambda *_: self.fail("network"))
        os.environ["PD_MINIAPP_DISPATCH_IMPORT_URL"] = ENDPOINT
        os.environ["PD_DISPATCH_ORDERS_INGEST_SECRET"] = "short"
        with self.assertRaises(DispatchBridgeUnavailable):
            publish_telegram_order(ORDER, open_url=lambda *_: self.fail("network"))

    def test_network_error_is_not_acknowledged(self):
        def send(req, timeout):
            raise OSError("offline")
        with self.assertRaises(DispatchBridgeUnavailable):
            publish_telegram_order(ORDER, open_url=send)


if __name__ == "__main__":
    unittest.main()
