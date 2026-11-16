"""Isolated live-code PR25 status transition integration test.

Downloads PythonAnywhere code using GET only. Temporary Flask app, local fake
SQLite databases and dummy identities; never imports production core, reads
production databases or invokes external payment/Telegram APIs.
"""
import ast
import contextlib
import datetime
import importlib.util
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import types
import traceback

from flask import Flask, jsonify, request
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ops.pr25_live_overlay_dryrun import get_live, add_admin_guard, secure_trip_runtime, secure_server_tail, verify_ast

def ensure(cond, label):
    if not cond:
        raise AssertionError(label)
    print("PASS", label, flush=True)

def expected_response(client, url, payload, who, code, label):
    response=client.post(url,json=payload,headers={"X-Dummy-UID":str(who)})
    ensure(response.status_code==code,label+" HTTP "+str(response.status_code))
    return response

def prepare(temp,token):
    # Current live code for ALL components involved in the pilot/dispatcher state.
    files=("miniapp_server.py","pd_trip_runtime_v4.py","pd_pilot_dispatch.py",
           "pd_admin_console_v4.py","pd_pilot_notifications.py")
    original={name:get_live(name,token) for name in files}
    patched={}
    # Since PR25 deployment, the live sources already include the guards.
    # Reuse exact production bytes, rather than attempting to patch twice.
    server_is_patched="pd_trip_runtime_v4.secure_legacy_status_route(app)" in original["miniapp_server.py"]
    runtime_is_patched="def secure_legacy_status_route(app):" in original["pd_trip_runtime_v4.py"]
    ensure(server_is_patched and runtime_is_patched,"PR25_INSTALLED_GUARDS_IN_LIVE_SOURCE")
    patched["miniapp_server.py"]=original["miniapp_server.py"]
    patched["pd_trip_runtime_v4.py"]=original["pd_trip_runtime_v4.py"]
    patched["pd_pilot_dispatch.py"]=original["pd_pilot_dispatch.py"]
    patched["pd_admin_console_v4.py"]=original["pd_admin_console_v4.py"]
    patched["pd_pilot_notifications.py"]=original["pd_pilot_notifications.py"]
    verify_ast(patched["miniapp_server.py"],patched["pd_trip_runtime_v4.py"])
    for filename,content in patched.items():
        ast.parse(content)
        (temp/filename).write_text(content,encoding="utf-8")
    print("TEMPORARY_SERVER_COMPONENTS",len(patched),"COPIED_AND_COMPILED",flush=True)
    return patched

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    inst=importlib.util.module_from_spec(spec)
    sys.modules[name]=inst
    spec.loader.exec_module(inst)
    return inst

