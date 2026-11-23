"""Offline unit tests for opt-in schema, no database writes."""
import unittest
from pd_unified_accounts_schema import (
    SCHEMA, install_schema, validate_telegram_subject,
    safe_dispatcher_registry_sql, PILOT_LABELS
)


class FakeCursor:
    def __init__(self):
        self.statements = []
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def execute(self, statement):
        self.statements.append(statement)


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
    def cursor(self):
        return self.cursor_instance


class UnifiedAccountSchemaTests(unittest.TestCase):
    def test_schema_is_additive_and_requires_explicit_install(self):
        conn = FakeConnection()
        self.assertEqual(conn.cursor_instance.statements, [])
        install_schema(conn)
        self.assertEqual(tuple(conn.cursor_instance.statements), SCHEMA)
        self.assertTrue(all(stmt.startswith("CREATE ") for stmt in SCHEMA))
        self.assertTrue(all("DROP " not in stmt and "ALTER " not in stmt
                            for stmt in SCHEMA))
        self.assertIn("REFERENCES native_auth_users(id)", SCHEMA[0])
        self.assertIn("reviewed_by IS NOT NULL", SCHEMA[1])
        self.assertIn("telegram_subject TEXT NOT NULL UNIQUE", SCHEMA[0])

    def test_telegram_identity_requires_verified_server_subject(self):
        self.assertEqual(validate_telegram_subject("7035610182"), "7035610182")
        for unsafe in ("", "0", "-12", "John", " 123", "123\n456", "1" * 21, None):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                validate_telegram_subject(unsafe)

    def test_dispatcher_projection_excludes_private_documents_and_tokens(self):
        sql = safe_dispatcher_registry_sql()
        for forbidden in ("token_hash", "encrypted_bytes", "license_front",
                          "native_auth_sessions", "native_twilio_challenges",
                          "photo BYTEA"):
            self.assertNotIn(forbidden, sql)
        self.assertIn("WHERE u.channel='phone'", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertEqual(PILOT_LABELS["pending"], "На проверке")


if __name__ == "__main__":
    unittest.main()
