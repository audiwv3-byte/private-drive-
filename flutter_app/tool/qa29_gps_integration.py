"""QA29 localhost fixture and Android emulator integration; synthetic identities only."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

PORT = 18729
BASE = f"http://127.0.0.1:{PORT}"
DSN = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
PILOT = "qa29-synthetic-pilot-session-not-a-real-credential"
TG = "qa25-synthetic-qa29"
CSRF = "qa26-synthetic-qa29"
PACKAGE = "lt.privatedrive.private_drive.gps_qa29"
OID_FILE = Path(os.environ.get("QA29_ORDER_FILE", "/tmp/qa29-order-id"))

def signed(uid):
    values = {"auth_date":str(int(time.time())), "user":json.dumps({"id":uid})}
    key = hmac.new(b"WebAppData", TG.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(key, "\n".join(k+"="+v for k,v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data":urllib.parse.urlencode(values)}

def serve(server_dir):
    import psycopg
    sys.path.insert(0, str(server_dir.resolve()))
    os.chdir(server_dir)
    from pd_native_auth_postgres_http import initialize_database
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from werkzeug.serving import run_simple
    if os.environ.get("PD_AUTH_TEST_DATABASE_URL") != DSN:
        raise RuntimeError("Fresh isolated local database required")
    initialize_database(DSN)
    now = int(time.time())
    with psycopg.connect(DSN, autocommit=True) as db:
        for name in ("native_auth_session_functions.sql","native_dispatch_orders.sql","native_pilot_identity.sql","qa26_pilot_assignment.sql","qa27_pilot_gps.sql"):
            db.execute((Path("migrations") / name).read_text())
        db.execute("CREATE ROLE qa29_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa29_api")
        db.execute("GRANT SELECT, INSERT ON public.pd_dispatch_orders, public.pd_native_order_owners, public.pd_telegram_order_owners TO qa29_api")
        for signature in ("pd_validate_native_session(text,bigint)","pd_pilot_assignment_candidates(bigint)","pd_assign_native_order(uuid,text,text,bigint)","pd_native_pilot_order_state(text,bigint)","pd_native_pilot_trip_action(text,text,text,bigint)","pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint)","pd_qa27_dispatch_gps(uuid,bigint)"):
            db.execute("GRANT EXECUTE ON FUNCTION public."+signature+" TO qa29_api")
        db.execute("INSERT INTO native_auth_users VALUES ('qa29-pilot','phone','qa29-pilot',0)")
        db.execute("INSERT INTO native_auth_roles VALUES ('qa29-pilot','pilot')")
        db.execute("INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,'qa29-pilot',%s,%s)",(hashlib.sha256(PILOT.encode()).hexdigest(),now,now+7200))
        db.execute("INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at) VALUES ('qa29-check','qa29-pilot','approved',%s,%s,%s)",(now-10,now+7200,now-5))
    api_dsn=DSN.replace("postgres:isolated-test@", "qa29_api:synthetic-api@")
    os.environ.update({"PD_QA25_WSGI":"1","PD_QA26_ASSIGNMENT":"1","PD_QA27_GPS":"1","PD_QA26_CSRF":CSRF,"PD_QA25_TELEGRAM_TEST_TOKEN":TG,"PD_QA25_PASSENGERS":"101,102","PD_QA25_ADMINS":"201","PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_DISPATCH_STAGING_ONLY":"1","PD_PAYMENT_MODE":"disabled","PD_DISPATCH_PERSISTENT_QUEUE":"1","PD_NATIVE_PILOT_ASSIGNMENT":"1","PD_DISPATCH_ORDERS_DATABASE_URL":api_dsn,"PD_PILOT_ASSIGNMENT_DATABASE_URL":api_dsn})
    from pd_qa25_wsgi import create_application
    app=create_application()
    client=Client(app,Response)
    body={"request_key":uuid.uuid4().hex,"origin":"Synthetic A","destination":"Synthetic B","trip_date":"2027-01-01","trip_time":"12:00"}
    order=client.post("/api/order",json=body,headers=signed(101))
    assert order.status_code==200,order.json
    oid=order.json["order_id"]
    assigned=client.post("/dispatch/orders/"+oid+"/assign",data={"pilot_id":"qa29-pilot","csrf":CSRF},headers=signed(201))
    assert assigned.status_code==200,assigned.json
    OID_FILE.write_text(oid)
    print("QA29 fixture: assigned synthetic trip",flush=True)
    run_simple("127.0.0.1",PORT,app,threaded=True,use_reloader=False,use_debugger=False)

def request(path, method="GET", body=None, headers=None):
    h=dict(headers or {})
    data=None
    if body is not None:
        h["Content-Type"]="application/json"
        data=json.dumps(body).encode()
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method)
    with urllib.request.urlopen(req,timeout=5) as response:
        return json.load(response)

def adb(*args):
    return subprocess.check_output(["adb",*args],text=True,timeout=20)

def tap_text(label, deadline=45):
    end=time.monotonic()+deadline
    while time.monotonic()<end:
        adb("shell","uiautomator","dump","/sdcard/qa29.xml")
        raw=adb("shell","cat","/sdcard/qa29.xml")
        root=ET.fromstring(raw)
        import re
        for node in root.iter("node"):
            if label in (node.get("text","")+" "+node.get("content-desc","")):
                nums=list(map(int,re.findall(r"\d+",node.get("bounds",""))))
                if len(nums)==4:
                    adb("shell","input","tap",str((nums[0]+nums[2])//2),str((nums[1]+nums[3])//2))
                    return
        time.sleep(1)
    raise AssertionError("UI control not found: "+label)

def poll(fn, predicate, description, seconds=60):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=fn()
            if predicate(value):
                print("PASS:",description,flush=True)
                return value
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise AssertionError("Timed out: "+description)

def emulator(apk):
    oid=OID_FILE.read_text().strip()
    read="/dispatch/orders/"+oid+"/gps"
    gps=lambda: request(read,headers=signed(201))
    bearer={"Authorization":"Bearer "+PILOT}
    assert gps()=={"available":False}
    adb("install","-r",str(apk))
    adb("reverse","tcp:18729","tcp:18729")
    for permission in ("ACCESS_COARSE_LOCATION","ACCESS_FINE_LOCATION","POST_NOTIFICATIONS"):
        adb("shell","pm","grant",PACKAGE,"android.permission."+permission)
    adb("shell","cmd","location","set-location-enabled","true")
    adb("shell","am","start","-W","-n",PACKAGE+"/lt.privatedrive.private_drive.MainActivity")
    tap_text("Передавать GPS диспетчеру")
    def fake_fix(lat,lon):
        adb("emu","geo","fix",str(lon),str(lat))
    def matches(g,lat,lon):
        return g.get("available") is True and abs(g["latitude"]-lat)<0.01 and abs(g["longitude"]-lon)<0.01
    fake_fix(1.25,2.5)
    first=poll(gps,lambda g:matches(g,1.25,2.5),"foreground fix persisted and visible to dispatcher")
    adb("shell","input","keyevent","KEYCODE_HOME")
    adb("shell","input","keyevent","KEYCODE_SLEEP")
    time.sleep(6)
    fake_fix(1.35,2.6)
    poll(gps,lambda g:matches(g,1.35,2.6) and g["captured_at"]>first["captured_at"],"new fix received with app backgrounded and screen asleep")
    for action in ("approach","start","finish"):
        result=request("/native-pilot-orders","PATCH",{"order_id":oid,"action":action},bearer)
        assert result["payment_mode"]=="disabled",result
    assert result["status"]=="finished"
    poll(gps,lambda g:g=={"available":False},"finished trip no longer exposes GPS")
    time.sleep(12)
    fake_fix(1.45,2.7)
    time.sleep(8)
    assert gps()=={"available":False}
    import psycopg
    with psycopg.connect(DSN) as db:
        assert db.execute("SELECT count(*) FROM public.pd_qa27_gps").fetchone()[0]==0
    print("PASS: no retained coordinates or accepted post-finish updates",flush=True)
    adb("shell","input","keyevent","KEYCODE_WAKEUP")
    adb("shell","am","force-stop",PACKAGE)

if __name__=="__main__":
    if sys.argv[1]=="serve": serve(Path(sys.argv[2]))
    elif sys.argv[1]=="emulator": emulator(Path(sys.argv[2]))
    else: raise SystemExit("usage: serve <QA27 checkout> | emulator <APK>")
