"""Offline integration tests on production-derived guarded code, fake SQLite only.

No real bookings, payment calls, Telegram messages, live file modifications.
The actual Flask handler AST is compiled from the temporarily patched live source.
"""
import ast
import contextlib
import datetime
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import types
from flask import Flask,request,jsonify
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ops.cash_offline_overlay_dryrun import FILES,fetch,candidate

def verify(value,label):
    if not value:raise AssertionError(label)
    print("PASS",label,flush=True)

def isolated_handler(code,func_name,env):
    tree=ast.parse(code)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==func_name]
    if len(nodes)!=1:raise RuntimeError("FUNCTION_COUNT_"+func_name)
    node=nodes[0]
    node.decorator_list=[]
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    exec(compile(module,"<isolated-production-handler>","exec"),env)
    return env[func_name]

class StopBeforeSaving(Exception):pass
class FakeCore:
    MAX_PASSENGERS=6
    ORDERS_DB="FAKE_TEST_ONLY"
    LOG=types.SimpleNamespace(exception=lambda *a,**k:None)
    def __init__(self,temp):
        self.filename=str(pathlib.Path(temp)/"orders.sqlite")
        with sqlite3.connect(self.filename) as con:
            con.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, telegram_id INTEGER,payment_method TEXT,status TEXT,price TEXT,payment_status TEXT,stripe_session_id TEXT,updated_at TEXT)")
            con.execute("INSERT INTO orders VALUES(701,1001,'Наличные','Подтверждена','50.00','Не оплачено',NULL,'2026-11-16')")
            con.execute("INSERT INTO orders VALUES(702,1001,'Банковский перевод','Подтверждена','50.00','Не оплачено',NULL,'2026-11-16')")
            con.execute("INSERT INTO orders VALUES(703,2002,'Банковский перевод','Подтверждена','50.00','Не оплачено',NULL,'2026-11-16')")
        self.saved=[]
        self.notified=[]
    def user_record(self,uid):return {"telegram_id":uid}
    def validate_departure(self,*a):return True
    def route(self,*a):return 25,40
    def quote(self,*a):return "50.00"
    def initialize(self):pass
    def order_save(self,uid,st,*args):
        self.saved.append((uid,st))
        raise StopBeforeSaving()
    def order_find(self,oid):
        with self.db(self.ORDERS_DB) as con:
            d=con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
            return dict(d) if d else None
    def now(self):return datetime.datetime(2026,11,16,11,22)
    def notify_admins(self,message):self.notified.append(message)
    @contextlib.contextmanager
    def db(self,db_name):
        with sqlite3.connect(self.filename) as c:
            c.row_factory=sqlite3.Row
            yield c

def state(core,oid):
    with core.db(core.ORDERS_DB) as c:
        r=c.execute("SELECT payment_method,payment_status,updated_at FROM orders WHERE id=?",(oid,)).fetchone()
        return tuple(r) if r else None

