"""Issue #30: test real GET-only Flask handler with opt-in admin review routes.

All registrations, files and decisions use a temporary fake SQLite.  No live
application requests, database connections or uploads.
"""
import hashlib
import io
import sqlite3
import unittest

import pd_document_review as reviews
import pd_issue30_admin_review_routes as routes
import pd_issue30_patch_live_dispatcher_offline as patched
import test_pd_issue30_live_onboarding_patch as fixture

SIDES1=("license_front","license_back","car_front","car_rear","car_interior")
SIDES2=("registration_front","ltsa","activity","insurance","portrait")


class AdminRoutesIntegration(unittest.TestCase):
    setUp = fixture.LivePatchIntegration.setUp
    tearDown = fixture.LivePatchIntegration.tearDown
    payload = fixture.LivePatchIntegration.payload
    submit = fixture.LivePatchIntegration.submit
    admin_approve = fixture.LivePatchIntegration.admin_approve
    status = fixture.LivePatchIntegration.status
    image = fixture.LivePatchIntegration.image

    @classmethod
    def setUpClass(cls):
        cls.original_source = fixture.get_verified_live_bytes().decode()
        cls.patched_source = patched.patch_source(cls.original_source.encode())
        cls.doc_images = {
            "license_front": fixture.make_photo((200,30,30)),
            "license_back": fixture.make_photo((30,200,30)),
            "car_front": fixture.make_photo((30,30,200)),
            "car_rear": fixture.make_photo((200,160,30)),
            "car_interior": fixture.make_photo((50,110,180)),
            "registration_front": fixture.make_photo((80,100,30)),
            "ltsa": fixture.make_photo((110,50,30)),
            "activity": fixture.make_photo((110,30,90)),
            "insurance": fixture.make_photo((30,140,120)),
            "portrait": fixture.make_photo((180,80,130)),
        }

    def setUp(self):
        fixture.LivePatchIntegration.setUp(self)
        with self.core.db(self.core.USERS_DB) as conn:
            conn.execute("CREATE TABLE pd_document_replacements ("
                         "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                         "telegram_id INTEGER NOT NULL, side TEXT NOT NULL,"
                         "actor_id INTEGER NOT NULL,previous_sha256 TEXT NOT NULL,"
                         "replacement_sha256 TEXT NOT NULL,replaced_at TEXT NOT NULL,"
                         "action TEXT NOT NULL CHECK(action='dispatcher_replace'))")
        routes.register(self.app, self.core, lambda:(self.current_user, {}),
                        self.onboarding.read_photos)

    def pilot_uploaded(self):
        self.assertEqual(self.submit(1,SIDES1).status_code,200)

    def meta(self, user=9001):
        self.current_user=user
        try:
            with self.app.test_client() as c:
                return c.get("/api/admin/driver-applications/1001/document-reviews")
        finally:
            self.current_user=1001

    def decide_doc(self, side, action="approved", user=9001,
                   expected=None, reason=""):
        if expected is None:
            blob=self.image(side)
            expected=hashlib.sha256(blob).hexdigest() if blob else ""
        self.current_user=user
        try:
            with self.app.test_client() as c:
                return c.post("/api/admin/driver-applications/1001/document-reviews/"+side,
                              json={"status":action,"sha256":expected,"reason":reason})
        finally:
            self.current_user=1001

    def replace_doc(self, side="license_front", user=9001, expected=None,
                    image=None):
        if expected is None:
            expected=hashlib.sha256(self.image(side) or b"").hexdigest()
        if image is None:
            image=fixture.make_photo((94,22,155))
        self.current_user=user
        try:
            with self.app.test_client() as c:
                return c.post("/api/admin/driver-applications/1001/documents/"+side+"/replace",
                    data={"expected_sha256":expected,
                          side:(io.BytesIO(image),"synthetic.jpg")})
        finally:
            self.current_user=1001

    def test_metadata_get_is_admin_only_and_no_images(self):
        self.pilot_uploaded()
        with self.assertRaises(PermissionError):
            self.meta(user=1001)
        response=self.meta()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["documents"]["license_front"]["status"],"pending")
        self.assertNotIn("image",response.json["documents"]["license_front"])

    def test_only_admin_can_decide_document(self):
        self.pilot_uploaded()
        with self.assertRaises(PermissionError):
            self.decide_doc("license_front",user=1001)
        self.assertEqual(self.meta().json["documents"]["license_front"]["status"],"pending")

    def test_admin_approves_per_side_then_stage1_advance(self):
        self.pilot_uploaded()
        for side in SIDES1:
            response=self.decide_doc(side)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json["status"],"approved")
        self.assertEqual(self.admin_approve().status_code,200)
        self.assertEqual(self.status(),("stage2",1))

    def test_unapproved_document_blocks_stage1(self):
        self.pilot_uploaded()
        for side in SIDES1[:-1]:
            self.decide_doc(side)
        with self.assertRaises(reviews.ReviewError):
            self.admin_approve()
        self.assertEqual(self.status(),("pending",1))

    def test_replace_requires_admin_before_reading_image(self):
        self.pilot_uploaded()
        with self.assertRaises(PermissionError):
            self.replace_doc(user=1001)
        self.assertEqual(self.meta().json["documents"]["license_front"]["status"],"pending")

    def test_replace_invalidates_review_and_has_audit(self):
        self.pilot_uploaded()
        self.decide_doc("license_front")
        previous=self.image("license_front")
        response=self.replace_doc()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["status"],"pending")
        self.assertNotEqual(previous,self.image("license_front"))
        self.assertEqual(self.meta().json["documents"]["license_front"]["status"],"pending")
        with self.core.db(self.core.USERS_DB) as c:
            row=c.execute("SELECT actor_id,previous_sha256,replacement_sha256 "
                          "FROM pd_document_replacements").fetchone()
            self.assertEqual(row[0],9001)
            self.assertEqual(row[1],hashlib.sha256(previous).hexdigest())
            self.assertEqual(row[2],hashlib.sha256(self.image("license_front")).hexdigest())

    def test_stale_sha_replacement_denied_without_mutation(self):
        self.pilot_uploaded()
        before=self.image("license_front")
        with self.assertRaises(reviews.ReviewError):
            self.replace_doc(expected="0"*64)
        self.assertEqual(self.image("license_front"),before)
        with self.core.db(self.core.USERS_DB) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM pd_document_replacements").fetchone()[0],0)

    def test_replacement_failure_rolls_back_photo_and_review(self):
        self.pilot_uploaded()
        self.decide_doc("license_front")
        before=self.image("license_front")
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("CREATE TRIGGER abort_replace BEFORE INSERT ON pd_document_replacements "
                      "BEGIN SELECT RAISE(ABORT,'synthetic error'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.replace_doc()
        self.assertEqual(self.image("license_front"),before)
        self.assertEqual(self.meta().json["documents"]["license_front"]["status"],"approved")

    def test_bad_side_cannot_replace(self):
        self.pilot_uploaded()
        with self.assertRaises(reviews.ReviewError):
            self.replace_doc(side="unknown")

    def test_end_to_end_approved_only_after_both_stages_reviewed(self):
        self.pilot_uploaded()
        for side in SIDES1:
            self.decide_doc(side)
        self.admin_approve()
        self.assertEqual(self.submit(2,SIDES2).status_code,200)
        for side in SIDES2:
            self.decide_doc(side)
        self.assertEqual(self.admin_approve().status_code,200)
        self.assertEqual(self.status(),("approved",2))

    def test_unchanged_original_paths_and_three_new_paths(self):
        urls={str(x) for x in self.app.url_map.iter_rules()}
        for path in (
            "/api/driver/application",
            "/api/admin/driver-applications/<int:applicant>/decision",
            "/api/admin/driver-applications/<int:applicant>/document-reviews",
            "/api/admin/driver-applications/<int:applicant>/document-reviews/<side>",
            "/api/admin/driver-applications/<int:applicant>/documents/<side>/replace",
        ):
            self.assertIn(path,urls)

if __name__=="__main__":
    unittest.main()
