import os
import unittest
from unittest.mock import patch
from flask import Flask
from pd_dispatch_persistent import enabled, validated_order, register

class PaymentGuardTests(unittest.TestCase):
    def test_explicit_disabled_required(self):
        env = {"PD_DISPATCH_STAGING_ONLY":"1",
               "PD_DISPATCH_PERSISTENT_QUEUE":"1",
               "PD_DISPATCH_ORDERS_DATABASE_URL":"postgresql://example/test",
               "PD_DISPATCH_ORDERS_INGEST_SECRET":"x"*32}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(enabled())
            os.environ["PD_PAYMENT_MODE"]="live"
            self.assertFalse(enabled())
            os.environ["PD_PAYMENT_MODE"]="disabled"
            self.assertTrue(enabled())

    def test_disabled_route_fails_closed(self):
        app = Flask(__name__)
        register(app, lambda: True)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(app.test_client().post("/v1/dispatch/orders/import", json={}).status_code, 503)

    def test_invalid_date_and_source(self):
        data = {"source":"android","source_order_id":"abc","from":"Vilnius",
                "to":"Kaunas","trip_date":"2026-11-25","trip_time":"12:00"}
        self.assertEqual(validated_order(data)[0], "android")
        for changes in ({"trip_date":"2026-02-30"}, {"source":[]}, {"trip_time":"24:00"}):
            with self.assertRaises(ValueError):
                validated_order(dict(data, **changes))

if __name__ == "__main__":
    unittest.main()
