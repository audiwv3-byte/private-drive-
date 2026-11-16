"""Issue #30 document storage: synthetic-only SQLite tests, no network or user data."""
import hashlib
import sqlite3
import unittest

import pd_document_review as reviews
import pd_issue30_document_storage_guard as guard

PILOT=1001
ADMIN=9001


def sha(b):
    return hashlib.sha256(b).hexdigest()


class StorageGuardTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(":memory:",isolation_level=None)
        self.c.row_factory=sqlite3.Row
        self.c.executescript("""
        CREATE TABLE pd_driver_applications (
          telegram_id INTEGER PRIMARY KEY, status TEXT NOT NULL, stage INTEGER NOT NULL);
        CREATE TABLE pd_driver_documents (
          telegram_id INTEGER NOT NULL,side TEXT NOT NULL,image BLOB NOT NULL,
          updated_at TEXT NOT NULL, PRIMARY KEY(telegram_id,side));
        INSERT INTO pd_driver_applications VALUES (1001,'pending',1);
        """)
        reviews.ensure_tables(self.c)
        guard.ensure_tables(self.c)

    def tearDown(self):
        self.c.close()

    def tx(self, func, **kw):
        self.c.execute("BEGIN IMMEDIATE")
        try:
            out=func(self.c,**kw)
            self.c.commit()
            return out
        except BaseException:
            self.c.rollback()
            raise

    def upload(self, side="license_front", image=b"synthetic original"):
        return self.tx(guard.pilot_insert_missing,
                       applicant=PILOT,side=side,image=image)

    def replace(self, side="license_front", image=b"synthetic replacement",
                expected_sha256=None, actor_id=ADMIN, is_admin=None):
        if expected_sha256 is None:
            expected_sha256=sha(b"synthetic original")
        if is_admin is None:
            is_admin=lambda uid:uid==ADMIN
        return self.tx(guard.dispatcher_replace,
                       applicant=PILOT,side=side,image=image,
                       expected_sha256=expected_sha256,
                       actor_id=actor_id,is_admin=is_admin)

    def original(self,side="license_front"):
        row=self.c.execute(
            "SELECT image FROM pd_driver_documents WHERE telegram_id=? AND side=?",
            (PILOT,side)).fetchone()
        return bytes(row[0]) if row else None

    def audit_count(self):
        return self.c.execute("SELECT COUNT(*) FROM pd_document_replacements").fetchone()[0]

    def test_pilot_first_upload_succeeds(self):
        self.assertTrue(self.upload()["inserted"])
        self.assertEqual(self.original(),b"synthetic original")

    def test_pilot_cannot_replace_existing_document(self):
        self.upload()
        with self.assertRaises(guard.DocumentStorageError):
            self.upload(image=b"new bytes")
        self.assertEqual(self.original(),b"synthetic original")

    def test_pilot_cannot_replace_with_same_bytes(self):
        self.upload()
        with self.assertRaises(guard.DocumentStorageError):self.upload()
        self.assertEqual(self.audit_count(),0)

    def test_pilot_upload_stage2_not_before_stage1_approval(self):
        with self.assertRaises(guard.DocumentStorageError):
            self.upload("insurance")
        self.assertIsNone(self.original("insurance"))

    def test_pilot_stage2_can_add_missing_second_side(self):
        self.c.execute("UPDATE pd_driver_applications SET stage=2,status='pending'")
        self.upload("insurance",b"stage2 insurance")
        self.assertEqual(self.original("insurance"),b"stage2 insurance")

    def test_pilot_stage2_cannot_replace_stage1_file(self):
        self.upload()
        self.c.execute("UPDATE pd_driver_applications SET stage=2,status='pending'")
        with self.assertRaises(guard.DocumentStorageError):
            self.upload(image=b"replacement attempted")
        self.assertEqual(self.original(),b"synthetic original")

    def test_pilot_approved_cannot_upload(self):
        self.c.execute("UPDATE pd_driver_applications SET status='approved'")
        with self.assertRaises(guard.DocumentStorageError):self.upload()

    def test_dispatcher_replace_invalidates_review_and_audits(self):
        self.upload()
        reviews.decide(self.c,applicant=PILOT,side="license_front",
                       action="approved",reviewer_id=ADMIN,
                       expected_sha256=sha(b"synthetic original"))
        self.assertEqual(reviews.states(self.c,PILOT)["license_front"]["status"],"approved")
        r=self.replace()
        self.assertEqual(r["status"],"pending")
        self.assertEqual(self.original(),b"synthetic replacement")
        self.assertEqual(reviews.states(self.c,PILOT)["license_front"]["status"],"pending")
        self.assertEqual(self.audit_count(),1)
        row=self.c.execute("SELECT actor_id,previous_sha256,replacement_sha256 "
                           "FROM pd_document_replacements").fetchone()
        self.assertEqual(row["actor_id"],ADMIN)
        self.assertEqual(row["previous_sha256"],sha(b"synthetic original"))
        self.assertEqual(row["replacement_sha256"],sha(b"synthetic replacement"))

    def test_pilot_cannot_claim_dispatcher(self):
        self.upload()
        with self.assertRaises(PermissionError):
            self.replace(actor_id=PILOT)
        self.assertEqual(self.original(),b"synthetic original")
        self.assertEqual(self.audit_count(),0)

    def test_stale_sha_rejected_without_write(self):
        self.upload()
        with self.assertRaises(guard.DocumentStorageError):
            self.replace(expected_sha256=sha(b"old unread image"))
        self.assertEqual(self.original(),b"synthetic original")
        self.assertEqual(self.audit_count(),0)

    def test_replacement_same_bytes_is_noop(self):
        self.upload()
        r=self.replace(image=b"synthetic original")
        self.assertFalse(r["changed"])
        self.assertEqual(self.audit_count(),0)

    def test_missing_file_cannot_be_replaced(self):
        with self.assertRaises(guard.DocumentStorageError):
            self.replace()
        self.assertEqual(self.audit_count(),0)

    def test_bad_side_refused(self):
        with self.assertRaises(guard.DocumentStorageError):
            self.upload("../secrets",b"bad")
        self.assertEqual(self.c.execute("SELECT count(*) FROM pd_driver_documents").fetchone()[0],0)

    def test_invalid_expected_sha_refused(self):
        self.upload()
        with self.assertRaises(guard.DocumentStorageError):
            self.replace(expected_sha256="bad")
        self.assertEqual(self.audit_count(),0)

    def test_review_schema_missing_denies_dispatcher(self):
        self.upload()
        self.c.execute("DROP TABLE pd_document_replacements")
        with self.assertRaises(guard.DocumentStorageError):
            self.replace()
        self.assertEqual(self.original(),b"synthetic original")

    def test_transaction_required_for_both_apis(self):
        with self.assertRaises(guard.DocumentStorageError):
            guard.pilot_insert_missing(self.c,applicant=PILOT,side="license_front",image=b"fake")
        with self.assertRaises(guard.DocumentStorageError):
            guard.dispatcher_replace(self.c,applicant=PILOT,side="license_front",
                                     image=b"fake",expected_sha256=sha(b"fake"),
                                     actor_id=ADMIN,is_admin=lambda uid:True)

    def test_dispatcher_cannot_replace_approved_pilot(self):
        self.upload()
        self.c.execute("UPDATE pd_driver_applications SET status='approved'")
        with self.assertRaises(guard.DocumentStorageError):
            self.replace()
        self.assertEqual(self.original(),b"synthetic original")

    def test_replacement_failure_rolls_back_image_review_and_audit(self):
        self.upload()
        reviews.decide(self.c,applicant=PILOT,side="license_front",
                       action="approved",reviewer_id=ADMIN,
                       expected_sha256=sha(b"synthetic original"))
        self.c.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON pd_document_replacements "
                       "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):self.replace()
        self.assertEqual(self.original(),b"synthetic original")
        self.assertEqual(reviews.states(self.c,PILOT)["license_front"]["status"],"approved")
        self.assertEqual(self.audit_count(),0)

    def test_unknown_pilot_does_not_insert(self):
        with self.assertRaises(guard.DocumentStorageError):
            self.tx(guard.pilot_insert_missing,applicant=9999,
                    side="license_front",image=b"fake")
        self.assertEqual(self.c.execute("SELECT count(*) FROM pd_driver_documents").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
