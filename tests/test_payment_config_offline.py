"""Offline-only payment configuration guard tests.

Never imports the application, initializes a database, or calls Stripe.
Only the configure() function AST is compiled with synthetic environment.
Run: python -m unittest discover -s tests -p 'test_payment_config_offline.py'
"""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "pd_prepayment_v3.py"


class StripeStub:
    api_key = None
    max_network_retries = None


class OfflinePaymentConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        configure = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "configure"
        )
        code = compile(ast.Module(body=[configure], type_ignores=[]), str(SOURCE), "exec")
        cls.stripe_stub = StripeStub()
        namespace = {"os": os, "stripe": cls.stripe_stub}
        exec(code, namespace)
        cls.configure = staticmethod(namespace["configure"])

    def setUp(self):
        self.stripe_stub.api_key = None
        self.stripe_stub.max_network_retries = None

    def run_config(self, values):
        keys = (
            "PD_PAYMENT_MODE", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            "PD_LIVE_PAYMENTS_APPROVED", "PD_CANCELLATION_POLICY_APPROVED",
            "PD_LIVE_WEBHOOK_EVENTS_VERIFIED",
        )
        with patch.dict(os.environ, {key: "" for key in keys}, clear=False):
            with patch.dict(os.environ, values):
                return self.configure()

    def test_disabled_mode_rejects_even_test_credentials(self):
        with self.assertRaises(ValueError):
            self.run_config({"PD_PAYMENT_MODE": "disabled",
                             "STRIPE_SECRET_KEY": "sk_test_SYNTHETIC",
                             "STRIPE_WEBHOOK_SECRET": "whsec_SYNTHETIC"})
        self.assertIsNone(self.stripe_stub.api_key)

    def test_test_mode_requires_matching_key_and_webhook(self):
        for values in (
            {"PD_PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_live_SYNTHETIC",
             "STRIPE_WEBHOOK_SECRET": "whsec_SYNTHETIC"},
            {"PD_PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_test_SYNTHETIC"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.run_config(values)
        self.assertIsNone(self.stripe_stub.api_key)

    def test_live_requires_all_three_independent_approvals(self):
        base = {"PD_PAYMENT_MODE": "live", "STRIPE_SECRET_KEY": "sk_live_SYNTHETIC",
                "STRIPE_WEBHOOK_SECRET": "whsec_SYNTHETIC",
                "PD_LIVE_PAYMENTS_APPROVED": "1",
                "PD_CANCELLATION_POLICY_APPROVED": "1",
                "PD_LIVE_WEBHOOK_EVENTS_VERIFIED": "1"}
        for key in (
            "PD_LIVE_PAYMENTS_APPROVED", "PD_CANCELLATION_POLICY_APPROVED",
            "PD_LIVE_WEBHOOK_EVENTS_VERIFIED",
        ):
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.run_config({**base, key: ""})
        self.assertIsNone(self.stripe_stub.api_key)

    def test_valid_synthetic_test_config_does_not_make_network_calls(self):
        result = self.run_config({"PD_PAYMENT_MODE": "test",
                                  "STRIPE_SECRET_KEY": "sk_test_SYNTHETIC",
                                  "STRIPE_WEBHOOK_SECRET": "whsec_SYNTHETIC"})
        self.assertEqual(result, "test")
        self.assertEqual(self.stripe_stub.api_key, "sk_test_SYNTHETIC")
        self.assertEqual(self.stripe_stub.max_network_retries, 1)


if __name__ == "__main__":
    unittest.main()
