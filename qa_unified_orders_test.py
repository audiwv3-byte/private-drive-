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

class OutboxAtomicity(unittest.TestCase):
    def setUp(self):
        import ast
        import sqlite3
        import tempfile
        from pathlib import Path
        from datetime import datetime
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "orders.sqlite"
        self.env = patch.dict(os.environ, {"PD_DISPATCH_STAGING_ONLY":"1",
            "PD_PAYMENT_MODE":"disabled","PD_TELEGRAM_PERSISTENT_BRIDGE":"1"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        def db(path):
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        self.db = db
        # Execute the actual repository function without importing bot startup.
        tree = ast.parse(Path("Euro_Baltic_Transfer.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "order_save")
        ns = {"db":db,"ORDERS_DB":self.path,"now":datetime.now}
        exec(compile(ast.Module(body=[node],type_ignores=[]),"Euro_Baltic_Transfer.py","exec"),ns)
        self.save = ns["order_save"]
        with db(self.path) as conn:
            conn.execute("""CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id,order_type,origin,destination,trip_date,trip_time,passengers,luggage,
                details,status,price,payment_method,distance_km,duration_min,route_source,quote_status,
                updated_at,roundtrip_wait,passenger_count_confirmed,request_key,request_fingerprint)""")
        self.order = dict(order_type="QA",origin="QA origin",destination="QA destination",
            trip_date="2099-01-01",trip_time="12:00",passengers=1,luggage="none",payment_method="cash")

    def test_rollback_after_outbox_insert(self):
        import pd_dispatch_outbox as outbox
        original = outbox.enqueue
        def fail(conn, order):
            original(conn, order)
            raise RuntimeError("synthetic failure after enqueue")
        with patch.object(outbox,"enqueue",fail):
            with self.assertRaisesRegex(RuntimeError,"synthetic failure"):
                self.save(1,self.order,"qa-key","fingerprint",dispatch_outbox=True)
        with self.db(self.path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM orders").fetchone()[0],0)
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE name='pd_dispatch_outbox'").fetchone()
            if exists:
                self.assertEqual(conn.execute("SELECT count(*) FROM pd_dispatch_outbox").fetchone()[0],0)

    def test_commit_replay_and_restart(self):
        import pd_dispatch_outbox as outbox
        from contextlib import closing
        oid,created=self.save(1,self.order,"qa-key","fingerprint",dispatch_outbox=True)
        self.assertTrue(created)
        self.assertEqual(self.save(1,self.order,"qa-key","fingerprint",dispatch_outbox=True),(oid,False))
        def fail(order):
            raise bridge.DeliveryError("synthetic offline")
        with closing(self.db(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM orders").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM pd_dispatch_outbox").fetchone()[0],1)
            self.assertEqual(outbox.drain(conn,sender=fail,now=lambda:100),1)
        received=[]
        with closing(self.db(self.path)) as conn:
            self.assertEqual(outbox.drain(conn,sender=received.append,now=lambda:101),0)
            self.assertEqual(outbox.drain(conn,sender=received.append,now=lambda:103),1)
            self.assertEqual(received[0]["id"],oid)
            self.assertEqual(conn.execute("SELECT delivered,attempts FROM pd_dispatch_outbox").fetchone()[:],(1,1))
        with closing(self.db(self.path)) as conn:
            self.assertEqual(outbox.drain(conn,sender=received.append,now=lambda:200),0)
            self.assertEqual(len(received),1)

class AndroidOrders(unittest.TestCase):
    def test_native_orders(self):
        import hashlib
        import uuid
        from pathlib import Path
        from werkzeug.test import Client
        from werkzeug.wrappers import Response
        from pd_native_orders_http import make_orders_app
        dsn = "postgresql://qa:qa@127.0.0.1:5432/qa"
        # Separate database for guarded repository migrations.
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute("CREATE DATABASE private_drive_test")
        dsn = dsn.rsplit("/", 1)[0] + "/private_drive_test"
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute("CREATE TABLE native_auth_users (id text PRIMARY KEY)")
            db.execute("CREATE TABLE native_auth_roles (user_id text PRIMARY KEY, role text)")
            db.execute("CREATE TABLE native_auth_sessions (user_id text, token_hash text PRIMARY KEY, created_at bigint, expires_at bigint, revoked_at bigint)")
            for migration in ("native_auth_session_functions.sql", "native_dispatch_orders.sql"):
                db.execute(Path("migrations", migration).read_text())
            for uid, token, role in (("a", "a"*64, "passenger"), ("b", "b"*64, "passenger"), ("p", "p"*64, "pilot")):
                db.execute("INSERT INTO native_auth_users VALUES (%s)", (uid,))
                db.execute("INSERT INTO native_auth_roles VALUES (%s,%s)", (uid,role))
                db.execute("INSERT INTO native_auth_sessions VALUES (%s,%s,0,2000,NULL)", (uid,hashlib.sha256(token.encode()).hexdigest()))
        with patch.dict(os.environ, {"PD_NATIVE_SMS_ISOLATED":"YES",
            "PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled",
            "PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_DISPATCH_ORDERS_DATABASE_URL":dsn}, clear=True):
            app = Flask(__name__)
            queue.register(app, lambda: True)
            client = Client(make_orders_app(app, dsn, clock=lambda:1000), Response)
            a = {"Authorization":"Bearer " + "a"*64}
            b = {"Authorization":"Bearer " + "b"*64}
            p = {"Authorization":"Bearer " + "p"*64}
            order = {"request_id":str(uuid.uuid4()),"from":"QA origin","to":"QA destination","trip_date":"2099-01-01","trip_time":"12:00"}
            self.assertEqual(client.get("/native-orders").status_code,401)
            self.assertEqual(client.post("/native-orders",json=order,headers=p).status_code,403)
            first = client.post("/native-orders",json=order,headers=a)
            self.assertEqual(first.status_code,201,first.get_data(as_text=True))
            oid = first.json["order_id"]
            retry = client.post("/native-orders",json=order,headers=a)
            self.assertEqual(retry.status_code,200)
            self.assertEqual(retry.json["order_id"],oid)
            self.assertEqual(client.post("/native-orders",json=dict(order,to="Changed"),headers=a).status_code,409)
            self.assertEqual([x["order_id"] for x in client.get("/native-orders",headers=a).json["orders"]],[oid])
            self.assertEqual(client.get("/native-orders",headers=b).json["orders"],[])
            rows = client.get("/dispatch/orders/state").json["orders"]
            self.assertEqual([(x["id"],x["source"]) for x in rows],[(oid,"android")])
            with psycopg.connect(dsn) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM pd_dispatch_orders").fetchone()[0],1)
            with patch.dict(os.environ, {"PD_PAYMENT_MODE":"live"}):
                self.assertEqual(client.post("/native-orders",json=order,headers=a).status_code,503)


if __name__ == "__main__":
    unittest.main()
