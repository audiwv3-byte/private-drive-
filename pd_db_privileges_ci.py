"""PRIVATE DRIVE PostgreSQL least-privilege design; SYNTHETIC CI ONLY.

No automatic connection to Render and no production credential provisioning.
Logical NOLOGIN roles model three separate trust boundaries:
- pd_ci_runtime: untrusted app data reader
- pd_ci_reviewer: trusted server-only approval executor
- pd_ci_migrator: schema owner/DDL; never available to API

Actual deployment must use distinct LOGIN credentials, role membership audits,
limited schema grants, verified backups and a separate review. Do not reuse
these CI role names or passwords in production.
"""
import os

DDL = (
"""DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pd_ci_runtime') THEN
    CREATE ROLE pd_ci_runtime NOLOGIN NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pd_ci_reviewer') THEN
    CREATE ROLE pd_ci_reviewer NOLOGIN NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pd_ci_migrator') THEN
    CREATE ROLE pd_ci_migrator NOLOGIN NOCREATEDB NOCREATEROLE;
  END IF;
END $$""",
"REVOKE CREATE ON SCHEMA public FROM PUBLIC",
"GRANT USAGE ON SCHEMA public TO pd_ci_runtime,pd_ci_reviewer,pd_ci_migrator",
"GRANT SELECT ON native_auth_sessions,native_auth_roles,native_auth_users TO pd_ci_migrator",
"ALTER TABLE pd_pilot_reviews OWNER TO pd_ci_migrator",
"ALTER TABLE pd_account_profiles OWNER TO pd_ci_migrator",
"ALTER TABLE pd_account_telegram_links OWNER TO pd_ci_migrator",
"ALTER FUNCTION pd_validate_pilot_review_actor() OWNER TO pd_ci_migrator",
# The trigger checks server roles, not client-controlled text.
# To execute inside a security-definer function it needs its own SELECT grant.
"""CREATE OR REPLACE FUNCTION pd_ci_approve_pilot(
      session_digest text, target_user text
   ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
   SET search_path=pg_catalog,public
   AS $acl$
   DECLARE actor_id text;
   BEGIN
      IF session_digest IS NULL OR length(session_digest)<>64
          OR target_user IS NULL OR length(target_user)>200 THEN
          RETURN false;
      END IF;
      SELECT s.user_id INTO actor_id
        FROM public.native_auth_sessions s
        JOIN public.native_auth_roles r ON r.user_id=s.user_id
        JOIN public.native_auth_users u ON u.id=s.user_id
       WHERE s.token_hash=session_digest
         AND s.revoked_at IS NULL
         AND s.expires_at>EXTRACT(EPOCH FROM clock_timestamp())
         AND s.created_at<=EXTRACT(EPOCH FROM clock_timestamp())
         AND r.role='admin' AND u.channel='phone';
      IF actor_id IS NULL OR actor_id=target_user THEN
         RETURN false;
      END IF;
      UPDATE public.pd_pilot_reviews p SET
           review_status='approved',
           reviewed_by=actor_id,
           reviewed_at=clock_timestamp()
       WHERE p.user_id=target_user AND p.review_status='pending'
         AND EXISTS(SELECT 1 FROM public.native_auth_roles pr
                     WHERE pr.user_id=target_user AND pr.role='pilot');
      RETURN FOUND;
   END
   $acl$""",
"ALTER FUNCTION pd_ci_approve_pilot(text,text) OWNER TO pd_ci_migrator",
"REVOKE ALL ON FUNCTION pd_ci_approve_pilot(text,text) FROM PUBLIC",
"GRANT EXECUTE ON FUNCTION pd_ci_approve_pilot(text,text) TO pd_ci_reviewer",
# View fields are intentionally whitelisted; sessions/tokens/photos absent.
"""CREATE OR REPLACE VIEW pd_ci_public_accounts WITH (security_barrier=true)
    AS SELECT u.id AS user_id,
       COALESCE(r.role,'passenger') AS role,
       COALESCE(p.display_name,'Без имени') AS display_name,
       left(u.destination,3)||'••••'||right(u.destination,2) AS phone_masked,
       (t.telegram_subject IS NOT NULL) AS telegram_linked,
       pr.review_status AS pilot_review_status
       FROM public.native_auth_users u
       LEFT JOIN public.native_auth_roles r ON r.user_id=u.id
       LEFT JOIN public.pd_account_profiles p ON p.user_id=u.id
       LEFT JOIN public.pd_account_telegram_links t ON t.user_id=u.id
       LEFT JOIN public.pd_pilot_reviews pr ON pr.user_id=u.id
       WHERE u.channel='phone'""",
"ALTER VIEW pd_ci_public_accounts OWNER TO pd_ci_migrator",
"REVOKE ALL ON pd_ci_public_accounts FROM PUBLIC",
"GRANT SELECT ON pd_ci_public_accounts TO pd_ci_runtime",
# Explicit deny of table privileges for runtime/reviewer, even if previously
# accidentally granted. They never receive table writes or role grants.
"""REVOKE ALL ON native_auth_users,native_auth_roles,native_auth_sessions,
native_identity_checks,pd_pilot_reviews,pd_account_profiles,
pd_account_telegram_links FROM pd_ci_runtime,pd_ci_reviewer""",
)


def install_synthetic_acl(conn):
    if os.environ.get("PD_CI_FAKE_DB_ONLY") != "YES":
        raise PermissionError("CI isolation gate missing")
    with conn.cursor() as cur:
        for sql in DDL:
            cur.execute(sql)
