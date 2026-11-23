"""PostgreSQL session operations, for explicit migration and synthetic CI only.

Never auto-apply on Render. The privileged function owner must remain outside
HTTP login credentials. No SMS or production operations.
"""
import os

SESSION_DDL = (
    """CREATE OR REPLACE FUNCTION public.pd_revoke_current_session(
         supplied_digest text, observed_at bigint
       ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
       SET search_path = pg_catalog, public
       AS $pd_logout$
       BEGIN
         IF supplied_digest IS NULL OR length(supplied_digest) <> 64
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
    """CREATE OR REPLACE FUNCTION public.pd_validate_native_session(
          supplied_digest text, observed_at bigint
       ) RETURNS TABLE(user_id text, server_role text, expires_at bigint)
       LANGUAGE sql SECURITY DEFINER STABLE
       SET search_path = pg_catalog, public
       AS $pd_verify$
         SELECT s.user_id, COALESCE(r.role, 'passenger'), s.expires_at
           FROM public.native_auth_sessions s
           JOIN public.native_auth_users u ON u.id = s.user_id
           LEFT JOIN public.native_auth_roles r ON r.user_id = s.user_id
          WHERE length(supplied_digest) = 64
            AND s.token_hash = supplied_digest
            AND s.revoked_at IS NULL
            AND s.created_at <= observed_at
            AND s.expires_at > observed_at
       $pd_verify$""",
    "REVOKE ALL ON FUNCTION public.pd_validate_native_session(text,bigint) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint) TO pd_ci_phone_auth",
)


def install_synthetic_logout_function(conn):
    if os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES":
        raise PermissionError("synthetic_ci_only")
    with conn.cursor() as cur:
        for statement in SESSION_DDL:
            cur.execute(statement)
