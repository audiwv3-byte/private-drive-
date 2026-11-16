"""Synthetic-only adapter tests. No production credentials, network, or files."""
import sqlite3
import unittest

import pd_document_review as review
import pd_issue30_stage_adapter as adapter
from test_pd_document_review_synthetic import DocumentReviewSyntheticTests, APP, ADMIN


class AdapterIntegrationTests(DocumentReviewSyntheticTests):
    # unittest also executes inherited baseline tests, intentionally.
    def test_stage1_missing_document_fails_closed(self):
        with self.assertRaises(review.ReviewError):
            adapter.guard_first_stage(self.db, APP)
        self.assertEqual(self.db.execute(
            "SELECT status FROM pd_driver_applications WHERE telegram_id=?", (APP,)
        ).fetchone()[0], "pending")

    def test_stage1_all_approved_allows_no_implicit_transition(self):
        for side in review.FIRST:
            self.approve(side)
        self.assertTrue(adapter.guard_first_stage(self.db, APP))
        self.assertEqual(self.db.execute(
            "SELECT status FROM pd_driver_applications WHERE telegram_id=?", (APP,)
        ).fetchone()[0], "pending")

    def test_final_requires_verified_stage2_submission(self):
        for side in review.FIRST + review.SECOND:
            self.approve(side)
        for evidence in (None, False, 1, "true"):
            with self.subTest(evidence=evidence):
                with self.assertRaises(adapter.IntegrationNotReady):
                    adapter.guard_final_stage(self.db, APP, evidence)
        self.assertTrue(adapter.guard_final_stage(self.db, APP, True))

    def test_final_rejected_document_blocks(self):
        for side in review.FIRST + review.SECOND:
            self.approve(side)
        side = review.SECOND[0]
        self.db.execute("UPDATE pd_document_reviews SET status='rejected' "
                        "WHERE telegram_id=? AND side=?", (APP, side))
        with self.assertRaises(review.ReviewError):
            adapter.guard_final_stage(self.db, APP, True)

    def test_final_stale_photo_blocks(self):
        for side in review.FIRST + review.SECOND:
            self.approve(side)
        self.upload(review.SECOND[0], b"different synthetic bytes")
        with self.assertRaises(review.ReviewError):
            adapter.guard_final_stage(self.db, APP, True)

    def test_final_wrong_status_rejected(self):
        for side in review.FIRST + review.SECOND:
            self.approve(side)
        self.db.execute("UPDATE pd_driver_applications SET status='stage2' WHERE telegram_id=?", (APP,))
        with self.assertRaises(review.ReviewError):
            adapter.guard_final_stage(self.db, APP, True)

    def test_missing_review_schema_fails_closed_without_creating_it(self):
        self.db.execute("DROP TABLE pd_document_review_events")
        with self.assertRaises(adapter.IntegrationNotReady):
            adapter.guard_first_stage(self.db, APP)
        self.assertFalse(self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='pd_document_review_events'"
        ).fetchone())

    def test_preapproved_legacy_pilot_unchanged(self):
        self.db.execute("UPDATE pd_driver_applications SET status='approved' WHERE telegram_id=?", (APP,))
        with self.assertRaises(review.ReviewError):
            adapter.guard_final_stage(self.db, APP, True)
        self.assertEqual(self.db.execute(
            "SELECT status FROM pd_driver_applications WHERE telegram_id=?", (APP,)
        ).fetchone()[0], "approved")


if __name__ == "__main__":
    unittest.main()
