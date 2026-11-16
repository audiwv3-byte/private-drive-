"""Issue 30 source-only GET inspection: return strictly onboarding handler statements.

Only source lines inside the driver application handler, never DB, secrets,
user data, or PythonAnywhere file mutations. CI logs are for code review.
"""
import ast, os, hashlib, requests
from urllib.parse import quote
ROOT="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
URL="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(ROOT+"/pd_onboarding.py",safe="/")
token=os.environ.get("PA_API_TOKEN","").strip()
if not token:
    raise SystemExit("No token; no GET performed")
r=requests.get(URL,headers={"Authorization":"Token "+token},timeout=30)
r.raise_for_status()
data=r.content
expected="7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b"
if hashlib.sha256(data).hexdigest()!=expected:
    raise SystemExit("Production source changed. Refusing analysis of unexpected version.")
source=data.decode("utf-8")
tree=ast.parse(source)
lines=source.splitlines()
functions=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=="pd_driver_apply"]
if len(functions)!=1: raise SystemExit("Unexpected handler structure")
fn=functions[0]
if fn.end_lineno-fn.lineno>90: raise SystemExit("Unexpected handler length")
for idx in range(fn.lineno-1,fn.end_lineno):
    s=lines[idx]
    if "password" in s.lower() or "token" in s.lower() or "secret" in s.lower():
        print(f"L{idx+1}: [REDACTED]")
    else:
        print(f"L{idx+1}: {s}")