def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    old=[fetch(name,token) for name in FILES]
    server,html,bot=candidate(*old)
    ast.parse(server);ast.parse(bot)
    app=Flask("pr28_offline")
    app.config["TESTING"]=True
    with tempfile.TemporaryDirectory(prefix="pd-cash-fixture-") as td:
        core=FakeCore(td)
        auth=lambda:(int(request.headers.get("X-Test-UID","1001")),{})
        env={"core":core,"auth":auth,"request":request,"jsonify":jsonify,
            "validate_route_data":lambda d:None,"pd_pet_extras":lambda d:False,
            "pd_stops":types.SimpleNamespace(address=lambda d:None),
            "pd_map_points":types.SimpleNamespace(point_details=lambda d:"",route_address=lambda *a:a[-1]),
            "pd_fixed_prices":types.SimpleNamespace(base=lambda d:None),
            "pd_pet_price":lambda value,d:value,
            "os":os,"datetime":datetime}
        create=isolated_handler(server,"create_order",env)
        cash=isolated_handler(server,"select_cash",env)
        @app.post("/api/order")
        def new_booking():
            try:return create()
            except ValueError as e:return jsonify(error=str(e)),400
            except StopBeforeSaving:return jsonify(blocked="no real or fixture booking persisted"),204
        @app.post("/api/payment/<int:oid>/cash")
        def cash_request(oid):
            try:return cash(oid)
            except ValueError as e:return jsonify(error=str(e)),400
            except PermissionError:return jsonify(error="forbidden"),403
        def post(path,data=None,uid=1001):
            with app.test_client() as client:
                return client.post(path,json=data or {},headers={"X-Test-UID":str(uid)})
        base={"origin":"Vilnius","destination":"Kaunas","trip_date":"2026-11-19",
              "trip_time":"14:00","passengers":1,"luggage":"Без багажа"}
        for method in ("Наличными","Наличные","💶 Наличные","",None,"Фальшивый способ"):
            payload=dict(base,payment_method=method)
            r=post("/api/order",payload)
            verify(r.status_code==400,"DIRECT_API_NEW_CASH_OR_INVALID_REJECTED_"+repr(method))
        verify(not core.saved,"INVALID_BOOKINGS_NEVER_REACH_SAVE")
        r=post("/api/order",base)
        verify(r.status_code==204,"DEFAULT_BANK_TRANSFER_ACCEPTED_NO_PERSISTENCE")
        verify(core.saved[-1][1]["payment_method"]=="Банковский перевод","DEFAULT_BANK_TRANSFER_METHOD")
        r=post("/api/order",dict(base,payment_method="Банковский перевод"))
        verify(r.status_code==204,"EXPLICIT_BANK_TRANSFER_ACCEPTED_NO_PERSISTENCE")
        historical=state(core,701)
        bank=state(core,702)
        r=post("/api/payment/702/cash")
        verify(r.status_code==400,"OLD_CASH_API_CANNOT_SWITCH_BANK_TO_CASH")
        verify(state(core,702)==bank,"BANK_RECORD_UNCHANGED")
        r=post("/api/payment/703/cash",uid=1001)
        verify(r.status_code==403,"CASH_ENDPOINT_DIFFERENT_OWNER_DENIED")
        verify(state(core,703)==bank,"FOREIGN_ORDER_UNCHANGED")
        # Historical cash records may keep using their original cash flow.
        # Do not invoke a 'payment' transaction: allow mock SQLite transition only.
        r=post("/api/payment/701/cash")
        verify(r.status_code==200,"HISTORICAL_CASH_REQUEST_COMPATIBLE")
        verify(state(core,701)[0]=="Наличные","HISTORICAL_CASH_METHOD_PRESERVED")
        verify(historical[0]=="Наличные","HISTORICAL_FIXTURE_ORIGINALLY_CASH")
        # Cached old bot keyboard must not be permitted after options removal.
        tree=ast.parse(bot)
        targets=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="options" for t in n.targets) and isinstance(n.value,ast.Dict)]
        allowed=[n.value for n in targets if any(isinstance(k,ast.Constant) and k.value=="💳 Безналичная" for k in n.keys)]
        verify(len(allowed)==1,"BOT_PAYMENT_WHITELIST_FOUND")
        menu=ast.literal_eval(allowed[0])
        verify("💶 Наличные" not in menu and "💳 Безналичная" in menu,"OLD_TELEGRAM_CASH_BUTTON_REJECTED")
        verify("cancel_menu([('💶 Наличные'" not in bot,"NEW_BOT_CASH_BUTTONS_REMOVED")
        verify("def admin_cash_received_web" in server and "def admin_cash_receipts_pd" in server,
               "LEGACY_ADMIN_CASH_RECORDS_ROUTE_PRESERVED")
    print("PR28_OFFLINE_SERVER_BOT_HISTORICAL_TESTS_PASS",flush=True)
    print("ONLY_SYNTHETIC_SQLITE_NO_PRODUCTION_WRITES_NO_PAYMENTS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("PR28_OFFLINE_TEST_FAILED",type(e).__name__,str(e)[:140],flush=True)
        raise SystemExit(1)
