"""PR #25 guarded live-source overlay simulation, never touches PythonAnywhere.

Reads only two current production sources via PythonAnywhere GET and the
reviewed PR25 helper from this checkout. Applies 3 tiny changes to temporary
copies, syntax checks, tests the adapter, and deletes copies automatically.
Never reads credentials, booking records, payment records, or .env.
"""
import ast
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

REPOSITORY=pathlib.Path(__file__).resolve().parents[1]
API="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
TARGETS=("miniapp_server.py","pd_trip_runtime_v4.py")

def get_live(name,token):
    url=API+ROOT+name
    req=urllib.request.Request(url,method="GET",headers={"Authorization":"Token "+token})
    with urllib.request.urlopen(req,timeout=45) as response:
        if response.status!=200:raise RuntimeError("READ_STATUS_BAD")
        raw=response.read(2000001)
        if not 1000<len(raw)<2000000:raise RuntimeError("SOURCE_SIZE_UNEXPECTED")
        return raw.decode("utf-8")

def exactly_once(source,old,new,tag):
    hits=source.count(old)
    print("PATCH_ANCHOR",tag,"COUNT",hits,flush=True)
    if hits!=1:raise RuntimeError("ANCHOR_NOT_UNIQUE_"+tag)
    return source.replace(old,new,1)

def add_admin_guard(source):
    tree=ast.parse(source)
    matches=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=="admin_status"]
    if len(matches)!=1:raise RuntimeError("ADMIN_HANDLER_COUNT")
    node=matches[0]
    raw_lines=source.splitlines(keepends=True)
    fragment="".join(raw_lines[node.lineno-1:node.end_lineno])
    anchor="    target = str(d.get('status', ''))\n"
    added=("    if target in ('В пути', 'Выполнена'):\n"
           "        raise ValueError('Используй защищённую диспетчерскую с причиной действия и проверками V4')\n")
    if "защищённую диспетчерскую" in fragment:raise RuntimeError("ADMIN_ALREADY_PATCHED")
    fragment=exactly_once(fragment,anchor,anchor+added,"ADMIN_STATUS_GUARD")
    result="".join(raw_lines[:node.lineno-1])+fragment+"".join(raw_lines[node.end_lineno:])
    ast.parse(result)
    return result

def secure_trip_runtime(source):
    reviewed=(REPOSITORY/"pd_trip_runtime_v4.py").read_text(encoding="utf-8")
    node=ast.parse(reviewed)
    matches=[n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=="secure_legacy_status_route"]
    if len(matches)!=1:raise RuntimeError("PR25_HELPER_NOT_FOUND")
    lines=reviewed.splitlines(keepends=True)
    func="".join(lines[matches[0].lineno-1:matches[0].end_lineno])
    if "def secure_legacy_status_route(" in source:raise RuntimeError("LIVE_HELPER_ALREADY_PRESENT")
    source=exactly_once(source,"    app.config['PD_TRIP_TRANSITION_V4'] = transition",
        "    app.config['PD_TRIP_TRANSITION_V4'] = transition\n    app.config['PD_TRIP_AUTH_V4'] = auth",
        "TRIP_AUTH_CONFIG")
    return source.rstrip()+"\n\n\n"+func+"\n"

def secure_server_tail(source):
    call="pd_trip_runtime_v4.secure_legacy_status_route(app)"
    if call in source:raise RuntimeError("LIVE_ROUTE_GUARD_ALREADY_PRESENT")
    if "pd_pilot_dispatch.register(app,core,auth)" not in source:raise RuntimeError("DISPATCH_REGISTER_UNEXPECTED")
    if "pd_trip_runtime_v4.register(app, core, auth, provider=None)" not in source:raise RuntimeError("TRIP_REGISTER_UNEXPECTED")
    # Must be the final module-level statement, AFTER all route modules.
    return source.rstrip()+"\n\n# PR25: secure old pilot status after every route registration.\n"+call+"\n"

def verify_ast(server,trip):
    ast.parse(server)
    tree=ast.parse(trip)
    helper=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="secure_legacy_status_route"]
    if len(helper)!=1:raise RuntimeError("HELPER_NOT_UNIQUE")
    ast_server=ast.parse(server)
    status=[n for n in ast_server.body if isinstance(n,ast.FunctionDef) and n.name=="admin_status"]
    if len(status)!=1:raise RuntimeError("ADMIN_STATUS_COUNT")
    handler="".join(server.splitlines(keepends=True)[status[0].lineno-1:status[0].end_lineno])
    if "if target in ('В пути', 'Выполнена'):" not in handler:raise RuntimeError("ADMIN_GUARD_MISSING")
    if not isinstance(ast_server.body[-1],ast.Expr):raise RuntimeError("CALL_NOT_FINAL")
    last=ast_server.body[-1].value
    if not isinstance(last,ast.Call) or not isinstance(last.func,ast.Attribute) or last.func.attr!="secure_legacy_status_route":
        raise RuntimeError("TAIL_GUARD_NOT_FINAL")
    print("AST_GUARDS_OK",flush=True)

def main():
    token=os.environ.get("PYTHONANYWHERE_API_TOKEN","").strip()
    token=re.sub(r"^Token\s+","",token,flags=re.I)
    if not token:raise RuntimeError("API_TOKEN_NOT_AVAILABLE")
    source={}
    print("MODE PYTHONANYWHERE_GET_ONLY_LOCAL_TEMP_FILES",flush=True)
    for name in TARGETS:
        source[name]=get_live(name,token)
        print("LIVE_SOURCE",name,"BYTES",len(source[name].encode()),"SHA256",
              hashlib.sha256(source[name].encode()).hexdigest()[:16],flush=True)
    server=add_admin_guard(source["miniapp_server.py"])
    trip=secure_trip_runtime(source["pd_trip_runtime_v4.py"])
    server=secure_server_tail(server)
    verify_ast(server,trip)
    with tempfile.TemporaryDirectory(prefix="pd-pr25-live-overlay-") as temp:
        path=pathlib.Path(temp)
        (path/"miniapp_server.py").write_text(server,encoding="utf-8")
        (path/"pd_trip_runtime_v4.py").write_text(trip,encoding="utf-8")
        for name in TARGETS:
            subprocess.run([sys.executable,"-m","py_compile",str(path/name)],check=True,
                capture_output=True)
        print("TEMPORARY_SOURCE_COMPILE_PASSED",flush=True)
        # Unit test only loads temporary trip engine; no production DB or network calls.
        env=os.environ.copy()
        env["PYTHONPATH"]=str(path)+os.pathsep+str(REPOSITORY)
        result=subprocess.run([sys.executable,str(REPOSITORY/"test_pilot_status_guard.py")],
            cwd=path,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=60)
        if result.returncode!=0:
            print("TEMPORARY_LEGACY_ROUTE_UNIT_FAILED",flush=True)
            raise RuntimeError("TEMP_TEST_FAILURE")
        print("TEMPORARY_LEGACY_ROUTE_UNIT_PASSED",flush=True)
        print("TEMPORARY_SOURCE_REMOVED_ON_EXIT",flush=True)
    print("OVERLAY_READY_FOR_REVIEW_NOT_DEPLOYED",flush=True)
    print("PRODUCTION_UNCHANGED_ORDERS_UNCHANGED_PAYMENTS_UNCHANGED",flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("DRYRUN_BLOCKED",type(exc).__name__,str(exc)[:110],flush=True)
        raise SystemExit(1)
