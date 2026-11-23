"""Synthetic-only scoped PostgreSQL grants for trusted phone-auth backend.

This role is a SERVER credential (never distributed to passengers/pilots).
Do not activate before schema initialization is moved to the migration role.
Never run against Render or use production credentials.
"""
import os

PHONE_AUTH_GRANTS = (
    """DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pd_ci_phone_auth') THEN
        CREATE ROLE pd_ci_phone_auth NOLOGIN NOCREATEROLE NOCREATEDB;
      END IF;
    END $$""",
    "GRANT USAGE ON SCHEMA public TO pd_ci_phone_auth",
    # Account registration (only an existing verified SMS flow may invoke).
    "GRANT SELECT (id,channel,destination) ON public.native_auth_users TO pd_ci_phone_auth",
    "GRANT INSERT (id,channel,destination,created_at) ON public.native_auth_users TO pd_ci_phone_auth",
    # Native role lookup: read-only; role assignment is strictly separate.
    "GRANT SELECT (user_id,role) ON public.native_auth_roles TO pd_ci_phone_auth",
    # Session creation: only hashed bearer tokens, no role writes.
    "GRANT INSERT (token_hash,user_id,created_at,expires_at) ON public.native_auth_sessions TO pd_ci_phone_auth",
    # Cooldown / verification checks; only challenge attempt state can change.
    """GRANT SELECT (id,phone,created_at,expires_at,attempts,consumed_at)
       ON public.native_twilio_challenges TO pd_ci_phone_auth""",
    "GRANT INSERT (id,phone,created_at,expires_at) ON public.native_twilio_challenges TO pd_ci_phone_auth",
    "GRANT UPDATE (attempts,consumed_at) ON public.native_twilio_challenges TO pd_ci_phone_auth",
    # No role membership, schema creation or permissions to identity documents.
)

def install_synthetic_phone_auth_grants(conn):
    if os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES":
        raise PermissionError("synthetic_postgres_only")
    with conn.cursor() as cur:
        for statement in PHONE_AUTH_GRANTS:
            cur.execute(statement)
