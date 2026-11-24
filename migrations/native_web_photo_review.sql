-- Explicit isolated database migration. No default bindings or automatic grants.
BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'private_drive_test' THEN
    RAISE EXCEPTION 'native web photo review requires private_drive_test';
  END IF;
END;
$guard$;

-- An offline, independently verified link, never set by the app or web route.
CREATE TABLE IF NOT EXISTS public.pd_web_photo_review_links (
    browser_admin_id BIGINT PRIMARY KEY CHECK (browser_admin_id > 0),
    native_reviewer_id TEXT NOT NULL UNIQUE REFERENCES public.native_auth_users(id),
    -- Server-only, domain-separated HMAC. Never the cookie's plain version.
    credential_proof TEXT NOT NULL CHECK (credential_proof ~ '^[0-9a-f]{64}$'),
    verified_at BIGINT NOT NULL CHECK (verified_at > 0),
    revoked_at BIGINT
);

-- The operator must independently verify reviewer and enrolled pilot are
-- different people, not merely different opaque native account IDs.
CREATE TABLE IF NOT EXISTS public.pd_web_photo_review_pairs (
    browser_admin_id BIGINT NOT NULL REFERENCES public.pd_web_photo_review_links(browser_admin_id)
      ON DELETE CASCADE,
    native_pilot_id TEXT NOT NULL REFERENCES public.native_auth_users(id),
    distinct_person_verified_at BIGINT NOT NULL CHECK (distinct_person_verified_at > 0),
    revoked_at BIGINT,
    PRIMARY KEY (browser_admin_id, native_pilot_id)
);

CREATE TABLE IF NOT EXISTS public.pd_web_photo_review_claims (
    browser_admin_id BIGINT PRIMARY KEY REFERENCES public.pd_web_photo_review_links(browser_admin_id)
      ON DELETE CASCADE,
    check_id TEXT NOT NULL UNIQUE REFERENCES public.native_identity_checks(id) ON DELETE CASCADE,
    claim_hash TEXT NOT NULL UNIQUE CHECK (claim_hash ~ '^[0-9a-f]{64}$'),
    expires_at BIGINT NOT NULL,
    credential_proof TEXT NOT NULL CHECK (credential_proof ~ '^[0-9a-f]{64}$')
);
REVOKE ALL ON public.pd_web_photo_review_links, public.pd_web_photo_review_pairs,
    public.pd_web_photo_review_claims FROM PUBLIC;

-- Internal helpers are not granted to the browser runtime. Lock existing
-- binding and role so a concurrent revocation cannot leave an accepted action.
CREATE OR REPLACE FUNCTION public.pd_web_photo_review_actor(
    p_browser_admin BIGINT, p_proof TEXT, p_now BIGINT
) RETURNS TEXT LANGUAGE sql
SET search_path = pg_catalog, pg_temp
AS $actor$
    SELECT b.native_reviewer_id
      FROM public.pd_web_photo_review_links b
      JOIN public.native_auth_roles r ON r.user_id = b.native_reviewer_id
     WHERE b.browser_admin_id = p_browser_admin AND b.credential_proof = p_proof
       AND b.revoked_at IS NULL AND b.verified_at <= p_now
       AND r.role IN ('admin', 'dispatcher')
     FOR UPDATE OF b FOR SHARE OF r;
$actor$;

-- Restrict to independently verified distinct people and the same first-party
-- native photo contract. Keep this selection private to SQL.
CREATE OR REPLACE FUNCTION public.pd_web_photo_review_case(
    p_browser_admin BIGINT, p_actor TEXT, p_now BIGINT, p_existing_check TEXT
) RETURNS TABLE(check_id TEXT, clean_jpeg BYTEA, photo_expires BIGINT)
LANGUAGE sql
SET search_path = pg_catalog, pg_temp
AS $choose_case$
    SELECT c.id, c.photo, c.expires_at
      FROM public.native_identity_checks c
      JOIN public.pd_web_photo_review_pairs p ON p.native_pilot_id = c.user_id
      JOIN public.native_auth_roles r ON r.user_id = c.user_id
     WHERE p.browser_admin_id = p_browser_admin AND p.revoked_at IS NULL
       AND p.distinct_person_verified_at <= p_now
       AND c.user_id <> p_actor AND r.role = 'pilot'
       AND c.status = 'pending' AND c.created_at <= p_now AND c.expires_at > p_now
       AND c.photo IS NOT NULL AND octet_length(c.photo) BETWEEN 4 AND 2097152
       AND substring(c.photo FROM 1 FOR 2) = decode('ffd8', 'hex')
       AND substring(c.photo FROM octet_length(c.photo)-1 FOR 2) = decode('ffd9', 'hex')
       AND (p_existing_check IS NULL OR c.id = p_existing_check)
       AND NOT EXISTS (
          SELECT 1 FROM public.native_identity_checks n
           WHERE n.user_id = c.user_id AND (n.created_at, n.id) > (c.created_at, c.id)
       )
       AND (p_existing_check IS NOT NULL OR NOT EXISTS (
          SELECT 1 FROM public.pd_web_photo_review_claims cl
           WHERE cl.check_id = c.id AND cl.expires_at > p_now
       ))
     ORDER BY c.created_at, c.id LIMIT 1
     FOR UPDATE OF c SKIP LOCKED FOR SHARE OF p, r;
