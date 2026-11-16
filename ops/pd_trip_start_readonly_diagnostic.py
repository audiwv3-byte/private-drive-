"""Inspect production-only trip start and status guards with GET requests.

Prints only selected trip-UI and guard code lines, never DB records or secrets.
Does not change PythonAnywhere, orders, payments or runtime configuration.
"""
import ast, hashlib, os, re, urllib.request, urllib.error
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
RAW="https://raw.githubusercontent.com/audiwv3-byte/private-drive-/main/"
FILES=["miniapp_server.py","pd_trip_runtime_v4.js","pd_trip_runtime_v4.py","pd_pilot_dispatch.py","pd_admin_console_v4.py"]
def fetch(url,token=None):
    h={"Authorization":"Token "+token} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url,method="GET",headers=h),timeout=35) as r:
        return r.read(2000001).decode("utf-8")
def summary(p,live,github):
    print("SOURCE",p,"IDENTICAL" if live==github else "DIFFERENT",
          "LIVE_SHA",hashlib.sha256(live.encode()).hexdigest()[:16],flush=True)
def selected(title,lines,pattern,before=1,after=2,limit=9):
    found=[i for i,line in enumerate(lines) if re.search(pattern,line)]
    print("SECTION",title,"matches",len(found),flush=True)
    used=set()
    for i in found[:limit]:
        for j in range(max(i-before,0),min(i+after+1,len(lines))):
            if j not in used:
                used.add(j)
                # Safely selected route and guard code only; never print credentials.
                print("LINE",j+1,lines[j][:230].strip(),flush=True)
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    live={}
    for p in FILES:
        live[p]=fetch(API+ROOT+p,token)
        upstream=fetch(RAW+p)
        summary(p,live[p],upstream)
    js=live["pd_trip_runtime_v4.js"].splitlines()
    trip=live["pd_trip_runtime_v4.py"].splitlines()
    server=live["miniapp_server.py"].splitlines()
    disp=live["pd_pilot_dispatch.py"].splitlines()
    admin=live["pd_admin_console_v4.py"].splitlines()
    selected("UI_ACTION_CONTROL",js,r"Начать поездку|Прибыл|/action|async function action|r\.role==='pilot'|arrived_at\?",0,1,11)
    selected("TRIP_REGISTER_AND_ROUTES",trip,r"def register\(|@app\.post\('/api/trip|def pd_v4_action|def transition",0,2,14)
    selected("TRIP_PILOT_AUTH_AND_START",trip,r"def pilot\(|def transition\(|if action == 'arrive'|elif action == 'start'|elif action == 'finish'|r\['payment_status'\]|status='В пути'|def legacy_status|/api/driver/work/<int:oid>/status|PD_TRIP_TRANSITION_V4",2,6,16)
    selected("SERVER_ADMIN_AND_PLUGIN_ORDER",server,r"import pd_trip_runtime_v4|pd_trip_runtime_v4\.register|import pd_pilot_dispatch|pd_pilot_dispatch\.register|import pd_admin_console_v4|pd_admin_console_v4\.register|def admin_status\(|target == 'В пути'|VALID_STATUSES|allowed",1,3,20)
    selected("DISPATCH_LEGACY_STATUS",disp,r"def status\(|@app\.post\('/api/driver/work|allowed=|UPDATE orders SET status=|payment_status",1,4,10)
    selected("ADMIN_CONSOLE_GUARD",admin,r"def pd_admin_console_action|PD_TRIP_TRANSITION_V4|/api/admin/console/orders/<int:oid>/action|def pd_admin_console_assignment_guard",2,5,6)
    for title, data, a, b in [
        ("LIVE_UI_GPS_START",js,21,43),
        ("LIVE_UI_STAGE_BUTTONS",js,152,173),
        ("LIVE_SERVER_ADMIN_STATUS",server,408,449),
        ("LIVE_TRIP_TRANSITION",trip,264,335),
        ("LIVE_TRIP_LEGACY_REPLACEMENT",trip,400,437),
    ]:
        print("DETAIL_BLOCK",title,flush=True)
        for idx in range(a-1,min(b,len(data))):
            line=data[idx]
            if any(word in line.lower() for word in ("token","secret","api_key","password","authorization")):
                print("DETAIL_LINE",idx+1,"[REDACTED]",flush=True)
            else:
                print("DETAIL_LINE",idx+1,line[:260],flush=True)
    engine_reg=live["miniapp_server.py"].find("pd_trip_runtime_v4.register(app")
    legacy_reg=live["miniapp_server.py"].find("pd_pilot_dispatch.register(app")
    print("REGISTRATION_ORDER", "LEGACY_REGISTERED_AFTER_TRIP_ENGINE" if 0<=engine_reg<legacy_reg else "REVIEW_REQUIRED",flush=True)
    print("LEGACY_ROUTE_VIEWS_OVERRIDDEN", "NO_EVIDENCE_OF_POST_REGISTER_OVERRIDE" if engine_reg<legacy_reg else "REVIEW_REQUIRED",flush=True)
    print("READ_ONLY_NO_ORDER_OR_PAYMENT_DATA_ACCESSED",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("ERROR",type(e).__name__,str(e)[:110],flush=True)
        raise SystemExit(1)
