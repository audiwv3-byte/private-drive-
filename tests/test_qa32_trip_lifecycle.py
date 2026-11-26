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

def test_qa32_trip_lifecycle(monkeypatch):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    initialize_database(dsn)
    now = int(time.time())
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql","native_dispatch_orders.sql","native_pilot_identity.sql","qa26_pilot_assignment.sql","qa27_pilot_gps.sql","qa32_trip_waiting.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa26_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa26_api")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners, public.pd_telegram_order_owners TO qa26_api")
        for signature in ("pd_validate_native_session(text,bigint)","pd_pilot_assignment_candidates(bigint)","pd_assign_native_order(uuid,text,text,bigint)","pd_native_pilot_order_state(text,bigint)","pd_native_pilot_trip_action(text,text,text,bigint)","pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint)","pd_qa27_dispatch_gps(uuid,bigint)"):
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
    for k,v in {"PD_QA27_GPS":"1","PD_QA25_WSGI":"1","PD_QA26_ASSIGNMENT":"1","PD_QA26_CSRF":csrf,"PD_QA25_TELEGRAM_TEST_TOKEN":token,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_NATIVE_PILOT_ASSIGNMENT":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn,"PD_PILOT_ASSIGNMENT_DATABASE_URL":api_dsn}.items():
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
    readiness = api.get("/qa/staging/readiness", headers=tg(201))
    assert readiness.status_code == 200, readiness.json
    assert readiness.json == {"ready": True, "reason": "ok"}
    assert api.get("/qa/staging/readiness", headers=tg(101)).status_code == 403
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
    assert action(tid,"stop_start").status_code == 409
    def gps(oid, enabled=True):
        return api.post("/native-pilot-orders/"+oid+"/gps",headers=native("b"),json={"enabled":enabled,"captured_at":int(time.time()),**({"latitude":54.1,"longitude":25.1} if enabled else {})})
    assert gps(tid).status_code == 200
    for act,status in (("approach","approaching"),("start","underway"),("finish","finished")):
        if act=="finish":
            for oid in (tid,nid):
                first=action(oid,"stop_start")
                assert first.status_code==200 and first.json["waiting_active"] is True, first.json
                assert action(oid,"stop_start").json["changed"] is False
                assert action(oid,"finish").status_code==409
                assert action(oid,"stop_end","c").status_code==404
            time.sleep(2)
            for oid in (tid,nid):
                ended=action(oid,"stop_end")
                assert ended.status_code==200 and ended.json["waiting_seconds"]>=1 and ended.json["waiting_active"] is False, ended.json
                assert ended.json["payment_mode"]=="disabled"
                assert action(oid,"stop_end").json["changed"] is False
                active=next(x for x in api.get("/native-pilot-orders",headers=native("b")).json["orders"] if x["order_id"]==oid)
                assert active["waiting_seconds"]==ended.json["waiting_seconds"] and not active["waiting_active"]
            print("PASS paid-stop timer, duplicate protection, ownership and no payments",flush=True)
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
    assert api.get("/dispatch/orders/"+tid+"/gps",headers=tg(201)).json=={"available":False}
    assert gps(tid).status_code==409
    with psycopg.connect(dsn) as db:
        assert db.execute("SELECT count(*) FROM public.pd_qa27_gps").fetchone()[0]==0
        rows=db.execute("SELECT status,waiting_seconds,waiting_started_at FROM public.pd_dispatch_orders WHERE id IN (%s,%s)",(tid,nid)).fetchall()
        assert len(rows)==2 and all(s=="finished" and w>=1 and a is None for s,w,a in rows)
    print("PASS passenger history, dispatcher status, completed stops and GPS cleanup",flush=True)
    monkeypatch.setenv("PD_PAYMENT_MODE","live")
    assert action(tid,"finish").status_code == 503
    assert assign(tid,"qa26-pilot").status_code == 503
    assert api.get("/api/orders",headers=tg(101)).status_code == 503
