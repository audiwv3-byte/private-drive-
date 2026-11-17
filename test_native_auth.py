"""Local isolated tests; no network, live customers or paid messages."""
import sqlite3
import unittest
from pd_native_auth import issue_code, verify_code, normalize_destination

SECRET = b"test-only-auth-secret-32-characters-long"

class NativeAuthTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def test_email_one_time_and_expiration(self):
        cid, code = issue_code(self.db, SECRET, "email", " Test@Example.com ", now=100)
        self.assertEqual(verify_code(self.db, SECRET, cid, code, now=101), ("email", "test@example.com"))
        self.assertIsNone(verify_code(self.db, SECRET, cid, code, now=102))
        cid2, code2 = issue_code(self.db, SECRET, "email", "test@example.com", now=161)
        self.assertIsNone(verify_code(self.db, SECRET, cid2, code2, now=461))

    def test_throttle_and_attempts(self):
        cid, code = issue_code(self.db, SECRET, "phone", "+37060000000", now=100)
        with self.assertRaises(ValueError):
            issue_code(self.db, SECRET, "phone", "+37060000000", now=101)
        for _ in range(5):
            self.assertIsNone(verify_code(self.db, SECRET, cid, "000000" if code != "000000" else "111111", now=102))
        self.assertIsNone(verify_code(self.db, SECRET, cid, code, now=103))

    def test_validation(self):
        for ch, val in [("email", "invalid"), ("phone", "060000000"), ("telegram", "123")]:
            with self.assertRaises(ValueError):
                normalize_destination(ch, val)

if __name__ == "__main__":
    unittest.main()
