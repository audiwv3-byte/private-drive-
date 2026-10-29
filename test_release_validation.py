"""Isolated release regression checks. Never uses production DBs, tokens or APIs."""
import gc,hashlib,hmac,json,os,shutil,sys,tempfile,time,urllib.parse
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='pd-release-test-') as temp:
    root=Path(temp)
    for p in SOURCE.glob('*.py'):
        if '.original.' not in p.name and p.name != Path(__file__).name:
            shutil.copy2(p,root/p.name)
    shutil.copytree(SOURCE/'miniapp',root/'miniapp')
    (root/'pd_translations.json').write_text('{}')
    os.environ['BOT_TOKEN']='123:TEST_RELEASE_ONLY'
    os.environ['ADMIN_IDS']='999'
    os.environ['ORS_API_KEY']=''
    os.environ['PD_PAYMENT_MODE']='disabled'
    sys.path.insert(0,str(root))
    import miniapp_server as server
    core=server.core
    original_db=core.db
    @contextmanager
    def closed_db(path):
        connection=original_db(path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()
    core.db=closed_db
    core.initialize();core.referral_initialize()
    sent=[]
    core.say=lambda *args,**kwargs:sent.append(args)
    core.notify_admins=lambda *args,**kwargs:None
    core.bot.answer_callback_query=lambda *args,**kwargs:None
    server.app.config['TESTING']=True
    client=server.app.test_client()
    def signed(uid=101,**overrides):
        data={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Test'})}
        data.update(overrides)
        secret=hmac.new(b'WebAppData',core.TOKEN.encode(),hashlib.sha256).digest()
        data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
        return urllib.parse.urlencode(data)
    def call(path,body=None,uid=101,method=None,init=None):
        headers={'X-Telegram-Init-Data':signed(uid) if init is None else init}
        return client.open(path,method=method or ('POST' if body is not None else 'GET'),json=body,headers=headers)
    def check(response,status):
        assert response.status_code==status,(response.status_code,response.get_data(as_text=True))
        assert response.is_json
        return response.get_json()
    for data in ['', 'hash=bad',signed(user='null'),signed(user='[]'),signed(user='{}'),signed(user='{"id":true}'),signed(auth_date='invalid'),signed(auth_date=str(int(time.time())-90000)),signed()+'&user=duplicate']:
        check(call('/api/me',init=data),401)
    print('PASS authentication: missing, forged, malformed, expired, duplicate data')
    check(call('/api/register',{'name':'Test Passenger','phone':'+37060000000'}),200)
    check(call('/api/register',{'name':['Test'],'phone':'+37060000000'}),400)
    for body in [[],['item'],'text',None]:
        resp=client.post('/api/register',data=json.dumps(body),content_type='application/json',headers={'X-Telegram-Init-Data':signed()})
        check(resp,400)
    check(client.post('/api/register',data='{bad',content_type='application/json'),400)
    for path in ['/api/admin/orders','/api/pilot-info','/api/payment/1','/api/driver/work']:
        resp=call(path,uid=102)
        assert resp.status_code in (401,403),path
    for path in ['/api/admin/orders','/api/driver/work','/api/admin/console/orders','/api/admin/pilot-assignments']:
        assert call(path,uid=101).status_code in (401,403),path
    print('PASS registration and private access')
    print('PASS registered passengers cannot access administrator or pilot APIs')
    request={'origin':'Vilnius','destination':'Kaunas','origin_coordinates':[25.28,54.68],'destination_coordinates':[23.90,54.89],'roundtrip':False,'extras':['Перевозка животного']}
    feature={'properties':{'summary':{'distance':100000,'duration':7200}},'geometry':{'coordinates':[[25.28,54.68],[23.90,54.89]]}}
    with patch.object(server.pd_stops,'directions',return_value=(feature,[25.28,54.68],[23.90,54.89])):
        estimate=check(call('/api/route',request),200)
    assert estimate['price']=='143.00',estimate
    for changes in [{'origin':{}},{'roundtrip':'false'},{'origin_coordinates':[float('nan'),54]},{'origin_coordinates':[999,54]},{'extras':{}},{'stop_address':[]}]:
        check(call('/api/route',request|changes),400)
    future=(core.now()+__import__('datetime').timedelta(days=2)).strftime('%d.%m.%Y')
    booking=request|{'trip_date':future,'trip_time':'14:00','passengers':3,'luggage':'2 чемодана','stop_address':'Trakai','request_key':'release_test_key_123456','details':'TEST'}
    with patch.object(server.pd_stops,'directions',return_value=(feature,[25.28,54.68],[23.90,54.89])):
        first=check(call('/api/order',booking),200)
        repeat=check(call('/api/order',booking),200)
        check(call('/api/order',booking|{'passengers':2}),400)
    oid=first['order_id'];r=core.order_find(oid)
    assert repeat['order_id']==oid and repeat['replayed']
    assert (r['passengers'],r['luggage'],r['stop_address'],r['price'])==(3,'2 чемодана','Trakai','107.80')
    check(call('/api/payment/'+str(oid),uid=103),403)
    print('PASS route, pet pricing, map validation, passengers, luggage, stop and duplicate prevention')
    check(call('/api/admin/status',{'id':oid,'status':'Подтверждена'},uid=999),200)
    check(call('/api/admin/status',{'id':oid,'status':'Подтверждена'},uid=999),400)
    bank=check(call(f'/api/payment/{oid}/bank',{}),200)
    assert bank['amount']=='107.80'
    check(call(f'/api/payment/{oid}/bank/claimed',{}),200)
    check(call(f'/api/payment/{oid}/cash',{}),400)
    before=dict(core.order_find(oid))
    def callback(data,uid):
        return SimpleNamespace(data=data,from_user=SimpleNamespace(id=uid),message=SimpleNamespace(chat=SimpleNamespace(id=uid)),id='test')
    for action in ['menu','cash','card','crypto','USDC']:
        core.handle_payment(callback(f'pay:{oid}:{action}',101))
    core.claim_payment(callback(f'claim:{oid}:USDC',101))
    core.admin_cash_received(callback(f'cashpaid:{oid}',999))
    core.admin_verify_payment(callback(f'paid:{oid}:no',999))
    for fn,cmd in [(core.admin_crypto_amount,'/crypto'),(core.admin_card_link,'/paylink')]:
        fn(SimpleNamespace(from_user=SimpleNamespace(id=999),chat=SimpleNamespace(id=999),text=f'{cmd} {oid} test'))
    assert dict(core.order_find(oid))==before,'Old Telegram controls changed active bank payment'
    check(call(f'/api/admin/bank-transfers/{oid}/received',{'amount':'107.80','verified_in_bank':False},uid=999),400)
    check(call(f'/api/admin/bank-transfers/{oid}/received',{'amount':'1','verified_in_bank':True},uid=999),400)
    receipt={'amount':'107.80','verified_in_bank':True}
    check(call(f'/api/admin/bank-transfers/{oid}/received',receipt,uid=101),401)
    check(call(f'/api/admin/bank-transfers/{oid}/received',receipt,uid=999),200)
    assert check(call(f'/api/admin/bank-transfers/{oid}/received',receipt,uid=999),200)['replayed']
    assert core.order_find(oid)['payment_status']=='Оплачено'
    print('PASS bank payment: owner access, claim distinct from receipt, exact amount, admin-only confirmation, duplicate safety and stale Telegram buttons')
    for target in ['В пути','Выполнена']:
        check(call('/api/admin/status',{'id':oid,'status':target},uid=999),200)
    check(call(f'/api/orders/{oid}/review',{'stars':5,'comment':'Test'}),200)
    orders=check(call('/api/orders'),200)['orders']
    assert orders[0]['review_stars']==5 and orders[0]['status']=='Выполнена'
    assert core.order_find(oid)['payment_status']=='Оплачено'
    print('PASS complete booking lifecycle through completed trip and passenger review')
    from pd_payment_tests import run
    run(server,core,client,call,signed,check)
    from pd_invoice_tests import run as invoice_checks
    invoice_checks(server,core,call,check)
    from pd_pilot_trip_tests import run as pilot_trip_checks
    pilot_trip_checks(server,core,call,check)
    gc.collect()
print('ALL RELEASE CHECKS PASSED; production data and payment providers were not used')
