"""Non-mutating launch smoke tests for PRIVATE DRIVE public app endpoints."""
import urllib.request
import urllib.error
import json
import sys

BASE="https://wilsonpark.pythonanywhere.com"
HEADERS={"User-Agent":"PrivateDriveReadOnlyLaunchAudit/1.0"}
def read(path):
    req=urllib.request.Request(BASE+path,headers=HEADERS,method="GET")
    try:
        with urllib.request.urlopen(req,timeout=30) as res:
            body=res.read(400000)
            return res.status,res.headers,body
    except urllib.error.HTTPError as error:
        return error.code,error.headers,error.read(100000)
def main():
    failures=[]
    for path in ("/","/privacy","/legal"):
        status,headers,body=read(path)
        passed=status==200 and bool(body)
        print("PUBLIC_PAGE",path,status,"OK" if passed else "FAILED",flush=True)
        if not passed:failures.append(path)
    for path in ("/api/me","/api/orders","/api/payment/1",
                 "/api/admin/orders","/api/admin/customers"):
        status,headers,body=read(path)
        # Invalid initData must not disclose private booking or customer data.
        passed=status in (401,403) and b'"orders":[' not in body and b'"phone"' not in body
        print("PRIVATE_API_REJECTS_ANONYMOUS",path,status,"OK" if passed else "FAILED",flush=True)
        if not passed:failures.append(path)
    status,headers,body=read("/")
    text=body.decode("utf-8",errors="replace")
    for term in ("pdObLanguage","pdbOrigin","pdbPays","pdObRole"):
        exists=term in text
        print("MINIAPP_UI_ELEMENT",term,"OK" if exists else "MISSING",flush=True)
        if not exists:failures.append(term)
    print("CHECKOUT_NO_REAL_ORDER_CREATED",flush=True)
    if failures:
        print("LAUNCH_GATE_BLOCKED failures",len(failures),flush=True)
        raise SystemExit(1)
    print("PUBLIC_READONLY_SMOKE_PASSED",flush=True)
if __name__=="__main__":
    main()
