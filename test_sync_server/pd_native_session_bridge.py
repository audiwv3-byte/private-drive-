"""Optional PostgreSQL-backed principal lookup for the isolated sync API.

The caller explicitly injects a disposable PostgreSQL DSN. No auto-discovery,
real SMS, native authentication writes, or production configuration.
Re-evaluates expiry, revocation and current role on EVERY HTTP request.
"""
import re
import time
import psycopg


class NativePostgresPrincipalLookup:
    def __init__(self, database_url, *, clock=None):
        self.database_url = database_url
        self.clock = clock or time.time

    def __call__(self, token_sha256_hex):
        if not isinstance(token_sha256_hex, str) or not re.fullmatch(
                r"[a-f0-9]{64}", token_sha256_hex):
            return None
        try:
            with psycopg.connect(self.database_url, connect_timeout=4) as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT user_id, server_role
                         FROM public.pd_validate_native_session(%s,%s)""",
                        (token_sha256_hex, int(self.clock())))
                    row = cur.fetchone()
                    if row is None:
                        return None
                    return tuple(row)
        except (psycopg.Error, OSError):
            # DB outage fails closed; never infer roles from screen labels.
            return None
