"""Issue 30: AST-only, GET-only live onboarding compatibility probe.

No source text, document bytes, data rows, secrets, or SQL values are output.
Never touches production database or calls a PythonAnywhere write endpoint.
"""
import ast
import os
import re
from urllib.parse import quote
import requests

HOST = "https://www.pythonanywhere.com"
ROOT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
PATH = ROOT + "/pd_onboarding.py"
ALLOWED = {"pending", "approved", "rejected", "stage1", "stage2", "stage_1", "stage_2",
           "draft", "submitted", "license_front", "license_back", "registration_front",
           "registration_back", "ltsa", "activity", "insurance", "portrait",
           "car_front", "car_rear", "car_interior"}
NEEDLES = ("stage", "status", "approve", "decision", "documents", "photo", "side", "replace")

def probe(data):
    tree = ast.parse(data.decode("utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        relevant = any(k in node.name.lower() for k in (
            "register", "apply", "decid", "document", "stage", "photo", "own", "admin"))
        if not relevant:
            continue
        methods = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                if dec.func.attr in ("get", "post", "put", "patch", "delete", "route"):
                    arg = dec.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        methods.append(dec.func.attr.upper() + ":" + arg.value)
        values = sorted({n.value for n in ast.walk(node)
                         if isinstance(n, ast.Constant) and isinstance(n.value, str)
                         and n.value.lower() in ALLOWED})
        # Structural evidence only, never source/SQL text
        funcs = sorted({n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                        for n in ast.walk(node) if isinstance(n, ast.Call)
                        and isinstance(n.func, (ast.Attribute, ast.Name))
                        and (any(k in (n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id).lower()
                                 for k in ("commit", "rollback", "execute", "is_admin", "read_photos", "stage", "auth")))})
        ids = sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                      and any(k in n.id.lower() for k in NEEDLES)})
        sql_ops = {"INSERT":0,"UPDATE":0,"DELETE":0,"CREATE":0,"SELECT":0}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                for verb in sql_ops:
                    sql_ops[verb] += len(re.findall(r"\\b" + verb + r"\\b", sub.value, re.I))
        print("LIVE_FUNCTION", node.name, "routes", methods, "stage_values", values,
              "related_calls", funcs, "identifiers", ids[:45], "sql_keywords",sql_ops)
    # Check specific live file features with tokens only (no source excerpts)
    lower = data.decode("utf-8").lower()
    for token in ("stage2", "stage1", "pd_driver_document_reviews", "pd_document_reviews",
                  "registration_front", "already", "on conflict", "begin immediate",
                  "status='approved'", "status = 'approved'"):
        print("LIVE_TOKEN", token, token in lower)

def main():
    token = re.sub(r"^Token\\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I)
    token = "".join(token.split())
    if not token:
        print("NO_TOKEN")
        return
    s = requests.Session()
    s.headers["Authorization"] = "Token " + token
    resp = s.get(HOST + "/api/v0/user/wilsonpark/files/path" + quote(PATH, safe="/"), timeout=35)
    print("LIVE_GET_STATUS", resp.status_code)
    if resp.status_code != 200:
        raise SystemExit("Read-only API fetch failed")
    probe(resp.content)

if __name__ == "__main__":
    main()
