"""Post-deploy PRIVATE DRIVE source audit. PythonAnywhere API GET only.
No environment/secrets, orders, databases, write requests, payment calls.
Outputs source fingerprints and structural findings, not source contents.
"""
import ast,hashlib,os,re,urllib.error,urllib.request
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES=("miniapp_server.py","pd_trip_runtime_v4.py","pd_paypal_checkout.py",
       "pd_trip_runtime_v4.js","pd_pilot_cabinet_v4.js",
       "pd_admin_console_v4.js","miniapp/templates/index.html")
def fetch(name,token):
    request=urllib.request.Request(API+ROOT+name,method="GET",headers={"Authorization":"Token "+token})
    try:
        with urllib.request.urlopen(request,timeout=35) as resp:
            raw=resp.read(2000001)
            return resp.status,raw
    except urllib.error.HTTPError as exc:
        return exc.code,b""
def check(label,ok):
    print("CHECK",label,"PASS" if ok else "NOT_CONFIRMED",flush=True)
def main():
    tok=os.environ.get("PYTHONANYWHERE_API_TOKEN","").strip()
    tok=re.sub(r"^Token\s+","",tok,flags=re.I)
    if not tok:raise RuntimeError("NO_API_TOKEN")
    print("MODE GET_ONLY_NO_SECRETS_NO_ORDERS_NO_PAYMENTS",flush=True)
    docs={}
    for name in FILES:
        code,raw=fetch(name,tok)
        print("FILE",name,"HTTP",code,"BYTES",len(raw),"SHA256_16",hashlib.sha256(raw).hexdigest()[:16],flush=True)
        docs[name]=raw.decode("utf8") if code==200 else ""
    srv=docs["miniapp_server.py"]; runtime=docs["pd_trip_runtime_v4.py"]
    paypal=docs["pd_paypal_checkout.py"]; html=docs["miniapp/templates/index.html"]
    tripjs=docs["pd_trip_runtime_v4.js"]
    for n in ("miniapp_server.py","pd_trip_runtime_v4.py","pd_paypal_checkout.py"):
        try:ast.parse(docs[n]);check("PYTHON_SYNTAX_"+n,True)
        except (SyntaxError,TypeError):check("PYTHON_SYNTAX_"+n,False)
    # The prior two expected SHA256 are published in the approved PR25 deployment log.
    deployed={
       "miniapp_server.py":"f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4",
       "pd_trip_runtime_v4.py":"424b6950c9006d684e70ed2014f53f1340c6c1627169920c7e1c4fc2ad43e0b0"}
    for name,expected in deployed.items():
        status,raw=fetch(name,tok)
        check("PR25_DEPLOYED_SHA_MATCH_"+name,status==200 and hashlib.sha256(raw).hexdigest()==expected)
    check("TRIP_LEGACY_GUARD", "pd_trip_runtime_v4.secure_legacy_status_route(app)" in srv)
    check("TRIP_AUTH_HOOK","PD_TRIP_AUTH_V4" in runtime)
    check("PAYPAL_MODULE_PRESENT",bool(paypal))
    check("PAYPAL_MODULE_SANDBOX_ONLY", "if mode == 'live':" in paypal and "return None" in paypal)
    check("PAYPAL_SERVER_IMPORT", "import pd_paypal_checkout" in srv)
    check("PAYPAL_CREATE_ROUTE", "/paypal/create" in srv)
    check("PAYPAL_CAPTURE_ROUTE", "/paypal/capture" in srv)
    check("PAYPAL_CONFIG_ROUTE", "/paypal/config" in srv)
    check("PAYPAL_BUTTON_UI", "paypalNotice" in html or "pdPaypalSdk" in html)
    check("GPS_WATCH_POSITION", "watchPosition(" in tripjs)
    check("GPS_CLEAR_WATCH", "clearWatch(" in tripjs)
    check("TRIP_START_FINISH_ACTIONS", "action('finish')" in tripjs and ("'start'" in tripjs))
    check("PILOT_UI_PRESENT",bool(docs["pd_pilot_cabinet_v4.js"]))
    check("DISPATCHER_UI_PRESENT",bool(docs["pd_admin_console_v4.js"]))
    # Only read-only remote inspection; does not tell us actual active env value.
    print("PAYPAL_ACTIVE_MODE UNKNOWN_NO_ENV_READ",flush=True)
    print("TELEGRAM_AUTHENTICATED_E2E NOT_TESTED",flush=True)
    print("PAYPAL_SANDBOX_TRANSACTION NOT_ATTEMPTED",flush=True)
    print("NO_PRODUCTION_MUTATIONS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("AUDIT_ERROR",type(exc).__name__,flush=True)
        raise SystemExit(1)
