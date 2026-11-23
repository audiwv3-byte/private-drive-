"""Synthetic-only PostgreSQL 18 fixtures and restore integrity verification.

Never connects to Render. Only local Docker PostgreSQL bound to 127.0.0.1:5432,
behind a CI-only explicit environment gate. No external credentials are used.
"""
import hashlib
import json
import os
import sys
from urllib.parse import urlsplit

import psycopg

from pd_unified_accounts_schema import install_schema
from test_unified_accounts_postgres_integration import SYNTHETIC_OLD_SCHEMA

TABLES = (
    "native_auth_users", "native_auth_roles", "native_auth_sessions",
    "native_identity_checks", "pd_account_telegram_links",
    "pd_pilot_reviews", "pd_account_profiles",
)


def connection(database):
    if os.getenv("PD_CI_FAKE_DB_ONLY") != "YES":
        raise RuntimeError("synthetic_ci_only")
    url = os.getenv("PD_CI_POSTGRES_URL", "")
    u = urlsplit(url)
    if (u.scheme != "postgresql" or u.hostname != "127.0.0.1"
            or u.port != 5432 or u.path != "/pd_schema_ci"
            or u.username != "pd_ci" or database not in
            ("pd_schema_ci", "pd_schema_restored")):
        raise RuntimeError("external_database_refused")
    return psycopg.connect(url.replace("/pd_schema_ci", "/" + database))


def seed():
    with connection("pd_schema_ci") as db:
        with db.cursor() as cur:
            for ddl in SYNTHETIC_OLD_SCHEMA:
                cur.execute(ddl)
        install_schema(db)
        with db.cursor() as cur:
            cur.execute("""INSERT INTO native_auth_users(id,channel,destination,created_at)
                VALUES ('ci-user-1','phone','+37060000001',1001),
                       ('ci-pilot-2','phone','+37060000002',1002),
                       ('ci-admin-3','phone','+37060000003',1003)""")
            cur.execute("""INSERT INTO native_auth_roles(user_id,role)
                VALUES ('ci-user-1','passenger'),('ci-pilot-2','pilot'),
                       ('ci-admin-3','admin')""")
            cur.execute("""INSERT INTO native_auth_sessions
                (token_hash,user_id,created_at,expires_at,revoked_at)
                VALUES ('synthetic-hash-ci','ci-user-1',1001,9999999999,NULL),
                       ('synthetic-revoked-ci','ci-pilot-2',1001,9999999999,1100)""")
            cur.execute("""INSERT INTO native_identity_checks
                (id,user_id,status,photo,created_at,expires_at)
                VALUES ('ci-check','ci-pilot-2','pending',
                        decode('000102ff','hex'),1001,2001)""")
            cur.execute("""INSERT INTO pd_account_telegram_links
                (user_id,telegram_subject,verified_at,verification_method)
                VALUES ('ci-user-1','123456789',
                        '2026-01-02 03:04:05+00','telegram_oidc')""")
            cur.execute("""INSERT INTO pd_pilot_reviews
                (user_id,review_status,application_id,reviewed_by,reviewed_at)
                VALUES ('ci-pilot-2','approved','ci-application',
                        'ci-admin-3','2026-01-02 03:04:05+00')""")
            cur.execute("""INSERT INTO pd_account_profiles
                (user_id,display_name,consent_version,consent_recorded_at)
                VALUES ('ci-user-1','Test passenger','test-v1',
                        '2026-01-02 03:04:05+00'),
                       ('ci-pilot-2','Test pilot','test-v1',
                        '2026-01-02 03:04:05+00')""")
    print("SYNTHETIC_FIXTURE_CREATED")


def db_signature(db):
    """Stable data and schema digest; never include real data in output."""
    digest = hashlib.sha256()
    with db.cursor() as cur:
        for table in TABLES:
            cur.execute("SELECT to_jsonb(x)::text FROM public." + table + " AS x")
            records = sorted(row[0] for row in cur.fetchall())
            if not records:
                raise AssertionError("empty_synthetic_table")
            digest.update(json.dumps([table, records], separators=(",", ":")).encode())
        cur.execute("""SELECT tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname='public' AND tablename=ANY(%s)
            ORDER BY tablename,indexname""", (list(TABLES),))
        indexes = cur.fetchall()
        if not indexes:
            raise AssertionError("indexes_not_restored")
        digest.update(json.dumps(indexes, separators=(",", ":")).encode())
        cur.execute("""SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid)
            FROM pg_constraint WHERE connamespace='public'::regnamespace
              AND conrelid=ANY(%s::regclass[])
            ORDER BY conrelid::regclass::text,conname""",
                    (list(TABLES),))
        constraints = cur.fetchall()
        if not constraints:
            raise AssertionError("constraints_not_restored")
        digest.update(json.dumps(constraints, separators=(",", ":")).encode())
    return digest.hexdigest()


def verify():
    with connection("pd_schema_ci") as original, connection("pd_schema_restored") as restored:
        before = db_signature(original)
        after = db_signature(restored)
        if before != after:
            raise AssertionError("encrypted_restore_integrity_mismatch")
    print("ENCRYPTED_RESTORE_INTEGRITY_OK")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("seed", "verify"):
            raise ValueError("seed_or_verify_required")
        {"seed": seed, "verify": verify}[sys.argv[1]]()
    except Exception:
        # Never include connection details or row content in logs.
        print("SYNTHETIC_CI_CHECK_FAILED", file=sys.stderr)
        sys.exit(1)
