"""Read-only startup schema check for PRIVATE DRIVE native phone auth.

Never creates, alters, or migrates a table. It inspects only PostgreSQL
catalog metadata; no rows, phone numbers, secrets, or tokens are read.
"""
import psycopg
import threading
import time

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


class SchemaReadinessGate:
    """Per-process, monotonic, throttled catalog probe; no background polling.

    Each request may initiate a read-only probe only after the cooldown.
    An RLock prevents concurrent requests from stampeding a recovering DB.
    Fail closed on failures, preserve the last known internal error code.
    """

    def __init__(self, database_url, *, monotonic=None, retry_seconds=15,
                 inspector=None):
        if retry_seconds < 5:
            raise ValueError("retry interval must be >= 5 seconds")
        self._url = database_url
        self._now = monotonic or time.monotonic
        self._inspector = inspector or inspect_native_auth_schema
        self._interval = retry_seconds
        self._lock = threading.Lock()
        self._checked_at = None
        self._cached = (False, "database_unavailable")

    def status(self):
        with self._lock:
            now = self._now()
            if self._checked_at is not None and (
                    0 <= now - self._checked_at < self._interval):
                return self._cached
            # Reserve the cooldown before I/O, even if the connection fails.
            self._checked_at = now
            try:
                self._cached = self._inspector(self._url)
            except Exception:
                # Do not log credentials or exception messages from drivers.
                self._cached = (False, "database_unavailable")
            return self._cached

    def mark_database_unavailable(self):
        """Throttle retries after a runtime connection failure as well."""
        with self._lock:
            self._cached = (False, "database_unavailable")
            self._checked_at = self._now()
