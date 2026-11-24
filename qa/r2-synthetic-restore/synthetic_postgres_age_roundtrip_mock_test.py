"""Offline guard tests; PostgreSQL/age commands are NOT executed by this file."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from synthetic_archive_policy import EXCLUDE_DATA
from synthetic_postgres_age_roundtrip import Blocked, PORT, Rehearsal, SOURCE, TARGET


class OfflineGuardTests(unittest.TestCase):
    def make_runner(self, root):
        with patch("shutil.which", side_effect=lambda tool, **_: "/fake/" + tool):
            return Rehearsal(Path(root))

    def test_private_socket_and_minimal_environment(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ, {"PGHOST": "remote", "PGHOSTADDR": "remote",
                         "PGSERVICE": "real", "PGPASSWORD": "fixture"},
        ):
            runner = self.make_runner(root)
            for database in (SOURCE, TARGET):
                args = runner.pgargs(database)
                self.assertEqual(args[:4], ("-h", str(runner.socket), "-p", PORT))
                self.assertEqual(args[-2:], ("-d", database))
            self.assertEqual(set(k for k in runner.env if k.startswith("PG")), {"PGCONNECT_TIMEOUT"})
            self.assertEqual(runner.socket.stat().st_mode & 0o777, 0o700)
            with self.assertRaisesRegex(Blocked, "NON_SYNTHETIC"):
                runner.pgargs("real_database_refused")

    def test_catalog_drift_blocks_before_archive_or_pg_dump(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_runner(root)
            with patch.object(runner, "relation_names", return_value=[
                "native_auth_users", "native_auth_roles", "unreviewed_photo_archive",
            ]), patch.object(runner, "pipe") as pipeline:
                with self.assertRaisesRegex(ValueError, "uncategorized_relation"):
                    runner.archive("unsafe.age", "synthetic-recipient")
                pipeline.assert_not_called()
                self.assertFalse((Path(root) / "unsafe.age").exists())

    def test_actual_archive_entry_uses_reviewed_exclusion_and_encrypted_sink(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_runner(root)
            sql_catalog = [
                "native_auth_users", "native_auth_roles", "pd_pilot_reviews", *sorted(EXCLUDE_DATA),
            ]
            def fake_pipe(leader, follower, output):
                self.assertEqual(leader[0], "pg_dump")
                for table in EXCLUDE_DATA:
                    self.assertIn(f"--exclude-table-data-and-children=public.{table}", leader)
                self.assertNotIn("--exclude-table-data-and-children=public.pd_pilot_reviews", leader)
                self.assertIn("--no-large-objects", leader)
                self.assertEqual(follower, ("age", "--encrypt", "--recipient", "synthetic-recipient"))
                output.write(b"age-encryption.org/v1\nsynthetic-stub-no-crypto")
            with patch.object(runner, "relation_names", return_value=sql_catalog), patch.object(
                runner, "pipe", side_effect=fake_pipe,
            ) as pipeline:
                dest = runner.archive("synthetic.age", "synthetic-recipient")
                self.assertTrue(dest.is_file())
                pipeline.assert_called_once()

    def test_rejects_non_age_header_and_fails_closed_without_tools(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_runner(root)
            with patch.object(runner, "relation_names", return_value=[
                "native_auth_users", "native_auth_roles",
            ]), patch.object(runner, "pipe", side_effect=lambda _x, _y, output: output.write(b"wrong")):
                with self.assertRaisesRegex(Blocked, "NOT_AGE_ARCHIVE"):
                    runner.archive("invalid.age", "synthetic-recipient")
                self.assertFalse((Path(root) / "invalid.age").exists())
        with tempfile.TemporaryDirectory() as root, patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(Blocked, "MISSING_OFFLINE_TOOLS .*pg_dump.*age"):
                Rehearsal(Path(root))


if __name__ == "__main__":
    unittest.main()
