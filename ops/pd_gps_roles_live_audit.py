"""GET-only live-vs-reviewed audit: GPS, trip status and role controls.

No app mutations, no auth tokens sent to the app itself, no private records read.
All downloads are only public UI assets or known source files via authenticated
PythonAnywhere file GET API. Only structural flags and hashes leave this process.
"""
import ast,hashlib,os,re,urllib.error,urllib.request

BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
REPO="https://raw.githubusercontent.com/audiwv3-byte/private-drive-/main/"
PATHS=("miniapp_server.py","pd_trip_runtime_v4.js","pd_pilot_cabinet_v4.js","pd_admin_console_v4.js")
def get(url,token=None):
    headers={"Authorization":"Token "+token} if token else {}
    request=urllib.request.Request(url,method="GET",headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            return response.status,response.read(2000001)
    except urllib.error.HTTPError as error:
        return error.code,b""
def sha(data):return hashlib.sha256(data).hexdigest()[:16]
def check(name,value):
    print(name,"OK" if value else "REVIEW_REQUIRED",flush=True)
def main():
    token=os.environ.get("PYTHONANYWHERE_API_TOKEN","").strip()
    token=re.sub(r"^Token\s+","",token,flags=re.I)
    if not token:raise ValueError("Missing audit-only token")
    print("AUDIT_MODE READ_ONLY_LIVE_VS_GITHUB",flush=True)
    live={}
    for path in PATHS:
        code,raw=get(BASE+ROOT+path,token)
        gh_status,gh_raw=get(REPO+path)
        print("FILE",path,"LIVE_HTTP",code,"GITHUB_HTTP",gh_status,flush=True)
        if code==200 and gh_status==200:
            print("SOURCE_MATCH",path,"MATCH" if raw==gh_raw else "DIFFERENT",
                  "live_sha256",sha(raw),"github_sha256",sha(gh_raw),flush=True)
        live[path]=raw.decode("utf-8") if code==200 else ""
    server=live["miniapp_server.py"]
    trip=live["pd_trip_runtime_v4.js"]
    pilot=live["pd_pilot_cabinet_v4.js"]
    admin=live["pd_admin_console_v4.js"]
    if server:
        try:ast.parse(server);check("LIVE_SERVER_PYTHON_SYNTAX",True)
        except SyntaxError:check("LIVE_SERVER_PYTHON_SYNTAX",False)
    markers={
      "GPS_WATCH_POSITION":"watchPosition(" in trip,
      "GPS_STOP_POSITION":"clearWatch(" in trip,
      "GPS_HIDE_WHEN_BACKGROUND":"visibilitychange" in trip and "stopPosition()" in trip,
      "GPS_DRIVER_ROLE_GUARD":"r.role==='pilot'&&live" in trip,
      "GPS_LOCATION_ENDPOINT":"/location" in trip,
      "TRIP_ACTION_ARRIVE":"action('arrive')" in trip or "'arrive':'" in trip or "?'start':'arrive'" in trip,
      "TRIP_ACTION_START":"?'start':'arrive'" in trip,
      "TRIP_ACTION_FINISH":"action('finish')" in trip,
      "PASSENGER_NO_PILOT_BUTTONS":"r.role==='pilot'" in trip,
      "PILOT_WORK_API":"/api/driver/work" in pilot,
      "PILOT_ROLE_GATE":"pdPilotEnabled" in pilot and "pdEnterPilot=function" in pilot,
      "ADMIN_ORDER_LIST":"/api/admin/console/orders" in admin,
      "ADMIN_ASSIGN_PILOT":"pdAssignPilot(" in admin,
      "ADMIN_TRIP_ACTION_CONFIRM":"actionDialog(" in admin,
      "SERVER_TELEGRAM_AUTH":"def auth():" in server,
      "SERVER_ORDER_GET":"/api/orders" in server,
      "SERVER_ADMIN_ORDER_GET":"/api/admin/orders" in server,
    }
    for k,v in markers.items():check(k,v)
    # Detailed classification without printing source code or app data.
    trip_actions={
        "START_ACTION_CALL": bool(re.search(r"action\\s*\\(\\s*['\\\"]start['\\\"]",trip)),
        "START_ACTION_REQUEST_LITERAL": "start" in trip and "/action" in trip,
        "ARRIVE_ACTION_CALL": bool(re.search(r"action\\s*\\(\\s*['\\\"]arrive['\\\"]",trip)),
        "CONDITIONAL_START_TRIGGER": bool(re.search(r"arrived_at.{0,130}start",trip,re.S)),
        "START_LABEL": "Начать поездку" in trip,
        "IN_ROUTE_LABEL": "В пути" in trip,
        "ARRIVED_AT_FIELD": "arrived_at" in trip,
    }
    for name,check_value in trip_actions.items():check(name,check_value)
    present=all(bool(live[p]) for p in PATHS)
    print("LIVE_SOURCE_FILES_ALL_PRESENT",present,flush=True)
    print("NOTE_SERVER_SIDE_TRIP_ROLE_GUARDS_NOT_EXECUTED",flush=True)
    print("NOTE_ROLE_AND_STATUS_BEHAVIOR_NOT_PROVEN_BY_STATIC_SOURCE",flush=True)
    print("NO_ORDERS_PAYMENTS_OR_LIVE_WRITES",flush=True)
    if not present:raise SystemExit(2)
if __name__=="__main__":
    try:main()
    except Exception as error:
        print("AUDIT_ERROR",type(error).__name__,flush=True)
        raise SystemExit(1)
