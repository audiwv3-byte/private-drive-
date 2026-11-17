"""Issue #30: STRICTLY OFFLINE patch to live dispatcher decisions.

Apply only to the SHA-pinned live source already transformed in memory by
pd_issue30_patch_live_onboarding_offline.patch_source(raw).  This function
never fetches/deploys files, never touches the production SQLite database.
"""
import ast
import re

import pd_issue30_patch_live_onboarding_offline as onboarding

IMPORT = "import pd_issue30_decision_bridge as pd_issue30_bridge"


class DispatcherPatchMismatch(onboarding.PatchMismatch):
    pass


def patch_source(raw):
    patched = onboarding.patch_source(raw)
    if IMPORT in patched:
        raise DispatcherPatchMismatch("Dispatcher bridge already present")
    lines = patched.splitlines(keepends=True)
    tree = ast.parse(patched)
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name == "pd_driver_decide"]
    if len(handlers) != 1:
        raise DispatcherPatchMismatch("Unexpected dispatcher handler count")
    fn = handlers[0]
    # The current deployed handler has one approval branch with presence-only
    # checks and one status-update branch after it.
    approval = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                and ast.unparse(n.test) == "target == 'approved' and r['status'] != 'approved'"]
    updates = [n for n in ast.walk(fn) if isinstance(n, ast.If)
               and ast.unparse(n.test) == "r['status'] != target"]
    if len(approval) != 1 or len(updates) != 1:
        raise DispatcherPatchMismatch("Unexpected approval or update blocks")
    old = approval[0]
    later = updates[0]
    # Include the intermediate unsafe checks, including stage2 -> approved
    # special case. Require exact, nonoverlapping positioning.
    if not (old.lineno < old.end_lineno < later.lineno and
            later.lineno - old.lineno <= 22):
        raise DispatcherPatchMismatch("Unexpected decision-block layout")
    old_text = "".join(lines[old.lineno - 1:later.lineno - 1])
    if ("ACTIVE_SIDES" not in old_text or
            "target='stage2'" not in old_text or
            "r['status']=='stage2'" not in old_text):
        raise DispatcherPatchMismatch("Known legacy approval logic not present")

    indent = lines[old.lineno - 1][:len(lines[old.lineno - 1]) -
                                       len(lines[old.lineno - 1].lstrip())]
    bridge_call = (
        indent + "target = pd_issue30_bridge.guard_admin_approval(\n"
        + indent + "    c, applicant, target, uid, core)\n"
    )
    patched = "".join(lines[:old.lineno - 1] + [bridge_call] +
                      lines[later.lineno - 1:])
    import_anchor = "import pd_issue30_document_storage_guard as pd_issue30_store\n"
    if patched.count(import_anchor) != 1:
        raise DispatcherPatchMismatch("Missing pretested registration patch")
    patched = patched.replace(import_anchor, import_anchor + IMPORT + "\n", 1)
    try:
        after = ast.parse(patched)
    except SyntaxError as exc:
        raise DispatcherPatchMismatch("Generated source is not valid Python") from exc

    old_routes = [(ast.unparse(n.func), ast.unparse(n.args[0]))
                  for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr in {"get", "post", "route"}
                  and isinstance(n.args[0], ast.Constant)
                  and isinstance(n.args[0].value, str)
                  and n.args[0].value.startswith("/")]
    new_routes = [(ast.unparse(n.func), ast.unparse(n.args[0]))
                  for n in ast.walk(after) if isinstance(n, ast.Call) and n.args
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr in {"get", "post", "route"}
                  and isinstance(n.args[0], ast.Constant)
                  and isinstance(n.args[0].value, str)
                  and n.args[0].value.startswith("/")]
    if sorted(old_routes) != sorted(new_routes):
        raise DispatcherPatchMismatch("Flask routes changed unexpectedly")
    decision = [n for n in ast.walk(after) if isinstance(n, ast.FunctionDef)
                and n.name == "pd_driver_decide"][0]
    if sum(1 for n in ast.walk(decision)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "guard_admin_approval") != 1:
        raise DispatcherPatchMismatch("Unexpected approval guard count")
    if "SELECT status,stage FROM pd_driver_applications" not in patched:
        raise DispatcherPatchMismatch("Live SQL state verification missing")
    return patched


if __name__ == "__main__":
    raise SystemExit("Import patch_source(bytes) in an isolated test runner only")
