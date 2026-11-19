"""Isolated negative tests: no Telegram token, network or production data."""
import hashlib
import hmac
import json
import time
import unittest
import urllib.parse
from pd_request_security import verify_telegram_user

TOKEN = "synthetic-test-token"
NOW = 1800000000

def signed(fields):
    data = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode({**fields, "hash": digest})

class TelegramAuthNegativeTests(unittest.TestCase):
    def valid(self):
        return {"auth_date": str(NOW), "user": json.dumps({"id": 123456, "first_name": "Synthetic"})}

    def test_valid_signed_payload(self):
        self.assertEqual(verify_telegram_user(signed(self.valid()), TOKEN, now=NOW)[0], 123456)

    def test_missing_signature(self):
        with self.assertRaises(PermissionError):
            verify_telegram_user(urllib.parse.urlencode(self.valid()), TOKEN, now=NOW)

    def test_tampered_identity(self):
        raw = signed(self.valid()).replace("123456", "123457")
        with self.assertRaises(PermissionError):
            verify_telegram_user(raw, TOKEN, now=NOW)

    def test_duplicate_user_field(self):
        raw = signed(self.valid()) + "&user=%7B%7D"
        with self.assertRaises(PermissionError):
            verify_telegram_user(raw, TOKEN, now=NOW)

    def test_expired_session(self):
        fields = self.valid()
        fields["auth_date"] = str(NOW - 86401)
        with self.assertRaises(PermissionError):
            verify_telegram_user(signed(fields), TOKEN, now=NOW)

    def test_future_session(self):
        fields = self.valid()
        fields["auth_date"] = str(NOW + 61)
        with self.assertRaises(PermissionError):
            verify_telegram_user(signed(fields), TOKEN, now=NOW)

    def test_boolean_user_id(self):
        fields = self.valid()
        fields["user"] = json.dumps({"id": True})
        with self.assertRaises(PermissionError):
            verify_telegram_user(signed(fields), TOKEN, now=NOW)

    def test_oversized_init_data(self):
        with self.assertRaises(PermissionError):
            verify_telegram_user("x" * 16385, TOKEN, now=NOW)

    def test_missing_user(self):
        fields = self.valid()
        del fields["user"]
        with self.assertRaises(PermissionError):
            verify_telegram_user(signed(fields), TOKEN, now=NOW)

if __name__ == "__main__":
    unittest.main()