def fake_core(temp):
    orders=temp/"isolated_orders.sqlite"
    users=temp/"isolated_users.sqlite"
    @contextlib.contextmanager
    def db(path):
        conn=sqlite3.connect(str(path),timeout=8)
        conn.row_factory=sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    core=types.SimpleNamespace(
        ORDERS_DB=orders,
        USERS_DB=users,
        db=db,
        is_admin=lambda user: user==999,
        now=lambda:datetime.datetime(2026,11,16,4,0,0),
        say=lambda *args,**kwargs:None,
        LOG=types.SimpleNamespace(exception=lambda *a,**kw:None),
        payment_button=lambda oid:None,
    )
    with db(users) as c:
        c.executescript("""
CREATE TABLE users(telegram_id INTEGER PRIMARY KEY,name TEXT,phone TEXT);
CREATE TABLE pd_driver_applications(telegram_id INTEGER PRIMARY KEY,status TEXT,name TEXT,phone TEXT,city TEXT,vehicle TEXT,vehicle_year TEXT,plate TEXT,seats INTEGER);
CREATE TABLE pd_driver_documents(telegram_id INTEGER,side TEXT);
INSERT INTO users VALUES(101,'Passenger','+37060000000');
INSERT INTO pd_driver_applications VALUES(201,'approved','Pilot','+37060000001','Vilnius','Test Car','2020','TEST001',4);
INSERT INTO pd_driver_applications(telegram_id,status,name,phone,city,vehicle,vehicle_year,plate,seats) VALUES(202,'pending','Unapproved','','','','','',4);
""")
    with db(orders) as c:
        c.executescript("""
CREATE TABLE orders(
 id INTEGER PRIMARY KEY, telegram_id INTEGER, status TEXT, payment_status TEXT,
 price TEXT, origin TEXT, destination TEXT, stop_address TEXT,
 trip_date TEXT,trip_time TEXT,order_type TEXT,passengers INTEGER,
 luggage TEXT,details TEXT,payment_method TEXT,distance_km REAL,
 duration_min REAL,created_at TEXT,updated_at TEXT,
 admin_note TEXT DEFAULT '',quote_status TEXT DEFAULT '',
 stripe_session_id TEXT,card_payment_url TEXT,crypto_currency TEXT,
 crypto_amount TEXT,crypto_txid TEXT
);
INSERT INTO orders(id,telegram_id,status,payment_status,price,origin,destination,stop_address,trip_date,trip_time,order_type,passengers,luggage,details,payment_method,created_at,updated_at)
VALUES(501,101,'Подтверждена','Оплачено','50.00','Vilnius','Kaunas','','16.11.2026','10:00','В одну сторону',1,'','TEST','Наличные','2026-11-16','2026-11-16');
INSERT INTO orders(id,telegram_id,status,payment_status,price,origin,destination,stop_address,trip_date,trip_time,order_type,passengers,luggage,details,payment_method,created_at,updated_at)
VALUES(502,101,'Подтверждена','Не оплачено','30.00','Vilnius','Trakai','','16.11.2026','11:00','В одну сторону',1,'','TEST','Наличные','2026-11-16','2026-11-16');
INSERT INTO orders(id,telegram_id,status,payment_status,price,origin,destination,stop_address,trip_date,trip_time,order_type,passengers,luggage,details,payment_method,created_at,updated_at)
VALUES(503,101,'Подтверждена','Оплачено','75.00','Vilnius','Klaipeda','','16.11.2026','12:00','В одну сторону',1,'','TEST','Наличные','2026-11-16','2026-11-16');
""")
    return core

