"""Role authorization regression tests; no SMS, network, or production DB."""
import sqlite3
import unittest

from pd_native_auth_sessions import issue_session, revoke_session
from pd_native_auth_roles import (
    assign_pilot, authorize, bootstrap_owner, get_role,
)

SECRET = "isolated-test-bootstrap-secret-0123456789abcdef"


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.owner = issue_session(self.db, "phone", "+37060000001", now=100)
        self.pilot = issue_session(self.db, "phone", "+37060000002", now=100)
        self.stranger = issue_session(self.db, "phone", "+37060000003", now=100)
        self.db.commit()

    def test_default_passenger_and_no_public_escalation(self):
        self.assertEqual(get_role(self.db, self.owner["user_id"]), "passenger")
        self.assertIsNone(get_role(self.db, "unknown"))
        self.assertIsNone(authorize(self.db, self.owner["access_token"],
                                    required_role="admin", now=101))
        with self.assertRaises(PermissionError):
            assign_pilot(self.db, self.pilot["user_id"],
                         administrator_token=self.pilot["access_token"], now=101)
        self.assertEqual(get_role(self.db, self.pilot["user_id"]), "passenger")

    def test_bootstrap_requires_existing_user_and_private_secret(self):
        with self.assertRaises(PermissionError):
            bootstrap_owner(self.db, self.owner["user_id"],
                            supplied_secret="guessed", configured_secret=SECRET)
        with self.assertRaises(ValueError):
            bootstrap_owner(self.db, "fake-user",
                            supplied_secret=SECRET, configured_secret=SECRET)
        self.assertEqual(get_role(self.db, self.owner["user_id"]), "passenger")

    def test_exactly_one_owner_no_second_admin(self):
        bootstrap_owner(self.db, self.owner["user_id"],
                        supplied_secret=SECRET, configured_secret=SECRET)
        self.db.commit()
        self.assertEqual(get_role(self.db, self.owner["user_id"]), "admin")
        with self.assertRaises(PermissionError):
            bootstrap_owner(self.db, self.stranger["user_id"],
                            supplied_secret=SECRET, configured_secret=SECRET)
        self.assertEqual(get_role(self.db, self.stranger["user_id"]), "passenger")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO native_auth_roles(user_id,role) VALUES (?, 'admin')",
                            (self.stranger["user_id"],))

    def test_admin_can_provision_pilot_but_pilot_cannot_dispatch(self):
        bootstrap_owner(self.db, self.owner["user_id"],
                        supplied_secret=SECRET, configured_secret=SECRET)
        assign_pilot(self.db, self.pilot["user_id"],
                     administrator_token=self.owner["access_token"], now=101)
        self.db.commit()
        self.assertEqual(get_role(self.db, self.pilot["user_id"]), "pilot")
        self.assertIsNotNone(authorize(self.db, self.pilot["access_token"],
                                       required_role="pilot", now=101))
        self.assertIsNone(authorize(self.db, self.pilot["access_token"],
                                    required_role="admin", now=101))
        self.assertIsNone(authorize(self.db, self.stranger["access_token"],
                                    required_role="admin", now=101))
        self.assertIsNotNone(authorize(self.db, self.owner["access_token"],
                                       required_role="admin", now=101))
        self.assertTrue(revoke_session(self.db, self.owner["access_token"], now=102))
        self.assertIsNone(authorize(self.db, self.owner["access_token"],
                                    required_role="admin", now=103))

    def test_expired_or_forged_tokens_denied(self):
        bootstrap_owner(self.db, self.owner["user_id"],
                        supplied_secret=SECRET, configured_secret=SECRET)
        self.assertIsNone(authorize(self.db, "fake", required_role="admin", now=101))
        self.assertIsNone(authorize(self.db, self.owner["access_token"],
                                    required_role="admin", now=100+30*86400))


if __name__ == "__main__":
    unittest.main()
