"""Offline-only checks for the PRIVATE DRIVE backup and verification utility."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pd_safe_backup import make_backup, verify_backup, source_files


class SafeBackupTests(unittest.TestCase):
    def test_backup_is_private_complete_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root, backups = base / "project", base / "private_snapshots"
            root.mkdir()
            required = [
                "Euro_Baltic_Transfer.py", "miniapp_server.py",
                "miniapp/templates/index.html", "pd_tips_widget.js", "pd_tips_widget.py",
            ]
            for name in required:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("PRIVATE_DRIVE_TEST_ONLY_CONTENT_" + name, encoding="utf-8")
            (root / ".env").write_text("SECRET_NEVER_COPY", encoding="utf-8")
            (root / "private.json").write_text('{"secret":"NEVER_COPY"}', encoding="utf-8")
            for name in ("orders.db", "users.db"):
                with sqlite3.connect(root / name) as db:
                    db.execute("CREATE TABLE test (value TEXT)")
                    db.execute("INSERT INTO test VALUES ('safe-test')")
            snapshot = make_backup(root, backups)
            self.assertGreaterEqual(verify_backup(snapshot), 7)
            self.assertTrue((snapshot / "orders.db").is_file())
            self.assertTrue((snapshot / "users.db").is_file())
            with sqlite3.connect(snapshot / "orders.db") as db:
                self.assertEqual(db.execute("SELECT value FROM test").fetchone()[0], "safe-test")
            self.assertFalse((snapshot / ".env").exists())
            self.assertFalse((snapshot / "private.json").exists())
            self.assertEqual(backups.stat().st_mode & 0o777, 0o700)
            self.assertEqual((snapshot / "orders.db").stat().st_mode & 0o777, 0o600)
            (snapshot / "miniapp/templates/index.html").write_text("CORRUPTED")
            with self.assertRaises(RuntimeError):
                verify_backup(snapshot)

    def test_cannot_backup_into_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("Euro_Baltic_Transfer.py", "miniapp_server.py",
                         "miniapp/templates/index.html", "pd_tips_widget.js", "pd_tips_widget.py"):
                f = root / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("safe-test-file-content-12345")
            for name in ("orders.db", "users.db"):
                with sqlite3.connect(root / name) as db:
                    db.execute("CREATE TABLE data (id INTEGER)")
            with self.assertRaises(ValueError):
                make_backup(root, root / "backups")


if __name__ == "__main__":
    unittest.main()
