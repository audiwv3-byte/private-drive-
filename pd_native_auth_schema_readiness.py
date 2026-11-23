"""Read-only startup schema check for PRIVATE DRIVE native phone auth.

Never creates, alters, or migrates a table. It inspects only PostgreSQL
catalog metadata; no rows, phone numbers, secrets, or tokens are read.
"""
import psycopg

REQUIRED_COLUMNS = {
    "native_twilio_challenges": frozenset(
        ("id", "phone", "created_at", "expires_at", "attempts", "consumed_at")),
    "native_auth_users": frozenset(
        ("id", "channel", "destination", "created_at")),
    "native_auth_sessions": frozenset(
        ("token_hash", "user_id", "created_at", "expires_at", "revoked_at")),
    "native_auth_roles": frozenset(("user_id", "role")),
}

def inspect_native_auth_schema(database_url):
    """Return (ready, internal_code); no DDL, no user data, no logging."""
    try:
        with psycopg.connect(database_url, connect_timeout=4,
                            options="-c statement_timeout=4000") as db:
            # Catalog query is explicitly restricted to a READ ONLY transaction.
            with db.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("""SELECT c.relname, a.attname
                  FROM pg_catalog.pg_class AS c
                  JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace
                  JOIN pg_catalog.pg_attribute AS a ON a.attrelid=c.oid
                  WHERE n.nspname='public'
                    AND c.relkind IN ('r','p')
                    AND a.attnum>0 AND NOT a.attisdropped
                    AND c.relname=ANY(%s)""",
                    (list(REQUIRED_COLUMNS),))
                found = {}
                for table, column in cur.fetchall():
                    found.setdefault(table, set()).add(column)
        if any(not columns.issubset(found.get(table, set()))
               for table, columns in REQUIRED_COLUMNS.items()):
            return False, "schema_not_ready"
        return True, "ready"
    except (psycopg.Error, ValueError, TypeError):
        return False, "database_unavailable"
