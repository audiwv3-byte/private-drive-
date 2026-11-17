"""Issue #30: fail-closed, GET-only WSGI integration source patch.

NEVER writes to PythonAnywhere. Accept exact verified deployed miniapp_server.py
bytes, return modified Python source string in memory for review/tests.
Must be staged together with review DB migration, helpers and updated HTML.
"""
import ast
import hashlib

EXPECTED_SHA256="f4a4dcfe4c9f406e7fe3188ca39a27eb53952bedfb09cd41f82a3613f790adc4"
IMPORT_AND_REGISTER=(
    "import pd_issue30_admin_review_routes as pd_issue30_admin_routes\n"
    "pd_issue30_admin_routes.register(app,core,auth,pd_onboarding.read_photos)\n"
)

class WsgiPatchMismatch(RuntimeError):
    pass

def patch_source(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA256:
        raise WsgiPatchMismatch("Live WSGI source changed; release blocked")
    source=raw.decode("utf-8")
    tree=ast.parse(source)
    targets=[n for n in tree.body if isinstance(n,ast.Expr)
             and isinstance(n.value,ast.Call)
             and ast.unparse(n.value.func)=="pd_onboarding.register"
             and [ast.unparse(x) for x in n.value.args]==["app","core","auth"]]
    if len(targets)!=1:
        raise WsgiPatchMismatch("Unexpected deployed onboarding registration")
    if "pd_issue30_admin_review_routes" in source:
        raise WsgiPatchMismatch("Admin review routes may already be enabled")
    lines=source.splitlines(keepends=True)
    idx=targets[0].end_lineno
    lines.insert(idx, IMPORT_AND_REGISTER)
    patched="".join(lines)
    newtree=ast.parse(patched)
    calls=[n for n in ast.walk(newtree) if isinstance(n,ast.Call)
           and ast.unparse(n.func)=="pd_issue30_admin_routes.register"]
    if len(calls)!=1 or [ast.unparse(x) for x in calls[0].args]!=[
          "app","core","auth","pd_onboarding.read_photos"]:
        raise WsgiPatchMismatch("Unexpected review route wiring")
    return patched
