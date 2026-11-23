"""Unit tests: no real database connections, no logs of database secrets."""
import unittest
from pd_db_connection_transition import (
    ROLE_VARIABLES, audit_transition, compatibility_matrix, _parse_url,
)


class CredentialTransitionTests(unittest.TestCase):
    def fixture(self):
        return {
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_DISPATCH_DATABASE_URL": "existing-not-inspected",
            "PD_DB_RUNTIME_URL": "postgresql://runtime_pass:test-1@db.example/private_drive_test",
            "PD_DB_REVIEWER_URL": "postgresql://reviewer:test-2@db.example/private_drive_test",
            "PD_DB_MIGRATOR_URL": "postgresql://migrator:test-3@db.example/private_drive_test",
        }

    def test_complete_candidate_staging_topology(self):
        result=audit_transition(self.fixture())
        self.assertTrue(result.ready_for_next_review)
        self.assertEqual(result.candidate_roles, ("runtime","reviewer","migrator"))
        self.assertEqual(result.legacy_configured, ("PD_DISPATCH_DATABASE_URL",))
        self.assertNotIn("test-1",repr(result))

    def test_no_new_database_urls_requires_no_migration(self):
        env=self.fixture()
        for name in ROLE_VARIABLES.values():
            env.pop(name)
        result=audit_transition(env)
        self.assertFalse(result.ready_for_next_review)
        self.assertIn("three_candidates_required",result.codes)

    def test_production_fails_closed(self):
        env=self.fixture()
        env["PD_DISPATCH_STAGING_ONLY"]="0"
        self.assertIn("not_isolated_staging",audit_transition(env).codes)

    def test_live_sms_fails_closed(self):
        env=self.fixture()
        env["PD_NATIVE_SMS_LIVE"]="YES"
        self.assertIn("real_sms_is_active",audit_transition(env).codes)

    def test_reused_role_account_fails(self):
        env=self.fixture()
        env["PD_DB_REVIEWER_URL"]=env["PD_DB_RUNTIME_URL"]
        self.assertIn("shared_database_login",audit_transition(env).codes)

    def test_unexpected_database_fails(self):
        env=self.fixture()
        env["PD_DB_RUNTIME_URL"]="postgresql://runtime:x@db.example/production"
        self.assertIn("runtime_invalid",audit_transition(env).codes)

    def test_different_server_fails(self):
        env=self.fixture()
        env["PD_DB_REVIEWER_URL"]="postgresql://reviewer:x@wrong.example/private_drive_test"
        self.assertIn("different_databases",audit_transition(env).codes)

    def test_role_cannot_use_current_admin_or_ci_account(self):
        env=self.fixture()
        env["PD_DB_RUNTIME_URL"]="postgresql://private_drive_test_user:x@db.example/private_drive_test"
        self.assertIn("privileged_or_ci_login",audit_transition(env).codes)

    def test_inputs_with_url_options_and_newlines_are_rejected(self):
        for raw in (
            "postgresql://runtime:x@db.example/private_drive_test?sslmode=disable",
            "postgresql://runtime:x@db.example/private_drive_test\n",
            "postgresql://runtime:x@db.example/private_drive_test#fragment",
            "postgresql://runtime:x@db.example:invalid/private_drive_test",
        ):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                _parse_url(raw)

    def test_registry_toggle_blocks_claim_of_ready(self):
        env=self.fixture()
        env["PD_DISPATCH_REGISTRY_ENABLED"]="1"
        self.assertIn("registry_already_enabled",audit_transition(env).codes)

    def test_compatibility_matrix_accounts_for_write_paths(self):
        matrix=compatibility_matrix()
        self.assertIn("insert session"," ".join(matrix["native_phone_auth"]))
        self.assertIn("recover"," ".join(matrix["dispatcher_auth"]))
        self.assertIn("no DDL"," ".join(matrix["migrations"]))


if __name__=="__main__":
    unittest.main()
