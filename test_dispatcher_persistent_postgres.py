"""Verify dispatcher order persistence using a disposable loopback Postgres."""

import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch

from flask import Flask, request

from pd_dispatch_persistent import register


@unittest.skipUnless(os.getenv("PD_DISPATCH_LOCAL_POSTGRES_CI") == "1", "disposable Postgres only")
class PersistentDispatcherPostgresTests(unittest.TestCase):
    def client(self):
        app = Flask(__name__)
        register(app, lambda: request.headers.get("X-Test-Dispatcher") == "yes")
        return app.test_client()

    def test_shared_inbox_survives_restart_and_retries_without_duplicate_orders(self):
        key = "local-synthetic-ingest-key-for-tests-only"
        env = {
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_DISPATCH_PERSISTENT_QUEUE": "1",
            "PD_DISPATCH_ORDERS_DATABASE_URL":
                "postgresql://pd_ci:local-synthetic-password@127.0.0.1:5432/pd_dispatch_ci",
            "PD_DISPATCH_ORDERS_INGEST_SECRET": key,
        }
        sources = ("website", "android", "ios", "telegram_miniapp", "telegram_bot")
        orders = [{
            "source": source, "source_order_id": "synthetic-order",
            "from": "Synthetic pickup", "to": "Synthetic destination",
            "trip_date": "2026-11-24", "trip_time": "14:30",
        } for source in sources]

        def post(client, order):
            body = json.dumps(order).encode()
            issued = str(int(time.time()))
            signature = hmac.new(key.encode(), issued.encode() + b"." + body, hashlib.sha256)
            return client.post("/v1/dispatch/orders/import", data=body, headers={
                "Content-Type": "application/json",
                "X-PD-Order-Timestamp": issued,
                "X-PD-Order-Signature": signature.hexdigest(),
            })

        with patch.dict(os.environ, env, clear=True):
            original = self.client()
            ids = {}
            for order in orders:
                result = post(original, order)
                self.assertEqual(result.status_code, 201)
                ids[order["source"]] = result.get_json()["order_id"]

            restarted = self.client()
            for order in orders:
                retried = post(restarted, order)
                self.assertEqual(retried.status_code, 200)
                self.assertEqual(retried.get_json()["order_id"], ids[order["source"]])
            self.assertEqual(post(restarted, {**orders[0], "to": "Another destination"}).status_code, 409)
            self.assertEqual(restarted.get("/dispatch/orders/state").status_code, 401)

            inbox = restarted.get("/dispatch/orders/state", headers={"X-Test-Dispatcher": "yes"})
            self.assertEqual(inbox.status_code, 200)
            self.assertEqual({row["source"]: row["id"] for row in inbox.get_json()["orders"]}, ids)
            self.assertEqual(len(inbox.get_json()["orders"]), len(sources))
