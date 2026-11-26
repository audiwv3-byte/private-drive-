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

def test_qa27_gps(monkeypatch):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    initialize_database(dsn)
    now = int(time.time())
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql","native_dispatch_orders.sql","native_pilot_identity.sql","qa26_pilot_assignment.sql","qa27_pilot_gps.sql"):
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
    for k,v in {"PD_QA25_WSGI":"1","PD_QA26_ASSIGNMENT":"1","PD_QA27_GPS":"1","PD_QA26_CSRF":csrf,"PD_QA25_TELEGRAM_TEST_TOKEN":token,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_NATIVE_PILOT_ASSIGNMENT":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn,"PD_PILOT_ASSIGNMENT_DATABASE_URL":api_dsn}.items():
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
    body = {"request_key":uuid.uuid4().hex,"origin":"Synthetic A","destination":"Synthetic B","trip_date":"2027-01-01","trip_time":"12:00"}
    order = api.post("/api/order",json=body,headers=tg(101))
    assert order.status_code == 200,order.json
    oid = order.json["order_id"]
    path = "/native-pilot-orders/"+oid+"/gps"
    read = "/dispatch/orders/"+oid+"/gps"
    now = int(time.time())
    fix = {"enabled":True,"captured_at":now-10,"latitude":1.25,"longitude":2.5}
    assert api.get(read,headers=tg(201)).json == {"available":False}
    assert api.get(read,headers=tg(101)).status_code == 401
    assert api.post(path,json=fix,headers=native("b")).status_code == 404
    assigned = api.post("/dispatch/orders/"+oid+"/assign",data={"pilot_id":"qa26-pilot","csrf":csrf},headers=tg(201))
    assert assigned.status_code == 200,assigned.json
    assert api.post(path,json=fix).status_code == 401
    assert api.post(path,json=fix,headers=native("a")).status_code == 403
    assert api.post(path,json=fix,headers=native("c")).status_code == 404
    assert api.post(path,json=fix,headers=native("d")).status_code == 403
    for changes in ({"latitude":91},{"longitude":181},{"latitude":True},{"latitude":"1.25"},{"latitude":float("nan")},{"captured_at":now-60},{"captured_at":now+60},{"pilot_id":"spoof"}):
        assert api.post(path,json=dict(fix,**changes),headers=native("b")).status_code == 400
    assert api.post(path,json=fix,headers=native("b")).status_code == 200
    observed = api.get(read,headers=tg(201)).json
    assert observed == {"available":True,"latitude":1.25,"longitude":2.5,"captured_at":now-10},observed
    assert api.post(path,json=dict(fix,latitude=3.25),headers=native("b")).status_code == 409
    assert api.post(path,json=dict(fix,captured_at=now-11),headers=native("b")).status_code == 409
    # New application instance must see the committed latest fix.
    second = Client(create_application(),Response)
    assert second.get(read,headers=tg(201)).json == observed
    assert api.post(path,json={"enabled":False,"captured_at":now-9},headers=native("b")).status_code == 200
    assert api.get(read,headers=tg(201)).json == {"available":False}
    assert api.post(path,json=fix,headers=native("b")).status_code == 409
    assert api.post(path,json=dict(fix,captured_at=now-8),headers=native("b")).status_code == 200
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE public.pd_qa27_gps SET captured_at=%s WHERE order_id=%s",(now-60,oid))
    assert api.get(read,headers=tg(201)).json == {"available":False}
    assert api.post(path,json=dict(fix,captured_at=now-7),headers=native("b")).status_code == 200
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE native_auth_sessions SET revoked_at=%s WHERE token_hash=%s",(now,hashlib.sha256(("b"*48).encode()).hexdigest()))
    assert api.post(path,json=dict(fix,captured_at=now-6),headers=native("b")).status_code == 401
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE native_auth_sessions SET revoked_at=NULL WHERE token_hash=%s",(hashlib.sha256(("b"*48).encode()).hexdigest(),))
    for act in ("approach","start","finish"):
        result = api.patch("/native-pilot-orders",json={"order_id":oid,"action":act},headers=native("b"))
        assert result.status_code == 200,result.json
    assert api.get(read,headers=tg(201)).json == {"available":False}
    assert api.post(path,json=dict(fix,captured_at=now-5),headers=native("b")).status_code == 409
    with psycopg.connect(dsn) as db:
        assert db.execute("SELECT count(*) FROM public.pd_qa27_gps").fetchone()[0] == 0
    monkeypatch.setenv("PD_PAYMENT_MODE","live")
    assert api.post(path,json=fix,headers=native("b")).status_code == 503
    assert api.get(read,headers=tg(201)).status_code == 503
