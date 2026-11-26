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

def test_qa36_load(monkeypatch):
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
        for i in range(50):
            uid=f"qa36-pilot-{i}"
            credential=f"qa36-synthetic-{i:04d}-"+"x"*48
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)",(uid,uid))
            db.execute("INSERT INTO native_auth_roles VALUES (%s,'pilot')",(uid,))
            db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",(hashlib.sha256(credential.encode()).hexdigest(),uid,now,now+3600))
            db.execute("INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at) VALUES (%s,%s,'approved',%s,%s,%s)",(uid,uid,now-10,now+3600,now-5))
    api_dsn = dsn.replace("postgres:isolated-test@", "qa26_api:synthetic-api@")
    token = "qa25-synthetic-token"
    csrf = "qa26-synthetic-csrf"
    for k,v in {"PD_QA36_PAGINATION":"1","PD_QA33_TRIP":"1","PD_QA27_GPS":"1","PD_QA25_WSGI":"1","PD_QA26_ASSIGNMENT":"1","PD_QA26_CSRF":csrf,"PD_QA25_TELEGRAM_TEST_TOKEN":token,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_NATIVE_PILOT_ASSIGNMENT":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn,"PD_PILOT_ASSIGNMENT_DATABASE_URL":api_dsn}.items():
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
    import math
    app=create_application()
    metrics=[]
    def batch(stage,name,jobs,workers=16):
        def run(fn):
            started=time.perf_counter()
            try:
                response=fn(Client(app,Response))
                return (time.perf_counter()-started)*1000,response.status_code,response.json
            except Exception:
                return (time.perf_counter()-started)*1000,599,None
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results=list(pool.map(run,jobs))
        duration=time.perf_counter()-started
        samples=sorted(x[0] for x in results)
        errors=sum(not 200<=x[1]<300 for x in results)
        record=dict(stage=stage,operation=name,requests=len(results),concurrency=workers,
            p50_ms=round(samples[math.ceil(len(samples)*.50)-1],2),
            p95_ms=round(samples[math.ceil(len(samples)*.95)-1],2),
            p99_ms=round(samples[math.ceil(len(samples)*.99)-1],2),
            error_pct=round(errors/len(results)*100,2),requests_per_second=round(len(results)/duration,2))
        metrics.append(record)
        print('QA36_METRIC '+json.dumps(record),flush=True)
        Path('qa36-metrics.json').write_text(json.dumps(metrics,indent=2))
        assert errors==0,[(x[1],x[2]) for x in results if not 200<=x[1]<300][:5]
        return [x[2] for x in results]
    for n,pilots in ((100,10),(500,30),(1000,50)):
        # Independent stage, keep the same synthetic users.
        with psycopg.connect(dsn) as db:
            db.execute("TRUNCATE public.pd_dispatch_orders CASCADE")
        def order(i):
            return lambda c:c.post('/api/order',headers=tg(101),json={
                'request_key':uuid.uuid5(uuid.NAMESPACE_URL,f'qa36-{n}-{i}').hex, 'origin':f'Synthetic A {i}',
                'destination':f'Synthetic B {i}', 'trip_date':'2027-01-01','trip_time':'12:00'})
        orders=batch(n,'booking',[order(i) for i in range(n)])
        ids=[o['order_id'] for o in orders]
        assert len(set(ids))==n
        with psycopg.connect(dsn) as db:
            assert db.execute('SELECT count(*) FROM public.pd_dispatch_orders').fetchone()[0]==n
        def assign(i):
            return lambda c:c.post('/dispatch/orders/'+ids[i]+'/assign',headers=tg(201),data={'pilot_id':f'qa36-pilot-{i}','csrf':csrf})
        batch(n,'assignment',[assign(i) for i in range(pilots)])
        def pilot(i):
            return {'Authorization':f'Bearer qa36-synthetic-{i:04d}-'+'x'*48}
        states=batch(n,'pilot_state',[lambda c,i=i:c.get('/native-pilot-orders',headers=pilot(i)) for i in range(pilots)])
        assert all(len(s['orders'])==1 and s['orders'][0]['order_id']==ids[i] for i,s in enumerate(states))
        for cycle in range(3):
            if cycle: time.sleep(1.1)
            stamp=int(time.time())
            batch(n,f'gps_write_{cycle+1}',[lambda c,i=i:c.post('/native-pilot-orders/'+ids[i]+'/gps',headers=pilot(i),json={'enabled':True,'captured_at':stamp,'latitude':54.1+i*.001,'longitude':25.1+cycle*.001}) for i in range(pilots)])
        fixes=batch(n,'gps_read',[lambda c,i=i:c.get('/dispatch/orders/'+ids[i]+'/gps',headers=tg(201)) for i in range(pilots)])
        assert all(x['available'] for x in fixes)
        queue=batch(n,'dispatcher_state',[lambda c:c.get('/dispatch/orders/state',headers=tg(201)) for _ in range(100)])
        assert all(len(q['orders'])==min(n,100) and q['total']==n and q['counts']['active']==pilots and q['counts']['new']==n-pilots for q in queue)
        pages=batch(n,'dispatcher_pages',[lambda c,i=i:c.get('/dispatch/orders/state?page='+str(i),headers=tg(201)) for i in range(1,(n+99)//100+1)])
        visible=[o['id'] for q in pages for o in q['orders']]
        assert len(visible)==n and set(visible)==set(ids)
        active=api.get('/dispatch/orders/state?filter=active',headers=tg(201)).json
        assert active['total']==pilots and len(active['orders'])==pilots
        assert api.get('/dispatch/orders/state?page=-1',headers=tg(201)).status_code==400
        print(f'QA36_QUEUE total={n} visible={len(visible)} pilots={pilots}',flush=True)
    print('PASS load scenarios; see metrics JSON for measured latency and throughput',flush=True)
