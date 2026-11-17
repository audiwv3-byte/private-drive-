"""Issue #30: test actual deployed dispatcher route after in-memory dual patch.

Only GET reads deployed Python source. No production requests/SQLite.
All Flask clients, uploads and document approvals use synthetic local SQLite.
"""
import hashlib
import sqlite3
import unittest

import pd_document_review as reviews
import pd_issue30_patch_live_dispatcher_offline as patcher
import pd_issue30_patch_live_onboarding_offline as onboarding_patcher
import test_pd_issue30_live_onboarding_patch as baseline

PILOT=1001
ADMIN=9001
FIRST=("license_front","license_back","car_front","car_rear","car_interior")
SECOND=("registration_front","ltsa","activity","insurance","portrait")


class GuardedDispatcherEndToEnd(unittest.TestCase):
    # Reuse synthetic fake server/test client, without inheriting baseline tests.
    setUp=baseline.LivePatchIntegration.setUp
    tearDown=baseline.LivePatchIntegration.tearDown
    payload=baseline.LivePatchIntegration.payload
    submit=baseline.LivePatchIntegration.submit
    admin_approve=baseline.LivePatchIntegration.admin_approve
    status=baseline.LivePatchIntegration.status
    image=baseline.LivePatchIntegration.image

    @classmethod
    def setUpClass(cls):
        raw=baseline.get_verified_live_bytes()
        cls.original_source=raw.decode("utf-8")
        cls.patched_source=patcher.patch_source(raw)
        cls.doc_images={
            "license_front": baseline.make_photo((220, 30, 30)),
            "license_back": baseline.make_photo((20, 220, 20)),
            "car_front": baseline.make_photo((20, 20, 220)),
            "car_rear": baseline.make_photo((240, 190, 30)),
            "car_interior": baseline.make_photo((60, 120, 180)),
            "registration_front": baseline.make_photo((60, 120, 30)),
            "ltsa": baseline.make_photo((120, 60, 30)),
            "activity": baseline.make_photo((120, 30, 80)),
            "insurance": baseline.make_photo((30, 150, 140)),
            "portrait": baseline.make_photo((190, 80, 150)),
        }

    def first(self):
        response=self.submit(1,FIRST)
        self.assertEqual(response.status_code,200)

    def approve_sides(self,sides):
        for side in sides:
            blob=self.image(side)
            self.assertIsNotNone(blob)
            with self.core.db(self.core.USERS_DB) as c:
                reviews.decide(c,applicant=PILOT,side=side,
                               action="approved",reviewer_id=ADMIN,
                               expected_sha256=hashlib.sha256(blob).hexdigest())

    def stage2(self):
        self.first()
        self.approve_sides(FIRST)
        self.assertEqual(self.admin_approve().status_code,200)
        self.assertEqual(self.status(),("stage2",1))
        self.assertEqual(self.submit(2,SECOND).status_code,200)
        self.assertEqual(self.status(),("pending",2))

    def test_stage1_unreviewed_documents_blocked(self):
        self.first()
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",1))
        with self.core.db(self.core.USERS_DB) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pd_driver_application_decisions").fetchone()[0],0)

    def test_stage1_only_four_explicit_reviews_blocked(self):
        self.first()
        self.approve_sides(FIRST[:-1])
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",1))

    def test_first_stage_review_advances_to_stage2_not_approved(self):
        self.first()
        self.approve_sides(FIRST)
        self.assertEqual(self.admin_approve().status_code,200)
        self.assertEqual(self.status(),("stage2",1))

    def test_stage2_submission_unreviewed_blocks_final(self):
        self.stage2()
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",2))

    def test_full_stage1_and_stage2_review_final_approval(self):
        self.stage2()
        self.approve_sides(SECOND)
        self.assertEqual(self.admin_approve().status_code,200)
        self.assertEqual(self.status(),("approved",2))
        with self.core.db(self.core.USERS_DB) as c:
            changes=c.execute("SELECT old_status,new_status FROM pd_driver_application_decisions "
                              "ORDER BY id").fetchall()
            self.assertEqual([(r[0],r[1]) for r in changes],
                             [("pending","stage2"),("pending","approved")])

    def test_second_stage_one_missing_review_blocks_final(self):
        self.stage2()
        self.approve_sides(SECOND[:-1])
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",2))

    def test_rejected_review_blocks_approval(self):
        self.first()
        self.approve_sides(FIRST)
        with self.core.db(self.core.USERS_DB) as c:
            image=self.image("license_front")
            reviews.decide(c,applicant=PILOT,side="license_front",
                           action="rejected",reason="Not readable",
                           reviewer_id=ADMIN,
                           expected_sha256=hashlib.sha256(image).hexdigest())
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",1))

    def test_changed_photo_hash_invalidates_prior_review(self):
        self.first()
        self.approve_sides(FIRST)
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("UPDATE pd_driver_documents SET image=? "
                      "WHERE telegram_id=? AND side=?",
                      (b"new synthetic document",PILOT,"license_back"))
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",1))

    def test_unauthorized_dispatcher_cannot_approve_reviewed_files(self):
        self.first()
        self.approve_sides(FIRST)
        with self.app.test_client() as client:
            with self.assertRaises(PermissionError):
                client.post("/api/admin/driver-applications/1001/decision",
                            json={"status":"approved"})
        self.assertEqual(self.status(),("pending",1))

    def test_failed_decision_audit_rolls_back_status_change(self):
        self.first()
        self.approve_sides(FIRST)
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON "
                      "pd_driver_application_decisions BEGIN "
                      "SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",1))
        with self.core.db(self.core.USERS_DB) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pd_driver_application_decisions").fetchone()[0],0)

    def test_missing_review_schema_blocks_without_creating(self):
        self.first()
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("DROP TABLE pd_document_review_events")
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        with self.core.db(self.core.USERS_DB) as c:
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master "
                                        "WHERE name='pd_document_review_events'").fetchone())
        self.assertEqual(self.status(),("pending",1))

    def test_read_only_routes_unchanged(self):
        routes={str(r) for r in self.app.url_map.iter_rules()}
        for expected in ("/api/driver/application",
                         "/api/admin/driver-applications",
                         "/api/admin/driver-applications/<int:applicant>/decision",
                         "/api/driver/documents/<int:applicant>/<side>"):
            self.assertIn(expected,routes)

    def test_patch_refuses_changed_server_source(self):
        with self.assertRaises(onboarding_patcher.PatchMismatch):
            patcher.patch_source(self.original_source.encode()+b"\n# stale")


if __name__=="__main__":
    unittest.main()
