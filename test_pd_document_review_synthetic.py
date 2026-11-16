"""Issue #30 synthetic-only contract tests. Run: python -m unittest -v test_pd_document_review_synthetic.py
Uses ONLY in-memory SQLite and fake image bytes. NEVER points at PythonAnywhere.
"""
import hashlib
import sqlite3
import unittest

import pd_document_review as review

APP = 1001
ADMIN = 9001


def sha(data):
    return hashlib.sha256(data).hexdigest()


class DocumentReviewSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE pd_driver_applications (
                telegram_id INTEGER PRIMARY KEY, status TEXT NOT NULL, stage INTEGER NOT NULL
            );
            CREATE TABLE pd_driver_documents (
                telegram_id INTEGER NOT NULL, side TEXT NOT NULL,
                image BLOB NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (telegram_id, side)
            );
            INSERT INTO pd_driver_applications VALUES (1001, 'pending', 1);
        """)
        review.ensure_tables(self.db)

    def tearDown(self):
        self.db.close()

    def upload(self, side, content=None):
        data = content or ("fake-" + side).encode()
        self.db.execute(
            "INSERT INTO pd_driver_documents VALUES (?,?,?,'synthetic') "
            "ON CONFLICT(telegram_id,side) DO UPDATE SET image=excluded.image",
            (APP, side, data)
        )
        return sha(data)

    def approve(self, side):
        return review.decide(
            self.db, applicant=APP, side=side,
            action="approved", reviewer_id=ADMIN,
            expected_sha256=self.upload(side)
        )

    def events(self):
        return self.db.execute("SELECT count(*) FROM pd_document_review_events").fetchone()[0]

    def test_historical_files_are_pending(self):
        self.upload("license_front")
        self.assertEqual(review.states(self.db, APP)["license_front"]["status"], "pending")
        self.assertEqual(review.states(self.db, APP)["license_back"]["status"], "missing")

    def test_stage1_gate_and_rejected_document(self):
        for side in review.FIRST[:-1]:
            self.approve(side)
        with self.assertRaises(review.ReviewError):
            review.require_approved_documents(self.db, APP, 1)
        side = review.FIRST[-1]
        digest = self.upload(side)
        review.decide(self.db, applicant=APP, side=side, action="rejected",
                      reason="Blurred image", reviewer_id=ADMIN, expected_sha256=digest)
        with self.assertRaises(review.ReviewError):
            review.require_approved_documents(self.db, APP, 1)
        review.decide(self.db, applicant=APP, side=side, action="approved",
                      reviewer_id=ADMIN, expected_sha256=digest)
        self.assertTrue(review.require_approved_documents(self.db, APP, 1))

    def test_final_gate_and_optional_registration_back(self):
        for side in review.FIRST + review.SECOND:
            self.approve(side)
        self.assertEqual(review.states(self.db, APP)["registration_back"]["status"], "missing")
        self.assertTrue(review.require_approved_documents(self.db, APP, 2))

    def test_stale_sha_rolls_back_without_audit(self):
        old = self.upload("license_front")
        self.upload("license_front", b"replacement synthetic bytes")
        before = self.events()
        with self.assertRaises(review.ReviewError):
            review.decide(self.db, applicant=APP, side="license_front",
                          action="approved", reviewer_id=ADMIN, expected_sha256=old)
        self.assertEqual(self.events(), before)

    def test_new_photo_invalidates_previous_approval(self):
        self.approve("license_front")
        self.upload("license_front", b"new synthetic image bytes")
        self.assertEqual(review.states(self.db, APP)["license_front"]["status"], "pending")

    def test_idempotency_and_audit(self):
        digest = self.upload("license_front")
        params = dict(applicant=APP, side="license_front", action="approved",
                      reviewer_id=ADMIN, expected_sha256=digest)
        self.assertTrue(review.decide(self.db, **params)["changed"])
        self.assertFalse(review.decide(self.db, **params)["changed"])
        self.assertEqual(self.events(), 1)

    def test_bad_side_and_rejection_reason(self):
        digest = self.upload("license_front")
        for side, action, reason in [
            ("unknown", "approved", ""),
            ("license_front", "rejected", ""),
            ("license_front", "invalid", "")
        ]:
            with self.subTest(side=side, action=action):
                with self.assertRaises(review.ReviewError):
                    review.decide(self.db, applicant=APP, side=side, action=action,
                                  reason=reason, reviewer_id=ADMIN, expected_sha256=digest)
        self.assertEqual(self.events(), 0)

    def test_no_implicit_application_approval(self):
        for side in review.FIRST + review.SECOND:
            self.approve(side)
        status = self.db.execute(
            "SELECT status FROM pd_driver_applications WHERE telegram_id=?", (APP,)
        ).fetchone()["status"]
        self.assertEqual(status, "pending")


if __name__ == "__main__":
    unittest.main()
