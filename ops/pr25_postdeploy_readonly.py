"""PR25 independent postdeployment check. PythonAnywhere GET only, no modifications."""
import ast
import hashlib
import os
import urllib.request
import urllib.error

API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
EXPECTED={
  "miniapp_server.py":"f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4",
  "pd_trip_runtime_v4.py":"424b6950c9006d684e70ed2014f53f1340c6c1627169920c7e1c4fc2ad43e0b0",
}
token=os.environ["PYTHONANYWHERE_API_TOKEN"].strip()
if token.lower().startswith("token "):token=token[6:].strip()
assert token,"MISSING_TOKEN"
files={}
for name,expected in EXPECTED.items():
    req=urllib.request.Request(API+ROOT+name,headers={"Authorization":"Token "+token},method="GET")
    with urllib.request.urlopen(req,timeout=40) as response:
        assert response.status==200
        raw=response.read(2000000)
    actual=hashlib.sha256(raw).hexdigest()
    assert actual==expected, "LIVE_SHA_MISMATCH_"+name
    files[name]=raw.decode("utf-8")
    ast.parse(files[name])
    print("LIVE_PATCH_SHA256_VERIFIED",name,actual,flush=True)
server=files["miniapp_server.py"]
trip=files["pd_trip_runtime_v4.py"]
assert server.count("pd_trip_runtime_v4.secure_legacy_status_route(app)")==1,"ROUTE_BINDING_MISMATCH"
assert trip.count("def secure_legacy_status_route(app):")==1,"TRANSITION_HELPER_MISMATCH"
assert "app.config['PD_TRIP_AUTH_V4'] = auth" in trip,"AUTH_GUARD_MISSING"
assert "if target in ('В пути', 'Выполнена'):" in server,"ADMIN_GUARD_MISSING"
print("PR25_RUNTIME_GUARDS_PRESENT",flush=True)
domain="https://wilsonpark.pythonanywhere.com"
for path,expected in (("/",200),("/privacy",200),("/legal",200)):
    with urllib.request.urlopen(urllib.request.Request(domain+path,method="GET"),timeout=30) as resp:
        assert resp.status==expected,"PAGE_HEALTH_BAD_"+path
    print("PUBLIC_ROUTE_OK",path,flush=True)
for path in ("/api/orders","/api/admin/console/orders"):
    req=urllib.request.Request(domain+path,method="GET")
    try:
        with urllib.request.urlopen(req,timeout=30) as resp:
            status=resp.status
    except urllib.error.HTTPError as exc:
        status=exc.code
    assert status in (401,403),"PRIVATE_API_EXPOSED_"+path
    print("PRIVATE_ROUTE_DENIED",path,status,flush=True)
print("PR25_POSTDEPLOY_INDEPENDENT_READONLY_PASSED",flush=True)
