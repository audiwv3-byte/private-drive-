"""Safe offline tests for protected staging PostgreSQL export."""
import os
import unittest
from unittest.mock import patch

from ops.private_drive_encrypted_pg_backup import source_env, validate_environment


class BackupGuardTests(unittest.TestCase):
    def test_only_known_staging_database_is_allowed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "incorrect_staging_database"):
                source_env("postgresql://dbuser:secret@localhost/production")
            with self.assertRaisesRegex(ValueError, "incorrect_staging_database"):
                source_env("postgresql://dbuser:secret@localhost/private_drive_test_copy")
            env=source_env("postgresql://dbuser:secret@localhost/private_drive_test")
            self.assertEqual(env["PGDATABASE"], "private_drive_test")
            self.assertEqual(env["PGPASSWORD"], "secret")
            self.assertEqual(env["PGSSLMODE"], "require")

    def test_no_backup_without_explicit_approval(self):
        with patch.dict(os.environ, {
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_BACKUP_SOURCE_URL": "postgresql://dbuser:secret@localhost/private_drive_test",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "not_explicitly_authorized"):
                validate_environment()

    def test_backup_never_targets_production(self):
        with patch.dict(os.environ, {
            "PD_DISPATCH_STAGING_ONLY": "0",
            "PD_BACKUP_EXPLICIT_APPROVAL": "YES",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "not_isolated_staging"):
                validate_environment()


if __name__ == "__main__":
    unittest.main()
