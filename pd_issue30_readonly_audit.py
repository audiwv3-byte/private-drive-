"""Issue #30: GET-only PythonAnywhere source compatibility audit.

Run in an isolated GitHub Actions job with PA_API_TOKEN secret.
No writes, no console endpoints, no database reads, no source/body printing.
Requires: requests.
"""
import ast
import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests

USER = "wilsonpark"
ROOT = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18"
TARGETS = ("pd_onboarding.py", "miniapp_server.py", "miniapp/templates/index.html")
HOST = "www.pythonanywhere.com"


def signature(content):
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (UnicodeError, SyntaxError):
        return ["source unavailable for AST introspection"]
    items = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(token in node.name.lower() for token in
                   ("driver", "pilot", "stage", "document", "review", "decid", "approv", "register")):
            continue
        routes = []
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr in ("get", "post", "put", "patch", "delete", "route"):
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        path = decorator.args[0].value
                        if isinstance(path, str) and path.startswith("/"):
                            routes.append(decorator.func.attr.upper() + " " + path)
        items.append({"function": node.name, "routes": routes})
    return items


def main():
    token = re.sub(r"^Token\s+", "", os.environ.get("PA_API_TOKEN", "").strip(), flags=re.I)
    token = "".join(token.split())
    if not token:
        raise RuntimeError("PA_API_TOKEN missing; read-only audit skipped")
    session = requests.Session()
    session.headers["Authorization"] = "Token " + token
    session.headers["Accept"] = "application/json"
    for rel in TARGETS:
        target = ROOT + "/" + rel
        url = f"https://{HOST}/api/v0/user/{USER}/files/path" + quote(target, safe="/")
        response = session.get(url, timeout=35)
        print("SOURCE", rel, "HTTP", response.status_code)
        if response.status_code != 200:
            continue
        data = response.content
        print("FINGERPRINT", rel, "size", len(data), "sha256", hashlib.sha256(data).hexdigest())
        local = Path(__file__).resolve().parent / rel
        if local.is_file():
            print("GITHUB_COMPARISON", rel, "MATCH" if data == local.read_bytes() else "DIFFERENT")
        if rel.endswith(".py"):
            print("ROUTE_SIGNATURE", rel, signature(data))
    # Never save files returned by PythonAnywhere or print source lines.
    print("DONE: GET-only, no production changes")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        raise SystemExit("Network failure during GET-only audit: " + type(exc).__name__)
