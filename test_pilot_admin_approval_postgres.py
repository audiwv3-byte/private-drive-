"""Security integration tests: only verified server admin session approves pilots."""
import hashlib
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from psycopg.errors import InsufficientPrivilege

from pd_unified_accounts_schema import install_schema
from pd_pilot_admin_approval import approve_pilot
from test_unified_accounts_postgres_integration import SYNTHETIC_OLD_SCHEMA

ADMIN_TOKEN = "synthetic_admin_token_" + "a" * 52
PILOT_TOKEN = "synthetic_pilot_token_" + "p" * 52
PASS_TOKEN = "synthetic_pass_token_" + "u" * 52


class PilotApprovalAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES":
            raise RuntimeError("CI staging synthetic database only")
        url = os.environ.get("PD_CI_POSTGRES_URL", "")
        parsed = urlsplit(url)
        if (parsed.scheme != "postgresql" or parsed.hostname not in ("127.0.0.1", "localhost")
                or parsed.port != 5432 or parsed.path != "/pd_schema_ci"):
            raise RuntimeError("Non-synthetic database refused")
        cls.db = psycopg.connect(url)
        with cls.db.cursor() as cur:
            for ddl in SYNTHETIC_OLD_SCHEMA:
                cur.execute(ddl)
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.rollback()
        install_schema(self.db)
        with self.db.cursor() as cur:
            cur.execute("""INSERT INTO native_auth_users(id,channel,destination,created_at)
                VALUES ('owner','phone','+37060000001',100),
                       ('pilot','phone','+37060000002',100),
                       ('passenger','phone','+37060000003',100),
                       ('second-pilot','phone','+37060000004',100)""")
            cur.execute("""INSERT INTO native_auth_roles(user_id,role)
                VALUES ('owner','admin'),('pilot','pilot'),
                       ('passenger','passenger'),('second-pilot','pilot')""")
            cur.execute("""INSERT INTO pd_pilot_reviews(user_id,review_status)
                VALUES ('pilot','pending'),('second-pilot','pending')""")
            for token, user in ((ADMIN_TOKEN, "owner"),(PILOT_TOKEN,"pilot"),
                                (PASS_TOKEN,"passenger")):
                cur.execute("""INSERT INTO native_auth_sessions
                    (token_hash,user_id,created_at,expires_at)
                    VALUES (%s,%s,100,5000)""",
                            (hashlib.sha256(token.encode()).hexdigest(),user))

    def tearDown(self):
        self.db.rollback()

    def review(self, user="pilot"):
        return self.db.execute("""SELECT review_status,reviewed_by
               FROM pd_pilot_reviews WHERE user_id=%s""", (user,)).fetchone()

    def test_approved_only_from_valid_admin_session_and_stored_role(self):
        self.assertTrue(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=200))
        self.assertEqual(self.review(),("approved","owner"))
        self.assertEqual(self.db.execute(
            "SELECT role FROM native_auth_roles WHERE user_id='pilot'").fetchone()[0],"pilot")
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=200))

    def test_passenger_and_pilot_cannot_grant_approval_or_roles(self):
        for token in (PILOT_TOKEN,PASS_TOKEN,"x"*50):
            self.assertFalse(approve_pilot(self.db,token,"pilot",now=200))
            self.assertEqual(self.review(),("pending",None))
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM native_auth_roles WHERE role='admin'").fetchone()[0],1)

    def test_no_stale_or_revoked_admin_token(self):
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=5000))
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=50))
        self.db.execute("""UPDATE native_auth_sessions SET revoked_at=150
            WHERE user_id='owner'""")
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=200))
        self.assertEqual(self.review(),("pending",None))

    def test_demotion_blocks_approval(self):
        self.db.execute("""UPDATE native_auth_roles SET role='passenger'
            WHERE user_id='owner'""")
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=200))
        self.assertEqual(self.review(),("pending",None))

    def test_self_approval_and_other_role_blocked(self):
        self.db.execute("UPDATE native_auth_roles SET role='passenger' WHERE user_id='pilot'")
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"pilot",now=200))
        self.assertFalse(approve_pilot(self.db,ADMIN_TOKEN,"owner",now=200))
        self.assertEqual(self.review(),("pending",None))

    def test_database_trigger_rejects_forged_non_admin_reviewer(self):
        with self.assertRaises(InsufficientPrivilege):
            with self.db.transaction():
                self.db.execute("""UPDATE pd_pilot_reviews
                    SET review_status='approved', reviewed_by='passenger',
                        reviewed_at=NOW() WHERE user_id='pilot'""")
        self.assertEqual(self.review(),("pending",None))

    def test_database_trigger_rejects_self_review(self):
        with self.assertRaises(InsufficientPrivilege):
            with self.db.transaction():
                self.db.execute("""UPDATE pd_pilot_reviews
                    SET review_status='approved', reviewed_by='pilot',
                        reviewed_at=NOW() WHERE user_id='pilot'""")
        self.assertEqual(self.review(),("pending",None))

    def test_database_trigger_rejects_fake_role_without_admin(self):
        with self.assertRaises(InsufficientPrivilege):
            with self.db.transaction():
                self.db.execute("""UPDATE pd_pilot_reviews
                    SET review_status='approved', reviewed_by='second-pilot',
                        reviewed_at=NOW() WHERE user_id='pilot'""")
        self.assertEqual(self.review(),("pending",None))


if __name__ == "__main__":
    unittest.main()
