-- Apply explicitly by the isolated private_drive_test migration owner only.
-- Requires native_auth_session_functions.sql and native_closed_pilot_invites.sql.
-- No role grants, operator credentials, invite codes, or production schema writes.
BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'private_drive_test' THEN
    RAISE EXCEPTION 'pilot invite onboarding migration requires private_drive_test';
  END IF;
END;
$guard$;

ALTER TABLE public.pd_native_closed_pilot_invites
  ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'passenger'
    CONSTRAINT pd_native_closed_invite_purpose CHECK (purpose IN ('passenger', 'pilot'));

CREATE TABLE IF NOT EXISTS public.pd_native_closed_invite_sessions (
  token_hash TEXT PRIMARY KEY REFERENCES public.native_auth_sessions(token_hash) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('passenger', 'pilot'))
);
REVOKE ALL ON TABLE public.pd_native_closed_invite_sessions FROM PUBLIC;
-- Preserve the purpose of already issued invite sessions, including through
-- any later operator migration of the credential channel.
INSERT INTO public.pd_native_closed_invite_sessions (token_hash, purpose)
  SELECT s.token_hash, 'passenger'
    FROM public.native_auth_sessions s
    JOIN public.native_auth_users u ON u.id = s.user_id
   WHERE u.channel = 'invite'
  ON CONFLICT (token_hash) DO NOTHING;

-- Share the per-account lock with issuance and role mutation. Read the live
-- role only after taking that lock. Purpose is taken from the stored invite,
-- never from an HTTP parameter. The runtime can only call the narrow wrappers.
CREATE OR REPLACE FUNCTION public.pd_redeem_closed_invite_bound(
  p_invite_hash TEXT, p_session_hash TEXT, p_purpose TEXT
) RETURNS TABLE(user_id TEXT, server_role TEXT, expires_at BIGINT)
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
  v_user TEXT;
  v_purpose TEXT;
  v_now BIGINT;
  v_expiry BIGINT;
BEGIN
  IF current_database() <> 'private_drive_test'
     OR p_invite_hash IS NULL OR p_invite_hash !~ '^[0-9a-f]{64}$'
     OR p_session_hash IS NULL OR p_session_hash !~ '^[0-9a-f]{64}$' THEN
    RETURN;
  END IF;

  SELECT u.id INTO v_user
    FROM public.native_auth_users u
    JOIN public.pd_native_closed_pilot_invites inv ON inv.user_id = u.id
   WHERE inv.invite_hash = p_invite_hash AND u.channel = 'invite'
   FOR UPDATE OF u;
  IF NOT FOUND THEN RETURN; END IF;

  v_now := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
  v_expiry := v_now + 604800;

  UPDATE public.pd_native_closed_pilot_invites inv
     SET consumed_at = v_now
   WHERE inv.invite_hash = p_invite_hash
     AND inv.user_id = v_user
     AND inv.consumed_at IS NULL AND inv.created_at <= v_now AND inv.expires_at > v_now
     AND inv.purpose = p_purpose
     AND inv.purpose = COALESCE((
       SELECT r.role FROM public.native_auth_roles r WHERE r.user_id = v_user
     ), 'passenger')
  RETURNING inv.purpose INTO v_purpose;
  IF NOT FOUND THEN RETURN; END IF;

  INSERT INTO public.native_auth_sessions (token_hash, user_id, created_at, expires_at)
    VALUES (p_session_hash, v_user, v_now, v_expiry);
  INSERT INTO public.pd_native_closed_invite_sessions (token_hash, purpose)
    VALUES (p_session_hash, v_purpose);
  RETURN QUERY SELECT v_user, v_purpose, v_expiry;
END;
$function$;

CREATE OR REPLACE FUNCTION public.pd_redeem_closed_pilot_invite(
  p_invite_hash TEXT, p_session_hash TEXT
) RETURNS TABLE(user_id TEXT, server_role TEXT, expires_at BIGINT)
LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $passenger$
  SELECT * FROM public.pd_redeem_closed_invite_bound(p_invite_hash, p_session_hash, 'passenger');
