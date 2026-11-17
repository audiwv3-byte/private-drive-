"""Offline tests for isolated PRIVATE DRIVE account sessions."""
import sqlite3
import unittest

from pd_native_auth_sessions import (
    SESSION_TTL_SECONDS, issue_session, authenticate_session, revoke_session,
)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")

    def test_verified_user_reuses_account_and_rotates_token(self):
        first = issue_session(self.db, "phone", "+37060000000", now=100)
        second = issue_session(self.db, "phone", "+37060000000", now=200)
        self.assertEqual(first["user_id"], second["user_id"])
        self.assertNotEqual(first["access_token"], second["access_token"])
        self.assertEqual(authenticate_session(self.db, first["access_token"], now=201)["user_id"], first["user_id"])
        rows = self.db.execute("SELECT token_hash FROM native_auth_sessions").fetchall()
        self.assertNotIn(first["access_token"], [row[0] for row in rows])
        self.assertIsNone(authenticate_session(self.db, first["access_token"], now=100 + SESSION_TTL_SECONDS))

    def test_revocation_and_validation(self):
        issued = issue_session(self.db, "email", " TEST@example.com ", now=500)
        self.assertTrue(revoke_session(self.db, issued["access_token"], now=501))
        self.assertIsNone(authenticate_session(self.db, issued["access_token"], now=502))
        self.assertFalse(revoke_session(self.db, issued["access_token"], now=503))
        with self.assertRaises(ValueError):
            issue_session(self.db, "phone", "not-a-phone", now=500)


if __name__ == "__main__":
    unittest.main()
