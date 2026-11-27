"""Staging-only unified accounts schema. No auto-migration and no HTTP writes.

Canonical user ID is native_auth_users.id. Telegram subject binding requires a
server-verified Telegram identity AND explicit account-link authorization; never
auto-merge users by unverified phone or allow role self-assignment.
"""
import re

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS pd_account_telegram_links (
       user_id TEXT PRIMARY KEY REFERENCES native_auth_users(id) ON DELETE CASCADE,
       telegram_subject TEXT NOT NULL UNIQUE
           CHECK (telegram_subject ~ '^[1-9][0-9]{0,19}$'),
       verified_at TIMESTAMPTZ NOT NULL,
       verification_method TEXT NOT NULL
           CHECK (verification_method = 'telegram_oidc'),
       linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS pd_pilot_reviews (
       user_id TEXT PRIMARY KEY REFERENCES native_auth_users(id) ON DELETE CASCADE,
       review_status TEXT NOT NULL DEFAULT 'pending'
          CHECK (review_status IN ('pending','approved','rejected','suspended')),
       application_id TEXT UNIQUE,
       reviewed_by TEXT REFERENCES native_auth_users(id),
       reviewed_at TIMESTAMPTZ,
       created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       CHECK (review_status != 'approved'
              OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
       CHECK (reviewed_by IS NULL OR reviewed_by <> user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS pd_account_profiles (
       user_id TEXT PRIMARY KEY REFERENCES native_auth_users(id) ON DELETE CASCADE,
       display_name TEXT,
       consent_version TEXT,
       consent_recorded_at TIMESTAMPTZ,
       updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       CHECK (display_name IS NULL OR length(display_name) <= 160)
    )""",
    """CREATE OR REPLACE FUNCTION pd_validate_pilot_review_actor()
       RETURNS trigger
       LANGUAGE plpgsql SECURITY DEFINER
       SET search_path=pg_catalog,public
       AS $pd$
       BEGIN
         IF NEW.review_status IN ('approved','rejected','suspended') THEN
           IF NEW.reviewed_by IS NULL OR NEW.reviewed_at IS NULL
              OR NEW.reviewed_by = NEW.user_id
              OR NOT EXISTS (
                 SELECT 1 FROM native_auth_roles r
                 WHERE r.user_id=NEW.reviewed_by AND r.role='admin'
              ) THEN
              RAISE EXCEPTION 'pilot_review_requires_admin'
                USING ERRCODE='42501';
           END IF;
         END IF;
         RETURN NEW;
       END
       $pd$""",
    """CREATE OR REPLACE TRIGGER pd_pilot_reviews_admin_gate
       BEFORE INSERT OR UPDATE ON pd_pilot_reviews
       FOR EACH ROW EXECUTE FUNCTION pd_validate_pilot_review_actor()""",
    "CREATE INDEX IF NOT EXISTS pd_pilot_reviews_status ON pd_pilot_reviews(review_status, created_at DESC)",
)
PILOT_LABELS = {"pending": "На проверке", "approved": "Одобрен",
                "rejected": "Отклонён", "suspended": "Приостановлен"}


def validate_telegram_subject(subject):
    """Subject must come from verified OIDC, never client-supplied untrusted data."""
    if not isinstance(subject, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", subject):
        raise ValueError("Invalid Telegram subject")
    return subject


def install_schema(conn):
    """Explicit privileged migration, not called automatically on any web request."""
    with conn.cursor() as cur:
        for statement in SCHEMA:
            cur.execute(statement)


def safe_dispatcher_registry_sql():
    """Read-only summary for an authorized dispatcher, without documents or tokens."""
    return """SELECT u.id, COALESCE(r.role,'passenger') AS role,
         p.display_name, u.destination AS verified_phone,
         (t.telegram_subject IS NOT NULL) AS telegram_linked,
         pr.review_status AS pilot_review_status
      FROM native_auth_users u
      LEFT JOIN native_auth_roles r ON r.user_id=u.id
      LEFT JOIN pd_account_profiles p ON p.user_id=u.id
      LEFT JOIN pd_account_telegram_links t ON t.user_id=u.id
      LEFT JOIN pd_pilot_reviews pr ON pr.user_id=u.id
      WHERE u.channel='phone'
      ORDER BY u.created_at DESC LIMIT 100"""
