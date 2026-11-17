"""GET-only source fingerprint of deployed HTTP request guard, no DB access."""
import ast
import hashlib
import os
from urllib.parse import quote
import requests

path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_request_security.py"
url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(path,safe="/")
token=os.environ.get("PA_API_TOKEN","").strip()
if not token: raise SystemExit("Read-only API credentials absent")
response=requests.get(url,headers={"Authorization":"Token "+token},timeout=30)
response.raise_for_status()
source=response.content.decode("utf-8")
tree=ast.parse(source)
guard=[f for f in ast.walk(tree) if isinstance(f,ast.FunctionDef) and f.name=="register_request_guard"]
if len(guard)!=1:raise SystemExit("Unexpected request guard source")
body=ast.unparse(guard[0])
print("REQUEST_GUARD_SHA256",hashlib.sha256(response.content).hexdigest())
print("REQUEST_GUARD_REGISTER",len(guard))
print("REQUEST_GUARD_MULTIPART_ONLY_APPLICATION", "/api/driver/application" in body and "multipart/form-data" in body)
print("REQUEST_GUARD_ADMIN_REPLACE_EXCEPTION", "documents" in body and "replace" in body)
print("REQUEST_GUARD_GET_ONLY_DONE")
