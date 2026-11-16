"""Issue #30, SQL definitions and guarded transition structure from live source.
GET-only, no DB access, no source file persistence.
"""
import os
import ast
import re
from urllib.parse import quote
import requests

USER="wilsonpark"
FILE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_onboarding.py"
def squish(s):return " ".join(s.split())
def expr(node):return squish(ast.unparse(node))[:600]
def run():
    token="".join(re.sub(r"^Token\\s+","",os.environ.get("PA_API_TOKEN","").strip(),flags=re.I).split())
    if not token:
        print("NO_TOKEN");return
    url="https://www.pythonanywhere.com/api/v0/user/"+USER+"/files/path"+quote(FILE,safe="/")
    r=requests.get(url,headers={"Authorization":"Token "+token},timeout=35)
    print("SOURCE_STATUS",r.status_code)
    r.raise_for_status()
    root=ast.parse(r.content.decode("utf-8"))
    for node in ast.walk(root):
        if isinstance(node, ast.FunctionDef) and node.name in ("ensure_tables","register","pd_driver_apply","pd_driver_decide"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func,ast.Attribute) and sub.func.attr in ("execute","executescript") and sub.args:
                    x=sub.args[0]
                    if isinstance(x,ast.Constant) and isinstance(x.value,str) and any(v in x.value.lower() for v in ("pd_driver_applications","pd_driver_documents")):
                        sql=squish(x.value)
                        if sql.upper().startswith(("CREATE TABLE","INSERT INTO PD_DRIVER_APPLICATIONS","UPDATE PD_DRIVER_APPLICATIONS")):
                            print("LIVE_SQL",node.name,sub.lineno,sql[:1400])
                if node.name in ("pd_driver_apply","pd_driver_decide"):
                    if isinstance(sub,ast.If) and any(t in expr(sub.test).lower() for t in ("stage","status","target")):
                        print("LIVE_IF",node.name,sub.lineno,expr(sub.test))
                    elif isinstance(sub,ast.Assign) and any(t in expr(sub.value).lower() for t in ("stage","status","target","required")):
                        print("LIVE_ASSIGN",node.name,sub.lineno,expr(sub))
    print("END")
if __name__=="__main__":run()
