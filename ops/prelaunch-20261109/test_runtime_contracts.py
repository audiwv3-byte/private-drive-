"""Run an unmodified runtime module against temporary SQLite and fake notifications."""
from contextlib import contextmanager
from datetime import datetime,timezone
import importlib.util
import logging
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
from flask import Flask,jsonify,request

def run(source):
    spec=importlib.util.spec_from_file_location('isolated_runtime',source)
    runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
    with tempfile.TemporaryDirectory(prefix='pd-runtime-',dir=Path(__file__).parent) as temp:
        @contextmanager
        def db(path):
            c=sqlite3.connect(path);c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        users=Path(temp)/'users.db';orders=Path(temp)/'orders.db'
        with db(users) as c:
            c.execute('CREATE TABLE pd_driver_applications(telegram_id INTEGER PRIMARY KEY,status TEXT)')
            c.execute("INSERT INTO pd_driver_applications VALUES(202,'approved')")
        with db(orders) as c:
            c.execute('CREATE TABLE orders(id INTEGER PRIMARY KEY,telegram_id INTEGER,status TEXT,payment_status TEXT,payment_method TEXT,price TEXT,updated_at TEXT)')
            c.execute('CREATE TABLE pd_pilot_assignments(order_id INTEGER PRIMARY KEY,pilot_id INTEGER)')
        sent=[];clock=[1000]
        core=SimpleNamespace(db=db,USERS_DB=users,ORDERS_DB=orders,is_admin=lambda uid:uid==999,
            now=lambda:datetime.now(timezone.utc),say=lambda *args:sent.append(args),LOG=logging.getLogger('fixture'))
        app=Flask('runtime-contract');app.config['TESTING']=True
        @app.errorhandler(PermissionError)
        def denied(error):return jsonify(error=str(error)),401
        @app.errorhandler(ValueError)
        def invalid(error):return jsonify(error=str(error)),400
        def auth():return int(request.headers.get('Test-Identity','202')),{}
        runtime.register(app,core,auth,clock=lambda:clock[0])
        client=app.test_client()
        def call(path,body=None,uid=202):
            return client.open(path,method='POST' if body is not None else 'GET',json=body,headers={'Test-Identity':str(uid)})
        def check(response,code=200):
            assert response.status_code==code,(response.status_code,response.json)
            return response.json
        def fixture(oid,payment_status,method='Банковский перевод'):
            clock[0]=1000
            with db(orders) as c:
                c.execute("INSERT INTO orders VALUES(?,101,'Подтверждена',?,?,'50.00','')",(oid,payment_status,method))
                c.execute('INSERT INTO pd_pilot_assignments VALUES(?,202)',(oid,))
            check(call(f'/api/trip/{oid}/waiting-consent',{'accept':True,'policy':runtime.POLICY},101))
            check(call(f'/api/trip/{oid}/depart',{'lat':54.68,'lon':25.28,'accuracy':10}))
            check(call(f'/api/trip/{oid}/action',{'action':'arrive'}))
        for oid,status,method in [(1,'Не оплачено','Банковский перевод'),(2,'Перевод на проверке','Банковский перевод'),(3,'Криптоперевод на проверке','Криптовалюта'),(4,'Ожидается оплата наличными','Наличные')]:
            fixture(oid,status,method);response=call(f'/api/trip/{oid}/action',{'action':'start'})
            assert response.status_code==400 and 'оплат' in response.json['error'].lower()
            with db(orders) as c:
                assert c.execute('SELECT started_at FROM pd_trip_runtime_v4 WHERE order_id=?',(oid,)).fetchone()[0] is None
                assert c.execute('SELECT payment_status FROM orders WHERE id=?',(oid,)).fetchone()[0]==status
        fixture(5,'Оплачено');clock[0]=1301
        started=check(call('/api/trip/5/action',{'action':'start'}))
        assert started['started_at']==1301 and started['wait_cents']==25
        assert check(call('/api/trip/5/action',{'action':'start'}))['started_at']==1301
        check(call('/api/trip/5/action',{'action':'stop_start'}),400)
        check(call('/api/trip/5/stop-consent',{'accept':True,'policy':'pd-stop-v7-20261029'},101))
        clock[0]=1400;check(call('/api/trip/5/action',{'action':'stop_start'}))
        clock[0]=1401;stopped=check(call('/api/trip/5/action',{'action':'stop_end'}));assert stopped['stop_total_cents']==25
        clock[0]=1500;check(call('/api/trip/5/action',{'action':'stop_start'}))
        clock[0]=1561;finished=check(call('/api/trip/5/action',{'action':'finish'}))
        assert finished['stop_total_cents']==75 and finished['final_cents']==5100
        assert check(call('/api/trip/5/action',{'action':'finish'}))['final_cents']==5100
        with db(orders) as c:
            assert c.execute('SELECT payment_status FROM orders WHERE id=5').fetchone()[0]=='Оплачено'
            assert c.execute("SELECT COUNT(*) FROM pd_trip_events_v4 WHERE order_id=5 AND event='completed'").fetchone()[0]==1
        for path in ['/api/trip/5','/api/trip/5/action']:
            check(call(path,{'action':'start'} if path.endswith('action') else None,303),401)
        assert runtime.waiting_cents(1000,1000,1300)==0
        assert runtime.waiting_cents(1000,1000,1301)==25
        assert runtime.waiting_cents(1000,None,1400)==0
        print('PASS current-runtime contract: paid starts; unpaid/bank review/crypto review/unreceived cash blocked without mutation')
        print('PASS current-runtime contract: pickup 300s=0 and 301s=25c; stops 1s=25c and 61s=50c; final 5100c; completion idempotent')
        print('PASS current-runtime contract: foreign passenger denied; zero real messages or payment calls')

if __name__=='__main__':
    import sys
    run(Path(sys.argv[1]))

