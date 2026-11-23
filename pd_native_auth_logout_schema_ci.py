"""Explicit PostgreSQL logout function DDL for privileged migration only.

Not installed at import, not mounted into production. The function acts on
ONLY the supplied bearer-token digest; callers cannot select user IDs or roles.
Keep its PostgreSQL owner as the privileged migration account, never the app.
"""
import os
from urllib.parse import urlsplit

LOGOUT_DDL = (
    """CREATE OR REPLACE FUNCTION public.pd_revoke_current_session(
         supplied_digest text, observed_at bigint
       ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
       SET search_path = pg_catalog, public
       AS $pd_logout$
       BEGIN
         IF supplied_digest IS NULL OR length(supplied_digest) <> 64
            OR supplied_digest !~ '^[0-9a-f]{64}$'
            OR observed_at IS NULL OR observed_at < 0 THEN
           RETURN false;
         END IF;
         UPDATE public.native_auth_sessions
            SET revoked_at = observed_at
          WHERE token_hash = supplied_digest
            AND revoked_at IS NULL
            AND created_at <= observed_at
            AND expires_at > observed_at;
         RETURN FOUND;
       END
       $pd_logout$""",
    "REVOKE ALL ON FUNCTION public.pd_revoke_current_session(text,bigint) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pd_revoke_current_session(text,bigint) TO pd_ci_phone_auth",
)


def install_synthetic_logout_function(conn):
    if os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES":
        raise PermissionError("synthetic_ci_only")
    with conn.cursor() as cur:
        for statement in LOGOUT_DDL:
            cur.execute(statement)
