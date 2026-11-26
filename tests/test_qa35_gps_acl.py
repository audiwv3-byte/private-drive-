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

def test_qa35_gps_acl(monkeypatch):
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
    with psycopg.connect(dsn,autocommit=True) as db:
        db.execute("CREATE ROLE qa35_untrusted NOLOGIN")
        db.execute("CREATE ROLE qa35_gps_writer NOLOGIN")
        db.execute("CREATE ROLE qa35_gps_reader NOLOGIN")
        db.execute("GRANT EXECUTE ON FUNCTION public.pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint) TO qa35_gps_writer")
        db.execute("GRANT EXECUTE ON FUNCTION public.pd_qa27_dispatch_gps(uuid,bigint) TO qa35_gps_reader")
        for role in ('qa35_untrusted','qa35_gps_writer','qa35_gps_reader'):
            db.execute("SET ROLE "+role)
            try:
                for stmt in ('SELECT * FROM public.pd_qa27_gps','DELETE FROM public.pd_qa27_gps','SELECT * FROM public.native_identity_checks'):
                    try: db.execute(stmt)
                    except psycopg.errors.InsufficientPrivilege: pass
                    else: raise AssertionError(role+' has direct sensitive table access')
                for stmt,permitted in (("SELECT public.pd_qa27_dispatch_gps(%s,%s)",role=='qa35_gps_reader'),("SELECT public.pd_qa27_write_gps(%s,%s,false,NULL,NULL,%s,%s)",role=='qa35_gps_writer')):
                    params=(str(uuid.uuid4()),now) if 'dispatch_gps' in stmt else ('0'*64,str(uuid.uuid4()),now,now)
                    try: result=db.execute(stmt,params).fetchone()[0]
                    except psycopg.errors.InsufficientPrivilege: assert not permitted
                    else: assert permitted and result.get('error') in ('order_not_found','invalid_session')
            finally: db.execute("RESET ROLE")
    print("PASS GPS least privilege: raw table denied, read/write wrappers separated",flush=True)
