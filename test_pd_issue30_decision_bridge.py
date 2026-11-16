"""Issue 30 integration decision bridge: synthetic in-memory SQLite only."""
import unittest
import pd_document_review as reviews
import pd_issue30_decision_bridge as bridge
import test_pd_document_review_synthetic as fixtures

PILOT=fixtures.APP
DISPATCHER=fixtures.ADMIN


class Core:
    def is_admin(self, uid):
        return uid == DISPATCHER


class LiveDecisionBridgeTests(unittest.TestCase):
    setUp=fixtures.DocumentReviewSyntheticTests.setUp
    tearDown=fixtures.DocumentReviewSyntheticTests.tearDown
    upload=fixtures.DocumentReviewSyntheticTests.upload
    approve=fixtures.DocumentReviewSyntheticTests.approve

    def decision(self, target="approved", admin=DISPATCHER):
        # Tests call under the equivalent live BEGIN IMMEDIATE transaction.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result=bridge.guard_admin_approval(self.db,PILOT,target,admin,Core())
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def status(self):
        return tuple(self.db.execute(
            "SELECT status,stage FROM pd_driver_applications WHERE telegram_id=?",(PILOT,)
        ).fetchone())

    def test_stage1_approved_files_progress_to_stage2_without_mutation(self):
        for side in reviews.FIRST:self.approve(side)
        self.assertEqual(self.decision(),"stage2")
        self.assertEqual(self.status(),("pending",1))

    def test_stage1_missing_file_does_not_progress(self):
        with self.assertRaises(reviews.ReviewError):self.decision()
        self.assertEqual(self.status(),("pending",1))

    def test_stage2_pending_and_all_approved_ready_for_final(self):
        for side in reviews.FIRST+reviews.SECOND:self.approve(side)
        self.db.execute("UPDATE pd_driver_applications SET stage=2 WHERE telegram_id=?",(PILOT,))
        self.assertEqual(self.decision(),"approved")
        self.assertEqual(self.status(),("pending",2))

    def test_stage2_pending_and_only_stage1_files_blocks(self):
        for side in reviews.FIRST:self.approve(side)
        self.db.execute("UPDATE pd_driver_applications SET stage=2 WHERE telegram_id=?",(PILOT,))
        with self.assertRaises(reviews.ReviewError):self.decision()
        self.assertEqual(self.status(),("pending",2))

    def test_stage2_with_stale_sha_blocks(self):
        for side in reviews.FIRST+reviews.SECOND:self.approve(side)
        self.db.execute("UPDATE pd_driver_applications SET stage=2 WHERE telegram_id=?",(PILOT,))
        self.upload(reviews.SECOND[0],b"replacement synthetic document")
        with self.assertRaises(reviews.ReviewError):self.decision()

    def test_client_cannot_claim_dispatcher(self):
        for side in reviews.FIRST:self.approve(side)
        with self.assertRaises(PermissionError):self.decision(admin=PILOT)
        self.assertEqual(self.status(),("pending",1))

    def test_stage2_status_not_final_approval(self):
        for side in reviews.FIRST+reviews.SECOND:self.approve(side)
        self.db.execute("UPDATE pd_driver_applications SET status='stage2' WHERE telegram_id=?",(PILOT,))
        with self.assertRaises(reviews.ReviewError):self.decision()
        self.assertEqual(self.status(),("stage2",1))

    def test_existing_approved_legacy_pilot_not_changed(self):
        self.db.execute("UPDATE pd_driver_applications SET status='approved',stage=2 WHERE telegram_id=?",(PILOT,))
        self.assertEqual(self.decision(),"approved")
        self.assertEqual(self.status(),("approved",2))

    def test_nonapproval_decisions_remain_separate(self):
        self.assertEqual(self.decision("rejected"),"rejected")
        self.assertEqual(self.status(),("pending",1))

    def test_invalid_target_rejected(self):
        with self.assertRaises(reviews.ReviewError):self.decision("stage2")

    def test_missing_review_schema_fails_closed(self):
        self.db.execute("DROP TABLE pd_document_review_events")
        for side in reviews.FIRST:self.upload(side)
        with self.assertRaises(reviews.ReviewError):self.decision()
        self.assertEqual(self.status(),("pending",1))


if __name__=="__main__":
    unittest.main()
