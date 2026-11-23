"""Server-only PostgreSQL native-session verification and per-token logout.

This never accepts a client-asserted role or user ID and has no HTTP route.
Tokens are stored as SHA-256 digests. Callers own transaction/commit.
"""
import hashlib
import time


def _digest(token):
    if not isinstance(token, str) or not 40 <= len(token) <= 256:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def inspect_session(conn, token, *, now=None):
    """Return (user_id, server_role) for an active token; else None."""
    digest = _digest(token)
    if digest is None:
        return None
    now = int(time.time() if now is None else now)
    with conn.cursor() as cur:
        cur.execute("""SELECT s.user_id,COALESCE(r.role,'passenger')
            FROM native_auth_sessions s
            JOIN native_auth_users u ON u.id=s.user_id
            LEFT JOIN native_auth_roles r ON r.user_id=u.id
            WHERE s.token_hash=%s AND s.revoked_at IS NULL
              AND s.created_at<=%s AND s.expires_at>%s""",
            (digest,now,now))
        return cur.fetchone()


def revoke_current_session(conn, token, *, now=None):
    """Revoke ONLY the presented active token; preserve all sibling sessions."""
    digest = _digest(token)
    if digest is None:
        return False
    now = int(time.time() if now is None else now)
    with conn.cursor() as cur:
        cur.execute("""UPDATE native_auth_sessions SET revoked_at=%s
             WHERE token_hash=%s AND revoked_at IS NULL
               AND created_at<=%s AND expires_at>%s
             RETURNING user_id""",
            (now,digest,now,now))
        return cur.fetchone() is not None
