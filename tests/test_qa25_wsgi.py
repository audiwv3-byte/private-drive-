import os
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from pathlib import Path
import psycopg
from werkzeug.test import Client
from werkzeug.wrappers import Response
from pd_native_auth_postgres_http import initialize_database

def test_shared_wsgi(monkeypatch):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    initialize_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql", "native_dispatch_orders.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa25_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa25_api")
        db.execute("GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint) TO qa25_api")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners TO qa25_api")
        db.execute("INSERT INTO native_auth_users VALUES ('qa25-native','phone','qa25-native',0)")
        db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,'qa25-native',%s,%s)",
            (hashlib.sha256(("a"*48).encode()).hexdigest(),int(time.time()),int(time.time())+600))
    token = "qa25-synthetic-token"
    api_dsn = dsn.replace("postgres:isolated-test@", "qa25_api:synthetic-api@")
    for k,v in {"PD_QA25_WSGI":"1","PD_QA25_TELEGRAM_TEST_TOKEN":token,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn}.items():
        monkeypatch.setenv(k,v)
    import wsgi
    api = Client(wsgi.application, Response)
    def headers(uid):
        values = {"auth_date":str(int(time.time())), "user":json.dumps({"id":uid})}
        secret = hmac.new(b"WebAppData",token.encode(),hashlib.sha256).digest()
        values["hash"] = hmac.new(secret,"\n".join(k+"="+v for k,v in sorted(values.items())).encode(),hashlib.sha256).hexdigest()
        return {"X-Telegram-Init-Data":urllib.parse.urlencode(values)}
    body = {"request_key":uuid.uuid4().hex,"origin":"Synthetic A","destination":"Synthetic B","trip_date":"2027-01-01","trip_time":"12:00"}
    assert api.post("/api/order",json=body).status_code == 401
    assert api.post("/api/order",json=body,headers=headers(999)).status_code == 403
    assert api.post("/api/order",json=body,headers=headers(201)).status_code == 403
    assert api.post("/api/order",json=dict(body,payment_method="Банковская карта"),headers=headers(101)).status_code == 503
    result = api.post("/api/order",json=body,headers=headers(101))
    assert result.status_code == 200, result.json
    oid = result.json["order_id"]
    assert api.post("/api/order",json=body,headers=headers(101)).json["order_id"] == oid
    assert api.post("/api/order",json=dict(body,destination="Synthetic C"),headers=headers(101)).status_code == 409
    other = api.post("/api/order",json=body,headers=headers(102))
    assert other.status_code == 200 and other.json["order_id"] != oid
    native = api.post("/native-orders",json={"request_id":str(uuid.uuid4()),"from":"Native A","to":"Native B","trip_date":"2027-01-01","trip_time":"13:00"},headers={"Authorization":"Bearer "+"a"*48})
    assert native.status_code == 201, native.json
    assert api.get("/dispatch/orders/state",headers=headers(101)).status_code == 401
    state = api.get("/dispatch/orders/state",headers=headers(201))
    assert state.status_code == 200, state.json
    rows = {r["id"]:r for r in state.json["orders"]}
    assert len(rows) == 3
    assert rows[oid]["source"] == "telegram_miniapp"
    assert rows[native.json["order_id"]]["source"] == "android"
    monkeypatch.setenv("PD_PAYMENT_MODE","live")
    assert api.post("/api/order",json=body,headers=headers(101)).status_code == 503
