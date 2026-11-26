import os
import unittest
from unittest.mock import patch
import urllib.error
import psycopg
from flask import Flask
import pd_dispatch_persistent as queue
import pd_telegram_persistent_bridge as bridge

class Integration(unittest.TestCase):
    def test_delivery_retry_and_dedup(self):
        dsn = "postgresql://qa:qa@127.0.0.1:5432/qa"
        with patch.dict(os.environ, {
            "PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled",
            "PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_TELEGRAM_PERSISTENT_BRIDGE":"1",
            "PD_DISPATCH_ORDERS_DATABASE_URL":dsn,
            "PD_DISPATCH_ORDERS_INGEST_SECRET":"synthetic-test-key-"*3,
            "PD_TELEGRAM_DISPATCH_IMPORT_URL":"https://private-drive-dispatcher-staging.onrender.com/v1/dispatch/orders/import"
        }, clear=True):
            with psycopg.connect(dsn) as db:
                db.execute("""CREATE TABLE pd_dispatch_orders (
                    id uuid PRIMARY KEY, source text NOT NULL, source_order_id text NOT NULL,
                    fingerprint text NOT NULL, origin text NOT NULL, destination text NOT NULL,
                    trip_date text NOT NULL, trip_time text NOT NULL, status text DEFAULT 'requested',
                    created_at timestamptz DEFAULT now(), UNIQUE(source,source_order_id))""")
            app=Flask(__name__)
            queue.register(app,lambda:True)
            client=app.test_client()
            calls=[]
            class Response:
                def __init__(self,r): self.r=r; self.status=r.status_code
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def read(self,n): return self.r.data[:n]
            def transport(req,timeout):
                calls.append(req)
                r=client.post("/v1/dispatch/orders/import",data=req.data,headers=dict(req.header_items()))
                if len(calls)==1:
                    self.assertEqual(r.status_code,201)
                    raise OSError("synthetic lost acknowledgement")
                return Response(r)
            order=dict(id=123,origin="QA origin",destination="QA destination",trip_date="2099-01-01",trip_time="12:00")
            first=bridge.deliver(order,transport=transport,sleep=lambda _:None)
            second=bridge.deliver(order,transport=transport,sleep=lambda _:None)
            self.assertEqual(first["order_id"],second["order_id"])
            self.assertEqual(len(calls),3)
            rows=client.get("/dispatch/orders/state").get_json()["orders"]
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["id"],first["order_id"])
            self.assertEqual(rows[0]["source"],"telegram_miniapp")
            self.assertEqual(client.post("/v1/dispatch/orders/import",json={}).status_code,401)
            with patch.dict(os.environ,{"PD_PAYMENT_MODE":"live"}):
                with self.assertRaises(bridge.DeliveryError):
                    bridge.deliver(order,transport=transport)
                self.assertEqual(len(calls),3)

if __name__ == "__main__":
    unittest.main()
