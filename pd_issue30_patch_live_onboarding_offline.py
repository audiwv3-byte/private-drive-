"""Issue #30: produce a STRICTLY OFFLINE patch of verified live pd_onboarding.py.

This module NEVER writes to PythonAnywhere. Call patch_source(bytes) only after
PythonAnywhere GET /files/path and compare to known deployment SHA. The patched
source remains in GitHub Actions runner memory, not GitHub or artifacts.

Only two surgical changes:
  1. add storage guard import;
  2. move the EXISTING application upsert before document writes, then invoke
     pilot_insert_missing once for every uploaded image, under EXISTING BEGIN IMMEDIATE.
No new routes or dispatcher behavior, no other statements removed.
"""
import ast
import hashlib
import re

EXPECTED_SHA256 = "7ae5a7b3dc3ed2a217be4368d79e6d6ebfd86c5222cae652edee900297ae0e9b"
IMPORT_LINE = "import pd_issue30_document_storage_guard as pd_issue30_store"


class PatchMismatch(RuntimeError):
    pass


def _handler_nodes(source):
    tree = ast.parse(source)
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "pd_driver_apply"]
    if len(matches) != 1:
        raise PatchMismatch("Expected exactly one deployed application handler")
    return tree, matches[0]


def patch_source(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise PatchMismatch("Deployed source fingerprint mismatch; patch refused")
    original = raw.decode("utf-8")
    tree, fn = _handler_nodes(original)
    lines = original.splitlines(keepends=True)
    if IMPORT_LINE in original:
        raise PatchMismatch("Unexpected installed storage guard")

    # Match the exact existing document loop by AST, not a global string replace.
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)
             and ast.unparse(n.target) == "(side, image)"
             and ast.unparse(n.iter) == "photos.items()"]
    if len(loops) != 1 or len(loops[0].body) != 1:
        raise PatchMismatch("Unexpected document save loop")
    loop = loops[0]
    statement = loop.body[0]
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        raise PatchMismatch("Unexpected document save statement")
    call = statement.value
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "execute":
        raise PatchMismatch("Document write is not direct SQLite execute")
    sql = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else ""
    if not ("INSERT INTO pd_driver_documents" in sql
            and re.search(r"ON\s+CONFLICT\s*\(telegram_id,side\)\s+DO\s+UPDATE\s+SET\s+image", sql, re.I)):
        raise PatchMismatch("Unexpected deployed UPSERT format")

    # The application upsert must be the immediately following block.
    first = loop.lineno - 1
    end = loop.end_lineno
    app_start = end
    if "c.execute('''INSERT INTO pd_driver_applications" not in lines[app_start]:
        raise PatchMismatch("Application UPSERT no longer follows photo loop")
    app_last = next((i for i in range(app_start, min(len(lines), app_start + 20))
                     if "(uid,out['name'],phone,out['city'],out['vehicle'],year,plate,seats,now,now,stage))" in lines[i]), None)
    if app_last is None:
        raise PatchMismatch("Application SQL parameters do not match deployed source")
    app_code = "".join(lines[app_start:app_last + 1])
    if "status='pending',stage=excluded.stage" not in app_code:
        raise PatchMismatch("Stage-2 application UPSERT not recognized")

    # Existing UPSERT becomes a call to the insert-only document guard.
    indent = lines[first][:len(lines[first]) - len(lines[first].lstrip())]
    updated_loop = (
        indent + "for side,image in photos.items():\n"
        + indent + "    pd_issue30_store.pilot_insert_missing("
        + "c, applicant=uid, side=side, image=image)\n"
    )
    patched_lines = (
        lines[:first] + [app_code, updated_loop] + lines[app_last + 1:]
    )
    patched = "".join(patched_lines)

    # Import near existing top-level imports; fail if code layout drifted.
    marker = "import json,re,io,warnings,hashlib\n"
    if patched.count(marker) != 1:
        raise PatchMismatch("Unexpected imports in deployed source")
    patched = patched.replace(marker, marker + IMPORT_LINE + "\n", 1)

    # Fail if ANY old document-image UPSERT remains, and ensure original routes
    # and all three original status transitions remain exactly as before.
    old_upsert = re.compile(r"ON\s+CONFLICT\s*\(\s*telegram_id\s*,\s*side\s*\)"
                            r"\s+DO\s+UPDATE\s+SET\s+image", re.I)
    if old_upsert.search(patched):
        raise PatchMismatch("Unsafe document UPSERT remains")
    new_tree, new_fn = _handler_nodes(patched)
    if len([n for n in ast.walk(new_fn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "pilot_insert_missing"]) != 1:
        raise PatchMismatch("Missing unique guarded insertion call")
    def routes(t):
        return sorted((n.func.attr, n.args[0].value)
                      for n in ast.walk(t)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr in ("get", "post", "route")
                      and n.args and isinstance(n.args[0], ast.Constant)
                      and isinstance(n.args[0].value, str)
                      and n.args[0].value.startswith("/"))
    if routes(tree) != routes(new_tree):
        raise PatchMismatch("Unexpected Flask route changes")
    return patched


if __name__ == "__main__":
    raise SystemExit("Offline patch helper: import patch_source(raw) from the test runner")
