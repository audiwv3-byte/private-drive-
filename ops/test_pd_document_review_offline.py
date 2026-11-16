"""Isolated issue #30 regression tests: no network or production records."""
import hashlib
import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pd_document_review as review
from flask import Flask, jsonify
from unittest.mock import patch


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("""CREATE TABLE pd_driver_applications
          (telegram_id INTEGER PRIMARY KEY, status TEXT, stage INTEGER)""")
        self.conn.execute("""CREATE TABLE pd_driver_documents
          (telegram_id INTEGER NOT NULL,side TEXT NOT NULL,image BLOB NOT NULL,
           updated_at TEXT NOT NULL,PRIMARY KEY(telegram_id,side))""")
        self.conn.execute(
            "INSERT INTO pd_driver_applications VALUES (101,'pending',1)"
        )
        for side in review.FIRST + review.SECOND:
            self.store(side, f"synthetic-original-{side}".encode())
        review.ensure_tables(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def store(self, side, data):
        self.conn.execute(
            "INSERT OR REPLACE INTO pd_driver_documents VALUES(?,?,?,?)",
            (101, side, data, "2026-11-17"),
        )
        self.conn.commit()

    def sha(self, side):
        data = self.conn.execute(
            "SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side=?",
            (side,),
        ).fetchone()[0]
        return hashlib.sha256(data).hexdigest()

    def decide(self, side, action="approved", reason=""):
        return review.decide(
            self.conn, applicant=101, side=side, action=action,
            reviewer_id=9001, expected_sha256=self.sha(side), reason=reason,
            reviewed_at="2026-11-17T01:00:00+00:00",
        )

    def test_legacy_existing_files_are_pending_not_approved(self):
        states = review.states(self.conn, 101)
        self.assertEqual(states["license_front"]["status"], "pending")
        with self.assertRaises(review.ReviewError):
            review.require_approved_documents(self.conn, 101, stage=1)

    def test_missing_file_not_approved(self):
        self.conn.execute("DELETE FROM pd_driver_documents WHERE side='license_back'")
        self.conn.commit()
        self.assertEqual(review.states(self.conn, 101)["license_back"], {"status": "missing"})
        with self.assertRaisesRegex(review.ReviewError, "Документ ещё не загружен"):
            review.decide(
                self.conn, applicant=101, side="license_back", action="approved",
                reviewer_id=9001, expected_sha256="a"*64,
            )

    def test_approve_all_first_then_second(self):
        for side in review.FIRST:
            self.decide(side)
        self.assertTrue(review.require_approved_documents(self.conn, 101, stage=1))
        with self.assertRaises(review.ReviewError):
            review.require_approved_documents(self.conn, 101, stage=2)
        for side in review.SECOND:
            self.decide(side)
        self.assertTrue(review.require_approved_documents(self.conn, 101, stage=2))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pd_document_review_events").fetchone()[0],
            len(review.FIRST + review.SECOND),
        )
        self.assertEqual(
            self.conn.execute("SELECT status,stage FROM pd_driver_applications WHERE telegram_id=101").fetchone(),
            ("pending", 1),
        )

    def test_rejection_needs_reason_and_blocks(self):
        with self.assertRaisesRegex(review.ReviewError, "причину"):
            self.decide("insurance", "rejected")
        self.decide("insurance", "rejected", "Снимок не читается")
        self.assertEqual(
            review.states(self.conn, 101)["insurance"]["reason"], "Снимок не читается"
        )
        self.assertEqual(review.states(self.conn, 101)["insurance"]["status"], "rejected")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pd_document_review_events").fetchone()[0], 1
        )

    def test_idempotence_one_audit_event(self):
        self.assertTrue(self.decide("ltsa")["changed"])
        self.assertFalse(self.decide("ltsa")["changed"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pd_document_review_events").fetchone()[0], 1
        )

    def test_stale_sha_refuses_and_no_new_event(self):
        old = self.sha("portrait")
        self.store("portrait", b"replaced-by-dispatcher")
        with self.assertRaisesRegex(review.ReviewError, "обновлён"):
            review.decide(
                self.conn, applicant=101, side="portrait", action="approved",
                reviewer_id=9001, expected_sha256=old,
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM pd_document_review_events").fetchone()[0], 0
        )

    def test_image_replacement_invalidates_previous_approval(self):
        self.decide("portrait")
        self.assertEqual(review.states(self.conn, 101)["portrait"]["status"], "approved")
        self.store("portrait", b"new-photo-other-sha")
        self.assertEqual(review.states(self.conn, 101)["portrait"]["status"], "pending")

    def test_unknown_side_and_nonexisting_applicant_rejected(self):
        with self.assertRaises(review.ReviewError):
            self.decide("not_a_side")
        with self.assertRaisesRegex(review.ReviewError, "не найдена"):
            review.decide(
                self.conn, applicant=999, side="portrait",
                reviewer_id=9001, action="approved", expected_sha256="a"*64,
            )

    def test_events_do_not_store_image_blobs(self):
        self.decide("portrait")
        columns = [
            r[1] for r in self.conn.execute("PRAGMA table_info(pd_document_review_events)")
        ]
        self.assertNotIn("image", columns)
        self.assertNotIn("phone", columns)

    def test_legacy_document_rows_untouched_by_schema(self):
        before = list(self.conn.execute("SELECT telegram_id,side,image FROM pd_driver_documents"))
        review.ensure_tables(self.conn)
        after = list(self.conn.execute("SELECT telegram_id,side,image FROM pd_driver_documents"))
        self.assertEqual(before, after)

    def test_admin_auth_is_enforced_on_both_routes(self):
        app = Flask("test_review")
        context = {"uid": 11}
        core = type("FakeCore", (), {
            "USERS_DB": "synthetic",
            "is_admin": staticmethod(lambda uid: uid == 9001),
            "db": lambda _, name: sqlite3.connect(self.path),
        })()
        review.register(app, core, lambda: (context["uid"], None))
        with app.test_client() as client:
            for method, path in (
                ("GET", "/api/admin/driver-applications/101/document-reviews"),
                ("POST", "/api/admin/driver-applications/101/document-reviews/portrait"),
            ):
                with self.assertRaises(PermissionError):
                    # propagate exceptions under TESTING=True
                    app.config["TESTING"] = True
                    if method == "GET":
                        client.get(path)
                    else:
                        client.post(path, json={
                            "status": "approved", "sha256": self.sha("portrait")
                        })
        context["uid"] = 9001
        with app.test_client() as client:
            res = client.get("/api/admin/driver-applications/101/document-reviews")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json["documents"]["portrait"]["status"], "pending")
            res = client.post(
                "/api/admin/driver-applications/101/document-reviews/portrait",
                json={"status": "approved", "sha256": self.sha("portrait")},
            )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json["ok"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReviewTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("ISSUE30_DOCUMENT_REVIEW_OFFLINE_PASS" if result.wasSuccessful()
          else "ISSUE30_DOCUMENT_REVIEW_OFFLINE_FAIL")
    raise SystemExit(0 if result.wasSuccessful() else 1)
