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

def test_qa39_services_browser(monkeypatch):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    initialize_database(dsn)
    now = int(time.time())
    with psycopg.connect(dsn, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql","native_dispatch_orders.sql","native_pilot_identity.sql","qa26_pilot_assignment.sql","qa27_pilot_gps.sql","qa32_trip_waiting.sql","qa33_trip_controls.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa26_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa26_api")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners, public.pd_telegram_order_owners, public.pd_native_order_quotes TO qa26_api")
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
    for kind in ("delivery", "jumpstart"):
        body = {"request_id":str(uuid.uuid4()),"from":"Synthetic shop","to":"Помощь на месте" if kind=="jumpstart" else "Synthetic destination","trip_date":"2027-01-01","trip_time":"12:00","details":{"ride_type":kind,"preferences":{"wishes":"Synthetic note"}}}
        def submit(_):
            return Client(create_application(),Response).post("/native-orders",json=body,headers=native("a"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(submit,range(4)))
        assert sorted(x.status_code for x in replies)==[200,200,200,201]
        assert len({x.json["order_id"] for x in replies})==1
        assert all(x.json["quoted_total_cents"]==2000 and x.json["payment_mode"]=="disabled" for x in replies)
        assert api.post("/native-orders",json=body,headers=native("b")).status_code==403
        assert api.post("/native-orders",json=body).status_code==401
        changed={**body,"details":{**body["details"],"preferences":{"wishes":"Changed"}}}
        assert api.post("/native-orders",json=changed,headers=native("a")).status_code==409
    rows=api.get("/dispatch/orders/state",headers=tg(201)).json["orders"]
    assert {x["service_type"] for x in rows}=={"delivery","jumpstart"}
    assert all(x["quoted_total_cents"]==2000 and x["service_notes"]=="Synthetic note" for x in rows)
    assert api.get("/dispatch/orders/state").status_code==401
    history=api.get("/native-orders",headers=native("a")).json["orders"]
    assert len(history)==2 and all(x["quoted_total_cents"]==2000 for x in history)
    print("PASS service price, authorization, concurrent idempotency, dispatcher and history")
    from threading import Thread
    import secrets, shutil
    from urllib.parse import urlsplit
    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright, expect
    password=secrets.token_urlsafe(24)
    for k,v in {'PD_DISPATCH_SESSION_SECRET':secrets.token_hex(32),'PD_DISPATCH_PASSWORD_HASH':generate_password_hash(password),'PD_DISPATCH_ADMIN_ID':'201','PD_DISPATCH_TEST_SYNC':'0','PD_DISPATCH_ORDERS_INGEST_SECRET':secrets.token_hex(32)}.items():
        monkeypatch.setenv(k,v)
    from pd_dispatcher_staging_wsgi import application as webapp
    server=make_server('127.0.0.1',0,webapp,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    host=f'127.0.0.1:{server.server_port}'
    url='http://'+host
    errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('google-chrome'),args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':900})
            page.on('pageerror',lambda exc:errors.append(str(exc)))
            def route(r):
                parsed=urlsplit(r.request.url)
                if parsed.netloc==host:return r.continue_()
                if parsed.netloc=='unpkg.com' and parsed.path in ('/leaflet@1.9.4/dist/leaflet.js','/leaflet@1.9.4/dist/leaflet.css'):
                    file=Path(parsed.path).name
                    return r.fulfill(path=file,content_type='text/javascript' if file.endswith('.js') else 'text/css',headers={'Access-Control-Allow-Origin':'*'})
                return r.abort()
            page.route('**/*',route)
            assert page.request.get(url+'/dispatch/orders/state').status==401
            page.goto(url+'/dispatch/login')
            page.locator('input[name=password]').fill(password)
            page.locator('button[type=submit], form button').first.click()
            page.wait_for_url(url+'/dispatch')
            cards=page.locator('#ordersList .card')
            expect(cards).to_have_count(2,timeout=15000)
            for label,destination in [('Доставка товаров','Synthetic destination'),('Запуск автомобиля','Помощь на месте')]:
                card=cards.filter(has_text=label+' · 20.00 €')
                expect(card).to_have_count(1)
                expect(card.locator('strong')).to_contain_text('Synthetic shop → '+destination)
                expect(card.get_by_text('Synthetic note',exact=True)).to_have_count(1)
            expect(page.locator('#countNew')).to_have_text('2')
            assert not errors,errors
            page.screenshot(path='qa39-services-browser.png',full_page=True)
            browser.close()
            print('PASS Chromium dispatcher: two service cards, fixed EUR 20, routes, notes, authenticated access',flush=True)
    finally:
        server.shutdown()
        server.server_close()
