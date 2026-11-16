"""Independent post-deployment audit. GET-only; no secrets, DB or payment calls."""
import os,re,urllib.request,urllib.error,ast,hashlib
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
BASE="https://wilsonpark.pythonanywhere.com"
def get(url,token=None):
    h={"Authorization":"Token "+token} if token else {}
    req=urllib.request.Request(url,headers=h,method="GET")
    try:
        with urllib.request.urlopen(req,timeout=35) as r:
            return r.status,r.headers,r.read(2000001)
    except urllib.error.HTTPError as e:
        return e.code,e.headers,e.read(100000)
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    checks={}
    source={}
    for file in ("miniapp_server.py","miniapp/templates/index.html","pd_paypal_checkout.py"):
        status,headers,raw=get(API+ROOT+file,token)
        checks["FILE_"+file]=(status==200 and len(raw)>1000)
        source[file]=raw.decode("utf-8")
        print("LIVE_FILE",file,"OK" if checks["FILE_"+file] else "FAILED",
              "sha256",hashlib.sha256(raw).hexdigest()[:16],flush=True)
    python=source["miniapp_server.py"]
    html=source["miniapp/templates/index.html"]
    ast.parse(python)
    checks["PAYPAL_MODE_PROGRAMMATICALLY_DISABLED"] = "PD_PAYPAL_DEPLOY_GATE = False" in python and "if not PD_PAYPAL_DEPLOY_GATE:" in python
    checks["PAYPAL_API_ROUTES"] = all(python.count(f'"/paypal/{suffix}"')>=0 for suffix in ("config","create","capture")) and all("/paypal/"+suffix in python for suffix in ("config","create","capture"))
    checks["PAYPAL_FRONTEND_HANDLER"] = "async function paypalNotice()" in html and "p.paypal_available" in html
    checks["PAYPAL_ACCESS_REQUIREMENTS"] = "paypal_check_booking(conn, oid, uid" in python and "uid, _ = auth()" in python
    for name in ("PAYPAL_MODE_PROGRAMMATICALLY_DISABLED","PAYPAL_API_ROUTES","PAYPAL_FRONTEND_HANDLER","PAYPAL_ACCESS_REQUIREMENTS"):
        print(name, "OK" if checks[name] else "FAILED",flush=True)
    for path in ("/","/privacy","/legal"):
        code,headers,payload=get(BASE+path)
        checks["PUBLIC_"+path]=code==200 and bool(payload)
        print("PUBLIC",path,code,"OK" if checks["PUBLIC_"+path] else "FAILED",flush=True)
    for path in ("/api/orders","/api/admin/orders","/api/payment/1","/api/payment/1/paypal/config"):
        code,headers,payload=get(BASE+path)
        checks["ANON_"+path]=code in (401,403) and b'"orders":[' not in payload
        print("ANON_DENIED",path,code,"OK" if checks["ANON_"+path] else "FAILED",flush=True)
    if all(checks.values()):
        print("POSTDEPLOY_READONLY_VERIFIED",flush=True)
        print("PAYPAL_PAYMENT_PROVIDER_NOT_CALLED",flush=True)
    else:
        print("POSTDEPLOY_AUDIT_BLOCKED",sum(not x for x in checks.values()),flush=True)
        raise SystemExit(1)
if __name__=="__main__":main()