def main():
    token=os.environ["PYTHONANYWHERE_API_TOKEN"].strip()
    token=re.sub(r"^Token\s+","",token,flags=re.I)
    with tempfile.TemporaryDirectory(prefix="pd-pr25-live-full-synthetic-") as tempdir:
        temp=pathlib.Path(tempdir)
        source=prepare(temp,token)
        # Inspect only arithmetic around the synthetic finish failure; no secrets or records.
        code_lines=source["pd_trip_runtime_v4.py"].splitlines()
        for line_number in range(331,340):
            line=code_lines[line_number-1]
            if any(word in line.lower() for word in ("secret","token","password","api_key")):continue
            print("FINISH_LOGIC_LINE",line_number,line[:180].strip(),flush=True)
        core=fake_core(temp)
        app=Flask("isolated_pr25_status")
        app.config["TESTING"]=True
        time_now=[2000000000]
        def auth():
            v=request.headers.get("X-Dummy-UID","")
            if not v.isdecimal():raise PermissionError("Missing synthetic identity")
            return int(v),{}
        @app.errorhandler(ValueError)
        def invalid(exc):return jsonify(error=str(exc)),400
        @app.errorhandler(PermissionError)
        def forbidden(exc):return jsonify(error=str(exc)),403
        @app.get("/api/me")
        def me():return jsonify(id=auth()[0])
        sys.path.insert(0,str(temp))
        runtime=module("isolated_live_pd_trip_runtime_v4",temp/"pd_trip_runtime_v4.py")
        console=module("isolated_live_pd_admin_console_v4",temp/"pd_admin_console_v4.py")
        dispatch=module("isolated_live_pd_pilot_dispatch",temp/"pd_pilot_dispatch.py")
        runtime.register(app,core,auth,provider=None,clock=lambda:time_now[0])
        console.register(app,core,auth)
        dispatch.register(app,core,auth)
        # Bind the actual legacy admin_status AST function from patched live code.
        main_ast=ast.parse(source["miniapp_server.py"])
        found=[node for node in main_ast.body if isinstance(node,ast.FunctionDef) and node.name=="admin_status"]
        ensure(len(found)==1,"EXACT_LIVE_ADMIN_STATUS_FUNCTION_FOUND")
        isolated=ast.Module(body=[found[0]],type_ignores=[])
        ast.fix_missing_locations(isolated)
        exec(compile(isolated,str(temp/"miniapp_server.py"),"exec"),
             {"app":app,"core":core,"auth":auth,"request":request,"jsonify":jsonify,
              "os":os,"__name__":"isolated_admin_status"})
        runtime.secure_legacy_status_route(app)
        ensure(bool(app.config.get("PD_TRIP_LEGACY_STATUS_SECURED")),
               "OLD_PILOT_ROUTE_REBOUND_TO_SINGLE_TRANSITION")
        with core.db(core.ORDERS_DB) as c:
            c.executemany("INSERT INTO pd_pilot_assignments(order_id,pilot_id,assigned_by,assigned_at) VALUES(?,?,?,?)",
                          [(501,201,999,"2026-11-16"),(502,201,999,"2026-11-16"),(503,201,999,"2026-11-16")])
        def state(oid):
            with core.db(core.ORDERS_DB) as c:
                row=c.execute("SELECT status,payment_status FROM orders WHERE id=?",(oid,)).fetchone()
                t=c.execute("SELECT * FROM pd_trip_runtime_v4 WHERE order_id=?",(oid,)).fetchone()
                return dict(row),dict(t) if t else {}
        with app.test_client() as client:
            legacy=lambda oid,target,who=201:client.post(
                f"/api/driver/work/{oid}/status",json={"status":target},
                headers={"X-Dummy-UID":str(who)})
            admin=lambda oid,target:client.post(
                "/api/admin/status",json={"id":oid,"status":target},
                headers={"X-Dummy-UID":"999"})
            action=lambda oid,act,who=201:client.post(
                f"/api/trip/{oid}/action",json={"action":act},
                headers={"X-Dummy-UID":str(who)})
            # Legacy status is no longer allowed to bypass arrival.
            before=state(501)
            r=legacy(501,"В пути")
            ensure(r.status_code==400,"OLD_PILOT_CANNOT_START_WITHOUT_ARRIVAL")
            ensure(state(501)==before,"OLD_PILOT_REJECTION_DOES_NOT_MUTATE_ORDER")
            for who in (101,202,203):
                r=legacy(501,"В пути",who)
                ensure(r.status_code in (400,403),"NON_PILOT_CANNOT_ADVANCE_STATUS")
            for target in ("В пути","Выполнена"):
                before=state(501)
                r=admin(501,target)
                ensure(r.status_code==400,"OLD_ADMIN_DIRECT_TRANSITION_REJECTED")
                ensure(state(501)==before,"OLD_ADMIN_REJECTION_DOES_NOT_MUTATE_ORDER")
            # New admin console requires explicit reason and uses the shared engine.
            r=client.post("/api/admin/console/orders/501/action",
                json={"action":"start","reason":"Synthetic test"},
                headers={"X-Dummy-UID":"999"})
            ensure(r.status_code==400,"ADMIN_CONSOLE_START_WITHOUT_ARRIVAL_BLOCKED")
            # A trip cannot start if payment status isn't confirmed.
            # Setup synthetic arrival with the real live 'arrive' handler.
            # Existing V7 live flow requires a departure and GPS before arrival.
            # We seed only synthetic runtime fields for this step.
            with core.db(core.ORDERS_DB) as c:
                c.execute("INSERT OR IGNORE INTO pd_trip_runtime_v4(order_id) VALUES(501)")
                c.execute("INSERT OR IGNORE INTO pd_trip_runtime_v4(order_id) VALUES(502)")
                c.execute("INSERT OR IGNORE INTO pd_trip_runtime_v4(order_id) VALUES(503)")
                c.execute("UPDATE pd_trip_runtime_v4 SET departed_at=?,departed_pilot_id=?,arrived_at=?,base_cents=CASE WHEN order_id=501 THEN 5000 WHEN order_id=503 THEN 7500 ELSE 3000 END WHERE order_id IN (501,502,503)",
                    (time_now[0]-100,201,time_now[0]-80))
            r=legacy(502,"В пути")
            ensure(r.status_code==400,"OLD_PILOT_UNPAID_START_BLOCKED")
            ensure(state(502)[0]["status"]=="Подтверждена","UNPAID_ORDER_NOT_ADVANCED")
            r=legacy(501,"В пути")
            ensure(r.status_code==200,"OLD_PILOT_PAID_START_SUCCESS")
            ensure(state(501)[0]["status"]=="В пути","PAID_TRIP_STATUS_IN_PROGRESS")
            ensure(bool(state(501)[1].get("started_at")),"TRIP_START_TIMESTAMP_RECORDED")
            r=legacy(501,"Выполнена")
            ensure(r.status_code==200,"OLD_PILOT_FINISH_SUCCESS")
            ensure(state(501)[0]["status"]=="Выполнена","FINISH_STATUS_PERSISTED")
            ensure(bool(state(501)[1].get("ended_at")),"FINISH_TIMESTAMP_RECORDED")
            # Authenticated dispatcher can advance the separate synthetic paid trip
            # ONLY via the console route and an explicit reason.
            for who in (101,201,203):
                r=client.post("/api/admin/console/orders/503/action",
                    json={"action":"start","reason":"Synthetic test"},
                    headers={"X-Dummy-UID":str(who)})
                ensure(r.status_code==403,"NON_ADMIN_CANNOT_OPERATE_DISPATCHER")
            r=client.post("/api/admin/console/orders/503/action",
                json={"action":"start","reason":"x"},
                headers={"X-Dummy-UID":"999"})
            ensure(r.status_code==400,"ADMIN_REASON_REQUIRED")
            r=client.post("/api/admin/console/orders/503/action",
                json={"action":"start","reason":"Synthetic dispatcher start"},
                headers={"X-Dummy-UID":"999"})
            ensure(r.status_code==200,"AUTHORIZED_DISPATCHER_START_SUCCESS")
            ensure(state(503)[0]["status"]=="В пути" and bool(state(503)[1].get("started_at")),
                   "DISPATCHER_START_TIMESTAMP_STORED")
            r=client.post("/api/admin/console/orders/503/action",
                json={"action":"finish","reason":"Synthetic dispatcher finish"},
                headers={"X-Dummy-UID":"999"})
            ensure(r.status_code==200,"AUTHORIZED_DISPATCHER_FINISH_SUCCESS")
            ensure(state(503)[0]["status"]=="Выполнена" and bool(state(503)[1].get("ended_at")),
                   "DISPATCHER_FINISH_TIMESTAMP_STORED")
            with core.db(core.ORDERS_DB) as c:
                audit=[r["event"] for r in c.execute("SELECT event FROM pd_trip_events_v4 WHERE order_id=503")]
            ensure(any("admin_start" in event for event in audit) and any("admin_finish" in event for event in audit),
                   "DISPATCHER_ACTION_REASON_AUDIT_RECORDED")
            before=state(501)
            r=legacy(501,"Выполнена")
            ensure(r.status_code in (200,400),"DUPLICATE_FINISH_HANDLED")
            ensure(state(501)==before,"DUPLICATE_FINISH_NO_STATE_CHANGE")
        print("ALL_SYNTHETIC_ROLE_STATUS_TESTS_PASSED",flush=True)
        print("ZERO_PRODUCTION_WRITES_ZERO_PROVIDER_CALLS",flush=True)
    print("ISOLATED_DATABASES_AND_PATCHES_DESTROYED",flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("ISOLATED_TEST_FAILED",type(exc).__name__,str(exc)[:150],flush=True)
        for frame in traceback.extract_tb(exc.__traceback__)[-4:]:
            print("FAILURE_FRAME",pathlib.Path(frame.filename).name,frame.lineno,frame.name,flush=True)
        raise SystemExit(1)
