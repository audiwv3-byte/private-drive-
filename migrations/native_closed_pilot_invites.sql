-- Explicit operator migration for the named isolated pilot DB; never run by WSGI.
BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'private_drive_test' THEN
    RAISE EXCEPTION 'closed pilot migration refused outside private_drive_test';
  END IF;
END
$guard$;
CREATE TABLE IF NOT EXISTS public.pd_native_closed_pilot_invites (
  invite_hash TEXT PRIMARY KEY CHECK (invite_hash ~ '^[0-9a-f]{64}$'),
  user_id TEXT NOT NULL REFERENCES public.native_auth_users(id),
  created_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL CHECK (expires_at > created_at AND expires_at <= created_at + 86400),
  consumed_at BIGINT
);
REVOKE ALL ON TABLE public.pd_native_closed_pilot_invites FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.pd_redeem_closed_pilot_invite(
  p_invite_hash TEXT, p_session_hash TEXT
) RETURNS TABLE(user_id TEXT, server_role TEXT, expires_at BIGINT)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
  v_now BIGINT := floor(extract(epoch FROM statement_timestamp()))::BIGINT;
  v_user TEXT;
  v_session_expiry BIGINT := v_now + 604800;
BEGIN
  IF current_database() <> 'private_drive_test'
     OR p_invite_hash IS NULL OR p_invite_hash !~ '^[0-9a-f]{64}$'
     OR p_session_hash IS NULL OR p_session_hash !~ '^[0-9a-f]{64}$' THEN
    RETURN;
  END IF;

  UPDATE public.pd_native_closed_pilot_invites AS inv
     SET consumed_at = v_now
    FROM public.native_auth_users AS usr
   WHERE inv.invite_hash = p_invite_hash
     AND inv.consumed_at IS NULL AND inv.created_at <= v_now AND inv.expires_at > v_now
     AND usr.id = inv.user_id AND usr.channel = 'invite'
     AND NOT EXISTS (
       SELECT 1 FROM public.native_auth_roles AS role
        WHERE role.user_id = usr.id AND role.role <> 'passenger'
     )
  RETURNING inv.user_id INTO v_user;
  IF NOT FOUND THEN
    RETURN;
  END IF;

  INSERT INTO public.native_auth_sessions (token_hash, user_id, created_at, expires_at)
    VALUES (p_session_hash, v_user, v_now, v_session_expiry);
  RETURN QUERY SELECT v_user, 'passenger'::TEXT, v_session_expiry;
END
$function$;

REVOKE ALL ON FUNCTION public.pd_redeem_closed_pilot_invite(TEXT, TEXT) FROM PUBLIC;
COMMIT;