$passenger$;

CREATE OR REPLACE FUNCTION public.pd_redeem_closed_pilot_account_invite(
  p_invite_hash TEXT, p_session_hash TEXT
) RETURNS TABLE(user_id TEXT, server_role TEXT, expires_at BIGINT)
LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $pilot_accounts$
  SELECT * FROM public.pd_redeem_closed_invite_bound(p_invite_hash, p_session_hash, 'pilot');
$pilot_accounts$;

-- Preserve unbound legacy passenger invites and non-invite (e.g. phone)
-- sessions. Never reinterpret an invite session as a different current role.
CREATE OR REPLACE FUNCTION public.pd_validate_native_session(
  supplied_digest TEXT, observed_at BIGINT
) RETURNS TABLE(user_id TEXT, server_role TEXT, expires_at BIGINT)
LANGUAGE sql SECURITY DEFINER STABLE
SET search_path = pg_catalog, pg_temp
AS $session$
  SELECT s.user_id, COALESCE(r.role, 'passenger'), s.expires_at
    FROM public.native_auth_sessions s
    JOIN public.native_auth_users u ON u.id = s.user_id
    LEFT JOIN public.native_auth_roles r ON r.user_id = s.user_id
    LEFT JOIN public.pd_native_closed_invite_sessions b ON b.token_hash = s.token_hash
   WHERE length(supplied_digest) = 64
     AND s.token_hash = supplied_digest
     AND s.revoked_at IS NULL
     AND s.created_at <= observed_at
     AND s.expires_at > observed_at
     AND ((b.token_hash IS NULL AND u.channel <> 'invite') OR
         (u.channel = 'invite' AND b.purpose = COALESCE(r.role, 'passenger')
          AND b.purpose IN ('passenger', 'pilot')));
$session$;

-- Revoke outstanding credentials on any invite-account role transition,
-- including demotion followed by re-promotion; old codes and tokens cannot
-- come back to life. No change to non-invite accounts or to role grants.
CREATE OR REPLACE FUNCTION public.pd_revoke_closed_invite_on_role_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $revoke$
DECLARE
  v_old TEXT;
  v_new TEXT;
  v_now BIGINT;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.user_id = NEW.user_id AND OLD.role = NEW.role THEN
    RETURN NEW;
  END IF;
  IF TG_OP <> 'INSERT' THEN v_old := OLD.user_id; END IF;
  IF TG_OP <> 'DELETE' THEN v_new := NEW.user_id; END IF;

  PERFORM 1 FROM public.native_auth_users u
    WHERE u.id IN (v_old, v_new) AND u.channel = 'invite'
    ORDER BY u.id FOR UPDATE;
  IF FOUND THEN
    v_now := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
    UPDATE public.native_auth_sessions s SET revoked_at = v_now
      FROM public.native_auth_users u
      WHERE s.user_id = u.id AND u.id IN (v_old, v_new)
        AND u.channel = 'invite' AND s.revoked_at IS NULL;
    UPDATE public.pd_native_closed_pilot_invites inv SET consumed_at = v_now
      FROM public.native_auth_users u
      WHERE inv.user_id = u.id AND u.id IN (v_old, v_new)
        AND u.channel = 'invite' AND inv.consumed_at IS NULL;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$revoke$;

DROP TRIGGER IF EXISTS pd_closed_invite_revoke_on_role_change ON public.native_auth_roles;
CREATE TRIGGER pd_closed_invite_revoke_on_role_change
  BEFORE INSERT OR UPDATE OR DELETE ON public.native_auth_roles
  FOR EACH ROW EXECUTE FUNCTION public.pd_revoke_closed_invite_on_role_change();

REVOKE ALL ON FUNCTION public.pd_redeem_closed_invite_bound(TEXT, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_redeem_closed_pilot_invite(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_redeem_closed_pilot_account_invite(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_validate_native_session(TEXT, BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_revoke_closed_invite_on_role_change() FROM PUBLIC;
COMMIT;
