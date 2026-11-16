"""GET-only live onboarding control-flow probe for issue #30.

Fetches ONE deployed Python source file through PythonAnywhere API GET.
Prints sanitized schema declarations, stage/status conditions, and static SQL
statements that modify registration, never application rows or source files.
No database endpoints; no POST; no webapp reload.
"""
import ast
import os
import re
from urllib.parse import quote
import requests

USER = "wilsonpark"
PATH = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_onboarding.py"
STATUS_WORDS = ("stage2", "pending", "approved", "rejected", "stage")
ALLOWED_TABLES = ("pd_driver_applications", "pd_driver_documents", "pd_driver_application_decisions")

def static_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # Do not expose dynamic parts.
        return "".join(p.value if isinstance(p, ast.Constant) and isinstance(p.value, str)
                       else "[DYNAMIC]" for p in node.values)
    return None

def clip(s, n=600):
    return re.sub(r"\\s+", " ", s).strip()[:n]

def is_target(s):
    return any(t in s.lower() for t in ALLOWED_TABLES)

def inspect_source(raw):
    root = ast.parse(raw.decode("utf-8"))
    for node in ast.walk(root):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "register", "pd_driver_apply", "pd_driver_decide", "read_photos", "ensure_tables"
        ):
            print("FUNCTION", node.name, "lines", node.lineno, node.end_lineno)
            if node.name in ("pd_driver_apply", "pd_driver_decide"):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.If):
                        test = ast.unparse(sub.test)
                        if any(token in test.lower() for token in STATUS_WORDS):
                            print("BRANCH", sub.lineno, clip(test, 350))
                    if isinstance(sub, ast.Assign):
                        expr = ast.unparse(sub.value)
                        if any(token in expr.lower() for token in STATUS_WORDS):
                            targets = ",".join(ast.unparse(t) for t in sub.targets)
                            print("ASSIGNMENT", sub.lineno, clip(targets + " = " + expr, 400))
                    if isinstance(sub, ast.Raise):
                        val = ast.unparse(sub.exc) if sub.exc is not None else ""
                        if any(t in val.lower() for t in STATUS_WORDS):
                            print("REJECTION", sub.lineno, clip(val, 240))
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr in (
                    "execute", "executescript"
                ) and sub.args:
                    statement = static_string(sub.args[0])
                    if statement and is_target(statement):
                        sql = clip(statement, 900)
                        if sql.upper().startswith("CREATE TABLE"):
                            print("SCHEMA_SQL", node.name, sub.lineno, sql)
                        elif any(x in sql.upper() for x in ("UPDATE ", "INSERT ", "SELECT ", "DELETE ")):
                            print("TABLE_SQL", node.name, sub.lineno, sql)
    print("AST_PROBE_DONE")

def main():
    token = "".join(re.sub(r"^Token\\s+", "", os.environ.get("PA_API_TOKEN", "").strip(),
                            flags=re.I).split())
    if not token:
        print("AUDIT_NOT_RUN: no token")
        return
    url = ("https://www.pythonanywhere.com/api/v0/user/" + USER + "/files/path"
           + quote(PATH, safe="/"))
    r = requests.get(url, headers={"Authorization": "Token " + token}, timeout=35)
    print("SOURCE_HTTP", r.status_code)
    r.raise_for_status()
    inspect_source(r.content)

if __name__ == "__main__":
    main()
