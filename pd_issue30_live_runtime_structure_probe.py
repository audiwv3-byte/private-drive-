"""Issue 30: GET-only structural inspection of live core.db and admin template.

Only static source AST and UI marker counts are logged. Never fetches SQL DB,
credentials, private documents, real photos, or runtime application objects.
"""
import ast, hashlib, os, re
from urllib.parse import quote
import requests

ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
HOST="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
FILES=("Euro_Baltic_Transfer.py","miniapp_server.py","miniapp/templates/index.html")
token="".join(os.environ.get("PA_API_TOKEN","").strip().split())
if not token: raise SystemExit("PA_API_TOKEN unavailable")
session=requests.Session()
session.headers["Authorization"]="Token "+token
for path in FILES:
    resp=session.get(HOST+quote(ROOT+path,safe="/"), timeout=35)
    print("LIVE_FILE",path,"HTTP",resp.status_code)
    if resp.status_code != 200:
        raise SystemExit("GET source unavailable")
    print("SHA256",path,hashlib.sha256(resp.content).hexdigest())
    source=resp.content.decode("utf-8")
    if path.endswith(".html"):
        for keyword in ("driver-applications", "document-reviews", "Одобрить", "stage2",
                        "admin", "dispatcher", "pd_driver", "approve", "license_front"):
            print("HTML_MARKER",keyword,source.lower().count(keyword.lower()))
        # Static inline script call sites only, no sensitive HTML contents
        for match in re.finditer(r"/api/(?:admin/driver-applications|driver/application)[^'\"<> ]{0,100}", source):
            print("HTML_API_PATH",match.group(0)[:115])
        continue
    tree=ast.parse(source)
    for f in ast.walk(tree):
        if not isinstance(f,(ast.FunctionDef,ast.AsyncFunctionDef)):
            continue
        if (path=="Euro_Baltic_Transfer.py" and f.name in ("db","is_admin")) or (
                path=="miniapp_server.py" and f.name in ("auth","registered_passenger","protect_private_information")):
            print("FUNC",path,f.name,"location",f.lineno,f.end_lineno,
                  "decorators",[ast.unparse(d) for d in f.decorator_list])
            if path=="Euro_Baltic_Transfer.py" and f.name=="db":
                print("DB_AST", ast.unparse(f)[:900])
            for n in ast.walk(f):
                if isinstance(n,ast.Call):
                    callee=ast.unparse(n.func)
                    if any(k in callee for k in ("commit","rollback","close","connect","is_admin","auth")):
                        print("CALL",f.name,callee)
                if isinstance(n,(ast.Try,ast.With,ast.Raise,ast.Yield)):
                    print("STRUCTURE",f.name,n.__class__.__name__,n.lineno)
print("GET_ONLY_COMPLETE")
