"""Offline PayPal regression checks; no real money, credentials or HTTP requests."""
import os
import unittest
from unittest.mock import patch
import pd_paypal_checkout as pp

def completed(amount="70.00", booking=27, currency="EUR", ref=None):
    return {
        "status": "COMPLETED",
        "purchase_units": [{
            "reference_id": str(booking) if ref is None else ref,
            "custom_id": f"pd-{booking}",
            "payments": {"captures": [{
                "id": "8AB1234567890123", "status": "COMPLETED",
                "amount": {"currency_code": currency, "value": amount}
            }]}
        }]
    }

class PaypalSafety(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"PD_PAYPAL_MODE": "disabled",
                "PAYPAL_CLIENT_ID": "fake", "PAYPAL_CLIENT_SECRET": "fake"}):
            self.assertIsNone(pp.settings())
    def test_live_needs_explicit_gate(self):
        env={"PD_PAYPAL_MODE":"live", "PAYPAL_CLIENT_ID":"client",
             "PAYPAL_CLIENT_SECRET":"secret"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(pp.settings())
    def test_sandbox_credentials(self):
        env={"PD_PAYPAL_MODE":"sandbox", "PAYPAL_CLIENT_ID":"client",
             "PAYPAL_CLIENT_SECRET":"secret"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(pp.settings()["base"],"https://api-m.sandbox.paypal.com")
    def test_money(self):
        self.assertEqual(pp.money("70"), "70.00")
        self.assertEqual(pp.money("70,25"), "70.25")
        for item in (None,"", "0", "-1", "NaN", "Infinity", "1.999", "100000.01"):
            with self.subTest(item=item), self.assertRaises(ValueError):
                pp.money(item)
    def test_reference_currency_amount_exact(self):
        self.assertEqual(pp.validated_capture(completed(),27,"70.00"),"8AB1234567890123")
        for payload in [completed("69.99"), completed(currency="USD"),
                        completed(ref="29"), completed(booking=28)]:
            with self.assertRaises(ValueError):
                pp.validated_capture(payload, 27, "70.00")
    def test_no_partial_or_multiple_captures(self):
        for status in ("PENDING","VOIDED"):
            p=completed()
            p["status"]=status
            with self.assertRaises(ValueError):
                pp.validated_capture(p,27,"70.00")
        p=completed()
        p["purchase_units"][0]["payments"]["captures"].append(
            p["purchase_units"][0]["payments"]["captures"][0])
        with self.assertRaises(ValueError):
            pp.validated_capture(p,27,"70.00")
    def test_create_no_http_on_invalid_amount(self):
        with patch.object(pp, "call", side_effect=AssertionError("Unexpected payment API")):
            with self.assertRaises(ValueError):
                pp.create({"mode":"sandbox"}, 12, "0")

if __name__ == "__main__":
    unittest.main()
