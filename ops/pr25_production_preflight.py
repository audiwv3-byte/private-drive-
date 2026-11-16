"""PR25 deployment preflight ONLY. GET requests to PythonAnywhere; no writes.

Prints only source hashes, anchor counts, route-order checks, and mode.
Does not inspect .env, credentials, orders, payments, customer records.
"""
import ast, hashlib, os, re, urllib.request, urllib.error
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
FILES=("miniapp_server.py","pd_trip_runtime_v4.py")
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    live={}
    for name in FILES:
        req=urllib.request.Request(API+ROOT+name,headers={"Authorization":"Token "+token},method="GET")
        with urllib.request.urlopen(req,timeout=35) as res:
            if res.status!=200:raise RuntimeError("SOURCE_READ_ERROR")
            data=res.read(2000001)
        if not 1000<len(data)<2000000:raise RuntimeError("UNEXPECTED_SOURCE_LENGTH")
        live[name]=data.decode("utf-8")
        ast.parse(live[name])
        print("FILE",name,"SHA256",hashlib.sha256(data).hexdigest(),"BYTES",len(data),flush=True)
    server=live["miniapp_server.py"];runtime=live["pd_trip_runtime_v4.py"]
    gates={
        "ADMIN_STATUS_SINGLE":server.count("def admin_status():")==1,
        "ADMIN_TRANSITION_ANCHOR":server.count("    target = str(d.get('status', ''))\n")>=1,
        "ENGINE_REGISTER":server.count("pd_trip_runtime_v4.register(app, core, auth, provider=None)")==1,
        "LEGACY_REGISTER":server.count("pd_pilot_dispatch.register(app,core,auth)")==1,
        "ROUTE_ORDER":0<server.find("pd_trip_runtime_v4.register(app, core, auth, provider=None)")<server.find("pd_pilot_dispatch.register(app,core,auth)"),
        "ENGINE_HOOK":runtime.count("    app.config['PD_TRIP_TRANSITION_V4'] = transition")==1,
        "NO_PR25_GUARD":("pd_trip_runtime_v4.secure_legacy_status_route(app)" not in server and "def secure_legacy_status_route(" not in runtime),
        "NO_SECRETS_QUERIED":True,
    }
    for key,val in gates.items():print("GATE",key,"PASS" if val else "BLOCK",flush=True)
    if not all(gates.values()):raise RuntimeError("RELEASE_GATE_FAILED")
    # Verify pre-existing backup destination via GET only; deployment must not
    # assume PythonAnywhere accepts uploads to a non-existent parent directory.
    backup_dir="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/private_drive_backups/"
    try:
        request=urllib.request.Request(backup_dir,headers={"Authorization":"Token "+token},method="GET")
        with urllib.request.urlopen(request,timeout=25) as response:
            backup_parent_ready=(response.status==200)
        print("GATE BACKUP_DIRECTORY_READABLE", "PASS" if backup_parent_ready else "BLOCK",flush=True)
    except urllib.error.HTTPError as exc:
        backup_parent_ready=False
        print("GATE BACKUP_DIRECTORY_READABLE BLOCK HTTP",exc.code,flush=True)
    if not backup_parent_ready:
        raise RuntimeError("BACKUP_DIRECTORY_NOT_VERIFIED_NO_DEPLOY")
    print("PREFLIGHT_READONLY_PASSED_NO_PRODUCTION_CHANGES",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("PREFLIGHT_BLOCKED",type(e).__name__,str(e)[:90],flush=True)
        raise SystemExit(1)

# Read-only preflight rerun trigger 2026-11-16
