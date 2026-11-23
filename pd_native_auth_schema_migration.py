"""Explicit offline migration for native phone auth: NEVER imported by WSGI.

Schema DDL is intentionally separate from request handling. Before any real
migration, obtain and verify encrypted backup and separate approval. Runtime
phone auth has no CREATE privilege. This module does not execute on import.
"""
import os
import psycopg


def initialize_database(database_url):
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS native_twilio_challenges (
                id TEXT PRIMARY KEY, phone TEXT NOT NULL,
                created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, consumed_at BIGINT
            )""")
            cur.execute("""CREATE INDEX IF NOT EXISTS native_twilio_phone_created
                ON native_twilio_challenges(phone, created_at DESC)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS native_auth_users (
                id TEXT PRIMARY KEY, channel TEXT NOT NULL,
                destination TEXT NOT NULL, created_at BIGINT NOT NULL,
                UNIQUE(channel, destination)
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS native_auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES native_auth_users(id),
                created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
                revoked_at BIGINT
            )""")
            cur.execute("""CREATE INDEX IF NOT EXISTS native_sessions_user
                ON native_auth_sessions(user_id)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS native_auth_roles (
                user_id TEXT PRIMARY KEY REFERENCES native_auth_users(id),
                role TEXT NOT NULL CHECK(role IN ('passenger','pilot','admin'))
            )""")
            cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS native_auth_one_admin
                ON native_auth_roles(role) WHERE role='admin'""")


def install_native_phone_schema_from_ci_only(database_url):
    """CI-only fixture entry. NO network or Render target permitted."""
    from urllib.parse import urlsplit
    if os.environ.get("PD_CI_FAKE_DB_ONLY")!="YES":
        raise PermissionError("synthetic_migration_only")
    parts=urlsplit(database_url)
    if (parts.hostname not in ("127.0.0.1","localhost")
        or parts.port!=5432 or parts.path!="/pd_schema_ci"
        or parts.username!="pd_ci"):
        raise PermissionError("non_synthetic_database_refused")
    initialize_database(database_url)
