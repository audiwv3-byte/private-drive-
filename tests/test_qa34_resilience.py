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

def test_qa34_resilience(monkeypatch):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    initialize_database(dsn)
    now = int(time.time())
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql","native_dispatch_orders.sql","native_pilot_identity.sql","qa26_pilot_assignment.sql","qa27_pilot_gps.sql","qa32_trip_waiting.sql","qa33_trip_controls.sql"):
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
    for k,v in {"PD_QA33_TRIP":"1","PD_QA27_GPS":"1","PD_QA25_WSGI":"1","PD_QA26_ASSIGNMENT":"1","PD_QA26_CSRF":csrf,"PD_QA25_TELEGRAM_TEST_TOKEN":token,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_NATIVE_PILOT_ASSIGNMENT":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn,"PD_PILOT_ASSIGNMENT_DATABASE_URL":api_dsn}.items():
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
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    def race(calls):
        barrier=Barrier(len(calls))
        def invoke(fn):
            barrier.wait(timeout=10)
            return fn(Client(create_application(),Response))
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(invoke,calls))
    body={"request_key":uuid.uuid4().hex,"origin":"Synthetic A","destination":"Synthetic B","trip_date":"2027-01-01","trip_time":"12:00"}
    def submit(client): return client.post('/api/order',json=body,headers=tg(101))
    replies=race([submit]*6)
    assert all(x.status_code==200 for x in replies),[x.status_code for x in replies]
    ids={x.json['order_id'] for x in replies}
    assert len(ids)==1
    tid=ids.pop()
    assert submit(Client(create_application(),Response)).json['order_id']==tid
    assert api.post('/api/order',json={**body,'destination':'Changed'},headers=tg(101)).status_code==409
    with psycopg.connect(dsn) as db:
        assert db.execute('SELECT count(*) FROM public.pd_dispatch_orders').fetchone()[0]==1
    print('PASS concurrent duplicate booking and lost acknowledgement replay',flush=True)
    second=api.post('/api/order',json={**body,'request_key':uuid.uuid4().hex},headers=tg(102))
    assert second.status_code==200
    nid=second.json['order_id']
    def assign(client,oid,pilot): return client.post('/dispatch/orders/'+oid+'/assign',data={'pilot_id':pilot,'csrf':csrf},headers=tg(201))
    candidates=['qa26-pilot','qa26-other']
    result=race([lambda c:assign(c,tid,candidates[0]),lambda c:assign(c,tid,candidates[1])])
    assert sorted(x.status_code for x in result)==[200,409]
    winner=0 if result[0].status_code==200 else 1
    assert assign(api,nid,candidates[1-winner]).status_code==200
    sessions=['b','c']
    pairs=[(tid,sessions[winner]),(nid,sessions[1-winner])]
    for oid,ch in pairs:
        assert {x['order_id'] for x in api.get('/native-pilot-orders',headers=native(ch)).json['orders']}=={oid}
    def action(client,oid,ch,act): return client.patch('/native-pilot-orders',json={'order_id':oid,'action':act},headers=native(ch))
    for act in ['approach','arrive','start','stop_start']:
        responses=race([lambda c,oid=oid,ch=ch:action(c,oid,ch,act) for oid,ch in pairs])
        assert all(x.status_code==200 for x in responses),[x.json for x in responses]
    print('PASS assignment race and two independent concurrent pilot trips',flush=True)
    time.sleep(2)
    for oid,ch in pairs:
        # Discard the first HTTP acknowledgement; recreate the WSGI app/client.
        recovered=Client(create_application(),Response)
        row=recovered.get('/native-pilot-orders',headers=native(ch)).json['orders'][0]
        assert row['order_id']==oid and row['waiting_active'] and row['waiting_seconds']>=1 and row['stop_charge_cents']==25
        assert action(recovered,oid,ch,'stop_start').json['changed'] is False
        assert action(recovered,oid,'c' if ch=='b' else 'b','stop_end').status_code==404
        end=action(recovered,oid,ch,'stop_end')
        assert end.status_code==200
        assert action(recovered,oid,ch,'stop_end').json['changed'] is False
        assert action(recovered,oid,ch,'finish').status_code==200
    with psycopg.connect(dsn) as db:
        rows=db.execute('SELECT status,waiting_seconds,stop_charge_cents,waiting_started_at FROM public.pd_dispatch_orders').fetchall()
        assert len(rows)==2 and all(s=='finished' and w>=1 and fee==25 and t is None for s,w,fee,t in rows)
    print('PASS fresh WSGI client recovery, active timer, isolated pilot ownership and final totals',flush=True)
