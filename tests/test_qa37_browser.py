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

def test_qa37_browser(monkeypatch):
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
    from threading import Thread
    import secrets, shutil, base64
    from urllib.parse import urlsplit
    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright, expect
    app=create_application()
    def create_order(i):
        response=Client(app,Response).post('/api/order',headers=tg(101),json={
            'request_key':uuid.uuid5(uuid.NAMESPACE_URL,f'qa37-{i}').hex,
            'origin':f'QA37 origin {i:04d}','destination':'QA37 destination',
            'trip_date':'2027-01-01','trip_time':'12:00'})
        assert response.status_code==200,response.json
        return response.json['order_id']
    with ThreadPoolExecutor(max_workers=16) as pool:
        ids=list(pool.map(create_order,range(1000)))
    assert len(set(ids))==1000
    def assign(i):
        response=Client(app,Response).post('/dispatch/orders/'+ids[i]+'/assign',headers=tg(201),data={'pilot_id':f'qa36-pilot-{i}','csrf':csrf})
        assert response.status_code==200,response.json
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(assign,range(49)))
    password=secrets.token_urlsafe(24)
    for k,v in {'PD_DISPATCH_SESSION_SECRET':secrets.token_hex(32),'PD_DISPATCH_PASSWORD_HASH':generate_password_hash(password),'PD_DISPATCH_ADMIN_ID':'201','PD_DISPATCH_TEST_SYNC':'0','PD_DISPATCH_ORDERS_INGEST_SECRET':secrets.token_hex(32)}.items():
        monkeypatch.setenv(k,v)
    from pd_dispatcher_staging_wsgi import application as webapp
    server=make_server('127.0.0.1',0,webapp,threaded=True)
    Thread(target=server.serve_forever,daemon=True).start()
    host=f'127.0.0.1:{server.server_port}'
    url='http://'+host
    errors=[]
    metrics=[]
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
            start=time.perf_counter()
            page.locator('button[type=submit], form button').first.click()
            page.wait_for_url(url+'/dispatch')
            cards=page.locator('#ordersList .card')
            expect(cards).to_have_count(100,timeout=15000)
            expect(page.locator('#countNew')).to_have_text('951')
            expect(page.locator('#countActive')).to_have_text('49')
            expect(page.locator('#countDone')).to_have_text('0')
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            metrics.append({'operation':'login_to_first_render','ms':round((time.perf_counter()-start)*1000,2)})
            seen=[]
            for i in range(1,11):
                start=time.perf_counter()
                if i>1:page.locator('#pdQueueNext').click()
                expect(page.locator('#pdQueuePage')).to_contain_text(f'Страница {i} / 10')
                expect(cards).to_have_count(100)
                page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                metrics.append({'operation':f'page_{i}','ms':round((time.perf_counter()-start)*1000,2)})
                seen.extend(cards.locator('strong').all_text_contents())
            assert len(seen)==1000 and len(set(seen))==1000
            expect(page.locator('#pdQueueNext')).to_be_disabled()
            page.locator('#pdQueuePrev').click()
            expect(page.locator('#pdQueuePage')).to_contain_text('Страница 9 / 10')
            page.locator('[data-filter=new]').click()
            expect(page.locator('#pdQueuePage')).to_contain_text('951 заказов')
            page.locator('[data-filter=active]').click()
            expect(cards).to_have_count(49)
            expect(page.locator('#countNew')).to_have_text('951')
            page.locator('[data-filter=done]').click()
            expect(cards).to_have_count(0)
            print('PASS 1000 unique rendered orders, ten pages, global counters, filters',flush=True)
            page.locator('[data-filter=new]').click()
            expect(cards).to_have_count(100)
            target=cards.filter(has=page.locator('select')).first
            target.wait_for(timeout=15000)
            select=target.locator('select')
            select.select_option('qa36-pilot-49')
            chosen=select.get_attribute('aria-label').split()[-1]
            target.get_by_role('button',name='Назначить пилота').click()
            expect(page.locator('#countActive')).to_have_text('50',timeout=15000)
            expect(page.locator('#countNew')).to_have_text('950')
            page.locator('[data-filter=active]').click()
            expect(cards).to_have_count(50)
            card=cards.filter(has=page.locator('strong',has_text='QA37 origin '+f'{ids.index(chosen):04d}'))
            card.get_by_role('button',name='Пилот на карте').click()
            stamp=int(time.time())
            credential={'Authorization':'Bearer qa36-synthetic-0049-'+'x'*48}
            fix=api.post('/native-pilot-orders/'+chosen+'/gps',headers=credential,json={'enabled':True,'captured_at':stamp,'latitude':54.6872,'longitude':25.2797})
            assert fix.status_code==200,fix.json
            expect(page.locator('.leaflet-marker-pane .pilot-marker')).to_have_count(1,timeout=15000)
            for action in ('approach','arrive','start','finish'):
                response=api.patch('/native-pilot-orders',headers=credential,json={'order_id':chosen,'action':action})
                assert response.status_code==200,response.json
            expect(page.locator('#countDone')).to_have_text('1',timeout=15000)
            expect(page.locator('#countActive')).to_have_text('49')
            expect(page.locator('.leaflet-marker-pane .pilot-marker')).to_have_count(0)
            page.locator('[data-filter=done]').click()
            expect(cards).to_have_count(1)
            assert not errors,errors
            print('PASS browser assignment, GPS marker, automatic finish update and removal',flush=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        Path('qa37-browser-metrics.json').write_text(json.dumps(metrics,indent=2))
        print('QA37_METRICS '+json.dumps(metrics),flush=True)
