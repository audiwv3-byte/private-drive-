"""Offline SHA-pinned patch for live pd_request_security.py.

Only the exact dispatcher document replacement POST multipart path is allowed
through the existing generic JSON-shape before_request guard. The endpoint
MUST still verify signed Telegram initData, core.is_admin, image normalization,
expected SHA and audit/transaction (pd_issue30_admin_review_routes.py).
No production writes, no bypass for arbitrary admin paths or other methods.
"""
import ast
import hashlib

EXPECTED_SHA256="f1dfb0d78e3799ed0a5569986bcb811dfb71c9f8fc5504336d6365abc9789d24"

class RequestGuardPatchMismatch(RuntimeError):
    pass

# Exact path shape, no wildcard for unrelated admin routes.
NEW_EXCEPTION=(
    "        if (request.method == 'POST' and request.mimetype == 'multipart/form-data'\n"
    "                and re.fullmatch(\n"
    "                    r'/api/admin/driver-applications/[1-9][0-9]*/documents/'\n"
    "                    r'(?:license_front|license_back|registration_front|registration_back|'\n"
    "                    r'ltsa|activity|insurance|portrait|car_front|car_rear|car_interior)/replace',\n"
    "                    request.path)):\n"
    "            return\n"
)

def patch_source(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA256:
        raise RequestGuardPatchMismatch("Deployed request guard fingerprint changed")
    original=raw.decode("utf-8")
    tree=ast.parse(original)
    matches=[n for n in ast.walk(tree) if isinstance(n,ast.If)
             and "/api/driver/application" in ast.unparse(n.test)
             and "multipart/form-data" in ast.unparse(n.test)
             and len(n.body)==1 and isinstance(n.body[0],ast.Return)]
    if len(matches)!=1:
        raise RequestGuardPatchMismatch("Unexpected deployed multipart guard AST")
    n=matches[0]
    indentation=original.splitlines()[n.lineno-1].split("if ",1)[0]
    if len(indentation)!=8:
        raise RequestGuardPatchMismatch("Unexpected nested guard indentation")
    lines=original.splitlines(keepends=True)
    # Insert after the original pilot exception, keeping it intact.
    lines.insert(n.end_lineno,NEW_EXCEPTION)
    changed="".join(lines)
    original_tree=ast.parse(original)
    new_tree=ast.parse(changed)
    def signature(tree):
        return sorted((n.name, len(n.args.args)) for n in ast.walk(tree)
                      if isinstance(n,ast.FunctionDef))
    if signature(original_tree)!=signature(new_tree):
        raise RequestGuardPatchMismatch("Unexpected function/API change")
    if changed.count("request.method == 'POST' and request.mimetype == 'multipart/form-data'")!=1:
        raise RequestGuardPatchMismatch("Unexpected multipart exception count")
    if changed.count("r'/api/admin/driver-applications/[1-9][0-9]*/documents/'")!=1:
        raise RequestGuardPatchMismatch("Unexpected URL constraint")
    return changed
