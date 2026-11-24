-- Apply explicitly as the isolated test DB owner, not an HTTP runtime user.
-- Behavior matches the existing native session functions used in PostgreSQL CI.
BEGIN;
DO $private_drive_pilot$
BEGIN
    IF current_database() NOT IN ('private_drive_test', 'pd_schema_ci') THEN
        RAISE EXCEPTION 'Refusing database outside the isolated private drive pilot';
    END IF;
END;
$private_drive_pilot$;

CREATE OR REPLACE FUNCTION public.pd_validate_native_session(
    supplied_digest text, observed_at bigint
) RETURNS TABLE(user_id text, server_role text, expires_at bigint)
LANGUAGE sql SECURITY DEFINER STABLE
SET search_path = pg_catalog, pg_temp
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
$pd_verify$;

CREATE OR REPLACE FUNCTION public.pd_revoke_current_session(
    supplied_digest text, observed_at bigint
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
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
END;
$pd_logout$;

REVOKE ALL ON FUNCTION public.pd_validate_native_session(text,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_revoke_current_session(text,bigint) FROM PUBLIC;
COMMIT;
