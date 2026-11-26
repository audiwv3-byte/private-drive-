"""Read-only contract checks for isolated PRIVATE DRIVE staging API wiring.

No database, HTTP, payment provider, production service or customer data is used.
"""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pd_miniapp_dispatch_bridge import bridge_enabled, central_delivery_required

ROOT = Path(__file__).resolve().parents[1]


class UnifiedStagingContractTests(unittest.TestCase):
    def test_native_wsgi_mounts_orders_and_pilot_api(self):
        module = ast.parse((ROOT / "isolated_sms_wsgi.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in module.body
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names}
        self.assertIn("make_orders_app", imported)
        self.assertIn("make_native_pilot_orders_app", imported)
        called = {node.func.id for node in ast.walk(module)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("make_orders_app", called)
        self.assertIn("make_native_pilot_orders_app", called)

    def test_import_reply_contains_required_disabled_payment_ack(self):
        source = (ROOT / "pd_dispatch_persistent.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        register = next(n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == "register")
        import_order = next(n for n in register.body
                            if isinstance(n, ast.FunctionDef) and n.name == "import_order")
        success_replies = [
            node for node in ast.walk(import_order)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "reply"
            and node.args and isinstance(node.args[0], ast.Dict)
            and "order_id" in [k.value for k in node.args[0].keys
                               if isinstance(k, ast.Constant)]
        ]
        self.assertEqual(len(success_replies), 1)
        keys = [k.value for k in success_replies[0].args[0].keys
                if isinstance(k, ast.Constant)]
        self.assertIn("payment_mode", keys)
        pos = keys.index("payment_mode")
        self.assertEqual(success_replies[0].args[0].values[pos].value, "disabled")

    def test_minapp_staging_cannot_approve_local_only_order(self):
        with patch.dict(os.environ, {
                "PD_DISPATCH_STAGING_ONLY": "1",
                "PD_PAYMENT_MODE": "disabled",
                "PD_MINIAPP_DISPATCH_BRIDGE": "0",
        }):
            self.assertTrue(central_delivery_required())
            self.assertFalse(bridge_enabled())
        module = ast.parse((ROOT / "miniapp_server.py").read_text(encoding="utf-8"))
        ack = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                   and n.name == "acknowledge_central_dispatch")
        self.assertTrue(any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Call)
            and isinstance(node.test.func, ast.Name)
            and node.test.func.id == "central_delivery_required"
            for node in ast.walk(ack)
        ))

    def test_no_payment_or_deployment_code_introduced_to_contract(self):
        source = (ROOT / "pd_miniapp_dispatch_bridge.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("PD_PAYMENT_MODE") == "disabled"', source)
        self.assertIn("verified", (ROOT / "pd_dispatch_persistent.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
