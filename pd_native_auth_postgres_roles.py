"""Offline-only owner provisioning for isolated PostgreSQL native auth.

Never expose these functions through WSGI or client APIs. Provision only after
manual verification of the existing native_auth_users.id. No owner by default.
"""
import hashlib
import hmac
import time


def bootstrap_owner_postgres(conn, user_id, *, supplied_secret, configured_secret, now=None):
    if not isinstance(configured_secret, str) or len(configured_secret) < 32:
        raise ValueError("Strong bootstrap secret required")
    if not isinstance(supplied_secret, str) or not hmac.compare_digest(
            hashlib.sha256(supplied_secret.encode()).digest(),
            hashlib.sha256(configured_secret.encode()).digest()):
        raise PermissionError("Invalid bootstrap credentials")
    now = int(time.time() if now is None else now)
    with conn.cursor() as cur:
        # Prevent concurrent initial provisioning from racing.
        cur.execute("SELECT pg_advisory_xact_lock(773144900)")
        cur.execute("SELECT 1 FROM native_auth_users WHERE id=%s", (user_id,))
        if not cur.fetchone():
            raise ValueError("Verified user_id not found")
        cur.execute("""SELECT 1 FROM native_auth_users u
            JOIN native_auth_sessions s ON s.user_id=u.id
            WHERE u.id=%s AND u.channel='phone'
              AND s.revoked_at IS NULL
              AND s.created_at<=%s AND s.created_at>%s
              AND s.expires_at>%s LIMIT 1""",
            (user_id, now, now - 600, now))
        if not cur.fetchone():
            raise PermissionError("Recent verified native phone session required")
        cur.execute("SELECT 1 FROM native_auth_roles WHERE role='admin'")
        if cur.fetchone():
            raise PermissionError("Owner already exists")
        cur.execute("SELECT role FROM native_auth_roles WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        if row and row[0] != "passenger":
            raise PermissionError("Owner must be a passenger before provisioning")
        cur.execute("""INSERT INTO native_auth_roles(user_id,role)
            VALUES (%s,'admin')
            ON CONFLICT(user_id) DO UPDATE SET role='admin'""", (user_id,))
    # Caller commits. No HTTP interface, user assignment or SMS side effects.


def authorize_postgres(conn, access_token, *, required_role="admin", now=None):
    import time
    if required_role not in ("passenger", "pilot", "admin"):
        raise ValueError("Unknown role")
    if not isinstance(access_token, str) or not 40 <= len(access_token) <= 256:
        return None
    now = int(time.time() if now is None else now)
    digest = hashlib.sha256(access_token.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute("""SELECT u.id, COALESCE(r.role, 'passenger')
            FROM native_auth_sessions s
            JOIN native_auth_users u ON u.id=s.user_id
            LEFT JOIN native_auth_roles r ON r.user_id=u.id
            WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>%s""",
            (digest, now))
        row = cur.fetchone()
    return row[0] if row and row[1] == required_role else None
