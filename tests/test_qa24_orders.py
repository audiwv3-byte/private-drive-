import hashlib, os, uuid
from pathlib import Path
import psycopg
from flask import Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response
from pd_native_auth_postgres_http import initialize_database
from pd_native_orders_http import make_orders_app
from pd_dispatch_persistent import register

def test_order_roundtrip(monkeypatch):
    dsn = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    assert os.environ["PD_AUTH_TEST_DATABASE_URL"] == dsn
    initialize_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql", "native_dispatch_orders.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa24_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa24_api")
        db.execute("GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint) TO qa24_api")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners TO qa24_api")
        for uid, token in (("qa24-a", "a"*48), ("qa24-b", "b"*48)):
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)", (uid,uid))
            db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,0,200)", (hashlib.sha256(token.encode()).hexdigest(),uid))
    api_dsn = dsn.replace("postgres:isolated-test@", "qa24_api:synthetic-api@")
    for k,v in {"PD_NATIVE_SMS_ISOLATED":"YES","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn}.items():
        monkeypatch.setenv(k,v)
    def fallback(e,s):
        s("404 Not Found", [])
        return [b""]
    api = Client(make_orders_app(fallback,api_dsn,clock=lambda:100),Response)
    h = {"Authorization":"Bearer "+"a"*48}
    assert api.get("/native-orders").status_code == 401
    payload = {"request_id":str(uuid.uuid4()),"from":"Synthetic A","to":"Synthetic B","trip_date":"2026-12-01","trip_time":"12:00"}
    monkeypatch.setenv("PD_PAYMENT_MODE","live")
    assert api.post("/native-orders",json=payload,headers=h).status_code == 503
    monkeypatch.setenv("PD_PAYMENT_MODE","disabled")
    result = api.post("/native-orders",json=payload,headers=h)
    assert result.status_code == 201, result.json
    oid = result.json["order_id"]
    assert api.post("/native-orders",json=payload,headers=h).json["order_id"] == oid
    assert api.post("/native-orders",json=dict(payload,to="Synthetic C"),headers=h).status_code == 409
    assert api.get("/native-orders",headers=h).json["orders"][0]["order_id"] == oid
    assert api.get("/native-orders",headers={"Authorization":"Bearer "+"b"*48}).json["orders"] == []
    app = Flask(__name__)
    register(app,lambda: False)
    assert app.test_client().get("/dispatch/orders/state").status_code == 401
    app = Flask("authorized")
    register(app,lambda: True)
    assert app.test_client().get("/dispatch/orders/state").json["orders"][0]["id"] == oid
