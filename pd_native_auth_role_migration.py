"""Offline, explicit native role CHECK migration. No startup migrations.

Preserves all existing users, sessions, role assignments, the unique-admin
index, and restricted SQL GRANTs. Does not assign or elevate any role.
Never import this module in WSGI startup.
"""
from urllib.parse import urlsplit
import os
import psycopg

ROLES = ("passenger", "pilot", "dispatcher", "pilot_dispatcher", "admin")
CHECK_NAME = "native_auth_roles_role_check"


def migrate_roles_on_connection(conn):
    """Run only as an independently authorized migration owner transaction."""
    with conn.cursor() as cur:
        cur.execute("LOCK TABLE public.native_auth_roles IN ACCESS EXCLUSIVE MODE")
        cur.execute("""SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'public.native_auth_roles'::regclass
              AND conname = %s AND contype = 'c'""", (CHECK_NAME,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("expected_old_role_constraint_missing")
        existing = row[0]
        if not all(role in existing for role in ("passenger","pilot","admin")):
            raise RuntimeError("unexpected_role_constraint")
        if "dispatcher" in existing:
            if all(role in existing for role in ROLES):
                return False
            raise RuntimeError("unexpected_partial_role_constraint")
        cur.execute("""ALTER TABLE public.native_auth_roles
                       DROP CONSTRAINT native_auth_roles_role_check""")
        cur.execute("""ALTER TABLE public.native_auth_roles
            ADD CONSTRAINT native_auth_roles_role_check
            CHECK (role IN
              ('passenger','pilot','dispatcher','pilot_dispatcher','admin'))""")
        return True


def migrate_roles_synthetic_ci_only(database_url):
    """Strictly gated CI fixture; never a production migration command."""
    u = urlsplit(database_url)
    if (os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES"
            or u.scheme != "postgresql" or u.hostname != "127.0.0.1"
            or u.port != 5432 or u.username != "pd_ci"
            or not u.path.startswith("/pd_") or not u.path.endswith("_ci")):
        raise PermissionError("non_synthetic_role_migration_refused")
    with psycopg.connect(database_url) as db:
        return migrate_roles_on_connection(db)
