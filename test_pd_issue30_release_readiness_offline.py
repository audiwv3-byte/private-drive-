"""Synthetic-only release gates: never contact PythonAnywhere or touch real DB."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pd_issue30_release_readiness_offline as safety

class ReleaseReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="pd-issue30-release-synthetic-")
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.execute("CREATE TABLE pd_driver_applications("
                        "telegram_id INTEGER PRIMARY KEY,status TEXT NOT NULL,stage INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE pd_driver_documents("
                        "telegram_id INTEGER NOT NULL,side TEXT NOT NULL,image BLOB NOT NULL,"
                        "updated_at TEXT NOT NULL,PRIMARY KEY(telegram_id,side))")
        self.db.execute("INSERT INTO pd_driver_applications VALUES(1001,'pending',1)")
        self.db.execute("INSERT INTO pd_driver_documents VALUES(1001,'license_front',X'010203','synthetic')")
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
    def filepath(self,name):
        return Path(self.tmp.name)/name

    def test_all_required_dependencies_resolve(self):
        self.assertTrue(safety.check_dependencies())

    def test_source_sha_mismatch_fails_closed(self):
        for content in (b"",b"wrong version",None,True):
            with self.subTest(content=content):
                with self.assertRaises(safety.ReleaseBlocked):
                    safety.verify_source_sha(content)

    def test_verified_backup_and_restore_preserve_legacy_rows(self):
        backup=self.filepath("before.sqlite")
        digest=safety.backup_sqlite(self.db,backup)
        self.assertEqual(len(digest),64)
        restored=self.filepath("restored.sqlite")
        self.assertTrue(safety.verify_restore_copy(backup,restored,digest))
        with sqlite3.connect(restored) as readback:
            self.assertEqual(readback.execute(
                "SELECT status,stage FROM pd_driver_applications WHERE telegram_id=1001"
            ).fetchone(),("pending",1))
            self.assertEqual(readback.execute(
                "SELECT image FROM pd_driver_documents WHERE telegram_id=1001 AND side='license_front'"
            ).fetchone()[0],b"\x01\x02\x03")

    def test_backup_refuses_overwriting_prior_snapshot(self):
        path=self.filepath("existing.sqlite")
        path.write_bytes(b"existing")
        with self.assertRaises(safety.ReleaseBlocked):
            safety.backup_sqlite(self.db,path)
        self.assertEqual(path.read_bytes(),b"existing")

    def test_tampered_backup_does_not_restore(self):
        backup=self.filepath("backup.sqlite")
        digest=safety.backup_sqlite(self.db,backup)
        backup.write_bytes(backup.read_bytes()+b"tamper")
        target=self.filepath("restore.sqlite")
        with self.assertRaises(safety.ReleaseBlocked):
            safety.verify_restore_copy(backup,target,digest)
        self.assertFalse(target.exists())

    def test_migration_creates_only_review_tables_not_changes_applicants(self):
        before=self.db.execute(
            "SELECT telegram_id,status,stage FROM pd_driver_applications"
        ).fetchall()
        self.db.execute("BEGIN IMMEDIATE")
        safety.migrate_synthetic(self.db)
        self.db.commit()
        self.assertEqual(self.db.execute(
            "SELECT telegram_id,status,stage FROM pd_driver_applications"
        ).fetchall(),before)
        self.assertEqual(self.db.execute(
            "SELECT image FROM pd_driver_documents"
        ).fetchone()[0],b"\x01\x02\x03")

    def test_migration_rollback_removes_new_tables(self):
        self.db.execute("BEGIN IMMEDIATE")
        safety.migrate_synthetic(self.db)
        self.db.rollback()
        tables={r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertNotIn("pd_document_reviews",tables)
        self.assertNotIn("pd_document_replacements",tables)
        self.assertIn("pd_driver_documents",tables)

    def test_migration_requires_write_transaction(self):
        with self.assertRaises(safety.ReleaseBlocked):
            safety.migrate_synthetic(self.db)

    def test_migration_is_idempotent_for_synthetic_schema(self):
        self.db.execute("BEGIN IMMEDIATE")
        safety.migrate_synthetic(self.db)
        safety.migrate_synthetic(self.db)
        self.db.commit()
        count=self.db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND name IN ('pd_document_reviews','pd_document_review_events','pd_document_replacements')"
        ).fetchone()[0]
        self.assertEqual(count,3)

    def test_restore_refuses_existing_destination(self):
        backup=self.filepath("backup.sqlite")
        digest=safety.backup_sqlite(self.db,backup)
        dest=self.filepath("already.sqlite")
        dest.write_bytes(b"must remain")
        with self.assertRaises(safety.ReleaseBlocked):
            safety.verify_restore_copy(backup,dest,digest)
        self.assertEqual(dest.read_bytes(),b"must remain")

if __name__=="__main__":
    unittest.main()
