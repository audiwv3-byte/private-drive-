"""PRIVATE DRIVE staging-only pilot approval primitive.

This is deliberately NOT an HTTP route. It can be called only after a trusted
server has verified the current administrator's native access token. A
DB-enforced trigger also requires an admin reviewer; no roles are ever changed.
No live SMS, Telegram identity or production deployment.
"""
import hashlib
import time


def approve_pilot(conn, authenticated_admin_token, pilot_user_id, *, now=None):
    """Approve pending pilot with valid server session AND database admin role.

    Returns False without mutating anything for absent/expired/revoked sessions,
    non-admin requesters, self-approval or non-pilots. Caller owns commit.
    """
    if not isinstance(authenticated_admin_token, str) or not 40 <= len(authenticated_admin_token) <= 256:
        return False
    if not isinstance(pilot_user_id, str) or not 1 <= len(pilot_user_id) <= 200:
        return False
    current_time = int(time.time() if now is None else now)
    token_hash = hashlib.sha256(authenticated_admin_token.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        # User identity is derived exclusively from the authenticated session
        # hash, never supplied as a client-selected reviewer or role.
        cur.execute("""WITH actor AS (
            SELECT s.user_id
            FROM native_auth_sessions s
            JOIN native_auth_roles r ON r.user_id=s.user_id
            JOIN native_auth_users u ON u.id=s.user_id
            WHERE s.token_hash=%s AND s.revoked_at IS NULL
              AND s.expires_at>%s AND s.created_at<=%s
              AND r.role='admin' AND u.channel='phone'
            FOR UPDATE OF s
        )
        UPDATE pd_pilot_reviews p
        SET review_status='approved', reviewed_by=actor.user_id,
            reviewed_at=NOW()
        FROM actor
        JOIN native_auth_roles target ON target.user_id=%s
        WHERE p.user_id=%s
          AND p.user_id<>actor.user_id
          AND p.review_status='pending'
          AND target.role='pilot'
        RETURNING p.user_id""",
                    (token_hash,current_time,current_time,pilot_user_id,pilot_user_id))
        return cur.fetchone() is not None