$choose_case$;

-- Each call returns at most one already-sanitized JPEG; no native IDs, queue
-- listing, photo blob table access, or pictures after expiry.
CREATE OR REPLACE FUNCTION public.pd_open_web_native_photo_review(
    p_browser_admin BIGINT, p_proof TEXT, p_claim_hash TEXT
) RETURNS BYTEA LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $open$
DECLARE
  v_actor TEXT;
  v_now BIGINT := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
  v_case RECORD;
BEGIN
  IF current_database() <> 'private_drive_test' OR p_browser_admin IS NULL
     OR p_proof IS NULL OR p_proof !~ '^[0-9a-f]{64}$'
     OR p_claim_hash IS NULL OR p_claim_hash !~ '^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
  v_actor := public.pd_web_photo_review_actor(p_browser_admin, p_proof, v_now);
  IF v_actor IS NULL THEN RETURN NULL; END IF;
  v_now := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
  IF EXISTS (SELECT 1 FROM public.pd_web_photo_review_claims cl
              WHERE cl.browser_admin_id = p_browser_admin AND cl.expires_at > v_now)
  THEN RETURN NULL; END IF;

  SELECT * INTO v_case FROM public.pd_web_photo_review_case(p_browser_admin, v_actor, v_now, NULL);
  IF NOT FOUND THEN RETURN NULL; END IF;
  v_now := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
  IF v_case.photo_expires <= v_now THEN RETURN NULL; END IF;
  DELETE FROM public.pd_web_photo_review_claims cl
    WHERE cl.expires_at <= v_now AND (cl.browser_admin_id = p_browser_admin OR cl.check_id = v_case.check_id);
  INSERT INTO public.pd_web_photo_review_claims
    (browser_admin_id, check_id, claim_hash, expires_at, credential_proof)
    VALUES (p_browser_admin, v_case.check_id, p_claim_hash,
            least(v_now + 180, v_case.photo_expires), p_proof);
  RETURN v_case.clean_jpeg;
END;
$open$;

CREATE OR REPLACE FUNCTION public.pd_decide_web_native_photo_review(
    p_browser_admin BIGINT, p_proof TEXT, p_claim_hash TEXT, p_decision TEXT
) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $decide$
DECLARE
  v_actor TEXT;
  v_now BIGINT := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
  v_claim RECORD;
  v_case RECORD;
BEGIN
  IF current_database() <> 'private_drive_test' OR p_browser_admin IS NULL
     OR p_proof IS NULL OR p_proof !~ '^[0-9a-f]{64}$'
     OR p_claim_hash IS NULL OR p_claim_hash !~ '^[0-9a-f]{64}$'
     OR p_decision IS NULL OR p_decision NOT IN ('approved','rejected') THEN RETURN false; END IF;
  v_actor := public.pd_web_photo_review_actor(p_browser_admin, p_proof, v_now);
  IF v_actor IS NULL THEN RETURN false; END IF;
  v_now := floor(extract(epoch FROM clock_timestamp()))::BIGINT;

  SELECT cl.check_id, cl.expires_at INTO v_claim FROM public.pd_web_photo_review_claims cl
    WHERE cl.browser_admin_id = p_browser_admin AND cl.claim_hash = p_claim_hash
      AND cl.expires_at > v_now AND cl.credential_proof = p_proof FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT * INTO v_case
    FROM public.pd_web_photo_review_case(p_browser_admin, v_actor, v_now, v_claim.check_id);
  IF NOT FOUND THEN RETURN false; END IF;
  v_now := floor(extract(epoch FROM clock_timestamp()))::BIGINT;
  IF v_claim.expires_at <= v_now OR v_case.photo_expires <= v_now THEN RETURN false; END IF;

  UPDATE public.native_identity_checks c
    SET status = p_decision, photo = NULL, reviewer_id = v_actor, decided_at = v_now
    WHERE c.id = v_case.check_id AND c.user_id <> v_actor AND c.status = 'pending'
      AND c.expires_at > v_now;
  IF NOT FOUND THEN RETURN false; END IF;
  DELETE FROM public.pd_web_photo_review_claims cl WHERE cl.browser_admin_id = p_browser_admin
    AND cl.claim_hash = p_claim_hash;
  RETURN true;
END;
$decide$;

REVOKE ALL ON FUNCTION public.pd_web_photo_review_actor(BIGINT,TEXT,BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_web_photo_review_case(BIGINT,TEXT,BIGINT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_open_web_native_photo_review(BIGINT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.pd_decide_web_native_photo_review(BIGINT,TEXT,TEXT,TEXT) FROM PUBLIC;
COMMIT;
