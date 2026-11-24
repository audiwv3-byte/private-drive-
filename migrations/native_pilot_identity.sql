-- Explicit, additive photo table migration for the closed pilot only.
BEGIN;
DO $private_drive_pilot$
BEGIN
    IF current_database() NOT IN ('private_drive_test', 'pd_schema_ci') THEN
        RAISE EXCEPTION 'Refusing database outside the isolated private drive pilot';
    END IF;
END;
$private_drive_pilot$;

CREATE TABLE IF NOT EXISTS public.native_identity_checks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES public.native_auth_users(id),
    status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired')),
    photo BYTEA,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    reviewer_id TEXT REFERENCES public.native_auth_users(id),
    decided_at BIGINT
);
CREATE INDEX IF NOT EXISTS native_identity_user_created
    ON public.native_identity_checks(user_id, created_at DESC);
REVOKE ALL ON TABLE public.native_identity_checks FROM PUBLIC;
COMMIT;
