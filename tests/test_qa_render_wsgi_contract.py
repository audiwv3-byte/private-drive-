"""Read-only CI contract audit for actual deployed Render WSGI sources.

Does not import application modules, connect to services, or read secrets.
Pinned GitHub revisions represent an observed snapshot, NOT a live probe.
"""
import ast
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "qa/render_wsgi_snapshot.json").read_text(encoding="utf-8"))


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports(tree, module_name, symbol=None):
    return any(isinstance(node, ast.ImportFrom)
               and node.module == module_name
               and (symbol is None or any(alias.name == symbol for alias in node.names))
               for node in ast.walk(tree))


def calls(tree, name):
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == name for node in ast.walk(tree))


def verify_checkout(snapshot):
    target = ROOT / snapshot["pinned_checkout"]
    actual = subprocess.check_output(
        ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != snapshot["repo_commit"]:
        raise AssertionError("Pinned revision does not match the observed Render deploy")
    return target


class DeployedEntrypointContract(unittest.TestCase):
    def test_native_endpoint_not_mounted_in_observed_deploy(self):
        native = next(s for s in DATA["services"] if s["role"] == "native_api")
        checkout = verify_checkout(native)
        entrypoint = parse(checkout / native["source_file"])
        orders = parse(checkout / "pd_native_orders_http.py")
        self.assertTrue(imports(orders, "pd_dispatch_persistent", "validated_order"))
        self.assertTrue(any(isinstance(n, ast.Constant) and n.value == "/native-orders"
                            for n in ast.walk(orders)))
        self.assertTrue(imports(entrypoint, "pd_native_pilot_assignment", "make_native_pilot_orders_app"))
        self.assertTrue(imports(entrypoint, "pd_native_auth_postgres_http", "make_app"))
        self.assertFalse(imports(entrypoint, "pd_native_orders_http", "make_orders_app"))
        self.assertFalse(calls(entrypoint, "make_orders_app"))
        self.assertNotIn("/native-orders", (checkout / native["source_file"]).read_text())
        print("CONFIRMED: deployed native API WSGI lacks /native-orders mount (HTTP 404 path); not evidence of HTTP 503")

    def test_dispatcher_uses_different_wsgi_and_registers_queue(self):
        dispatcher = next(s for s in DATA["services"] if s["role"] == "dispatcher")
        checkout = verify_checkout(dispatcher)
        entrypoint = parse(checkout / dispatcher["source_file"])
        web_dispatch = parse(checkout / "pd_web_dispatcher.py")
        self.assertTrue(imports(entrypoint, "pd_web_dispatcher", "register"))
        self.assertTrue(calls(entrypoint, "register"))
        self.assertTrue(imports(web_dispatch, "pd_dispatch_persistent", "register"))
        self.assertTrue(calls(web_dispatch, "register_persistent_queue"))
        self.assertFalse(imports(entrypoint, "pd_qa25_wsgi", "create_application"))
        print("CONFIRMED: dispatcher WSGI mounts queue separately; actual enablement depends on uninspected runtime flags")

    def test_qa_wsgi_mounts_shared_native_order_adapter(self):
        qa = parse(ROOT / "pd_qa25_wsgi.py")
        self.assertTrue(imports(qa, "pd_native_orders_http", "make_orders_app"))
        self.assertTrue(calls(qa, "make_orders_app"))
        print("CONFIRMED: QA WSGI mounts native orders, unlike deployed Render native API WSGI")


if __name__ == "__main__":
    unittest.main()
