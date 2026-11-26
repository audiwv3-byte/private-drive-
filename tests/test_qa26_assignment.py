import hashlib
import hmac
import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path

import psycopg
from werkzeug.test import Client
from werkzeug.wrappers import Response
from pd_native_auth_postgres_http import initialize_database

def test_qa26_assignment_and_status(monkeypatch):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    initialize_database(dsn)
    now = int(time.time())
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql","native_dispatch_orders.sql","native_pilot_identity.sql","qa26_pilot_assignment.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa26_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa26_api")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners, public.pd_telegram_order_owners TO qa26_api")
        for signature in ("pd_validate_native_session(text,bigint)","pd_pilot_assignment_candidates(bigint)","pd_assign_native_order(uuid,text,text,bigint)","pd_native_pilot_order_state(text,bigint)","pd_native_pilot_trip_action(text,text,text,bigint)"):
            db.execute("GRANT EXECUTE ON FUNCTION public."+signature+" TO qa26_api")
        for uid, token, role in (("qa26-passenger","a","passenger"),("qa26-pilot","b","pilot"),("qa26-other","c","pilot"),("qa26-unapproved","d","pilot")):
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)",(uid,uid))
            db.execute("INSERT INTO native_auth_roles VALUES (%s,%s)",(uid,role))
            db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",(hashlib.sha256((token*48).encode()).hexdigest(),uid,now,now+600))
            if role == "pilot" and token != "d":
                db.execute("INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at) VALUES (%s,%s,'approved',%s,%s,%s)",(uid,uid,now-10,now+600,now-5))
    api_dsn = dsn.replace("postgres:isolated-test@", "qa26_api:synthetic-api@")
    token = "qa25-synthetic-token"
    csrf = "qa26-synthetic-csrf"
    for k,v in {"PD_QA25_WSGI":"1","PD_QA26_ASSIGNMENT":"1","PD_QA26_CSRF":csrf,"PD_QA25_TELEGRAM_TEST_TOKEN":token,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_NATIVE_PILOT_ASSIGNMENT":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn,"PD_PILOT_ASSIGNMENT_DATABASE_URL":api_dsn}.items():
        monkeypatch.setenv(k,v)
    from pd_qa25_wsgi import create_application
    api = Client(create_application(),Response)
    def tg(uid):
        values = {"auth_date":str(int(time.time())), "user":json.dumps({"id":uid})}
        key = hmac.new(b"WebAppData",token.encode(),hashlib.sha256).digest()
        values["hash"] = hmac.new(key,"\n".join(k+"="+v for k,v in sorted(values.items())).encode(),hashlib.sha256).hexdigest()
        return {"X-Telegram-Init-Data":urllib.parse.urlencode(values)}
    def native(ch):
        return {"Authorization":"Bearer "+ch*48}
    telegram_body = {"request_key":uuid.uuid4().hex,"origin":"Synthetic A","destination":"Synthetic B","trip_date":"2027-01-01","trip_time":"12:00"}
    t = api.post("/api/order",json=telegram_body,headers=tg(101))
    assert t.status_code == 200,t.json
    tid = t.json["order_id"]
    n = api.post("/native-orders",json={"request_id":str(uuid.uuid4()),"from":"Native A","to":"Native B","trip_date":"2027-01-01","trip_time":"12:00"},headers=native("a"))
    assert n.status_code == 201,n.json
    nid = n.json["order_id"]
    assert api.get("/api/orders",headers=tg(102)).json["orders"] == []
    assert api.get("/dispatch/orders/eligible-pilots",headers=tg(101)).status_code == 401
    assert {p["id"] for p in api.get("/dispatch/orders/eligible-pilots",headers=tg(201)).json["pilots"]} == {"qa26-pilot","qa26-other"}
    def assign(oid,pilot,headers=None,csrf_value=csrf):
        return api.post("/dispatch/orders/"+oid+"/assign",data={"pilot_id":pilot,"csrf":csrf_value},headers=tg(201) if headers is None else headers)
    assert assign(tid,"qa26-pilot",headers=tg(101)).status_code == 401
    assert assign(tid,"qa26-pilot",csrf_value="wrong").status_code == 403
    assert assign(tid,"qa26-unapproved").status_code == 409
    for oid in (tid,nid):
        a = assign(oid,"qa26-pilot")
        assert a.status_code == 200 and a.json["changed"] is True,a.json
        assert assign(oid,"qa26-pilot").json["changed"] is False
        assert assign(oid,"qa26-other").status_code == 409
    assert api.get("/native-pilot-orders",headers=native("a")).status_code == 403
    assert api.get("/native-pilot-orders",headers=native("c")).json["orders"] == []
    assert {r["order_id"] for r in api.get("/native-pilot-orders",headers=native("b")).json["orders"]} == {tid,nid}
    def action(oid,act,ch="b"):
        return api.patch("/native-pilot-orders",json={"order_id":oid,"action":act},headers=native(ch))
    assert action(tid,"start").status_code == 409
    assert action(tid,"approach","c").status_code == 404
    assert action(tid,"approach","a").status_code == 403
    for act,status in (("approach","approaching"),("start","underway"),("finish","finished")):
        for oid in (tid,nid):
            r = action(oid,act)
            assert r.status_code == 200 and r.json["status"] == status,r.json
            assert action(oid,act).json["changed"] is False
        assert api.get("/api/orders",headers=tg(101)).json["orders"][0]["status"] == status
        assert api.get("/native-orders",headers=native("a")).json["orders"][0]["status"] == status
        rows = {r["id"]:r["status"] for r in api.get("/dispatch/orders/state",headers=tg(201)).json["orders"]}
        assert rows == {tid:status,nid:status}
        assert api.post("/api/order",json=telegram_body,headers=tg(101)).json["status"] == status
    assert api.get("/native-pilot-orders",headers=native("b")).json["orders"] == []
    monkeypatch.setenv("PD_PAYMENT_MODE","live")
    assert action(tid,"finish").status_code == 503
    assert assign(tid,"qa26-pilot").status_code == 503
    assert api.get("/api/orders",headers=tg(101)).status_code == 503
