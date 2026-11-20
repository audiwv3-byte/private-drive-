"""Server-owned roles for the isolated PRIVATE DRIVE native authentication API.

No HTTP endpoint grants roles. Bootstrap is a privileged *offline* operation,
requiring the established user's server-issued ID and a deployment secret.
No administrator is installed by default. This module does not change the
existing Telegram Mini App identity/authorization system.
"""
import hashlib
import hmac
import sqlite3

ROLES = frozenset(("passenger", "pilot", "admin"))


def create_role_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS native_auth_roles (
        user_id TEXT PRIMARY KEY REFERENCES native_auth_users(id),
        role TEXT NOT NULL CHECK(role IN ('passenger','pilot','admin'))
    )""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS native_auth_one_admin
        ON native_auth_roles(role) WHERE role='admin'""")


def get_role(conn, user_id):
    """Fail closed for unknown users; never use a phone supplied by a client."""
    if not isinstance(user_id, str) or not user_id:
        return None
    create_role_schema(conn)
    row = conn.execute("""SELECT u.id, COALESCE(r.role,'passenger')
        FROM native_auth_users u LEFT JOIN native_auth_roles r ON r.user_id=u.id
        WHERE u.id=?""", (user_id,)).fetchone()
    return row[1] if row else None


def bootstrap_owner(conn, user_id, *, supplied_secret, configured_secret):
    """Run only from trusted offline maintenance, NEVER from an HTTP handler.

    The configured secret is supplied securely by the operator at deployment.
    This method cannot select a user by phone and cannot create an account.
    Owner creation is one-time: if another admin exists, it refuses.
    Caller must commit the transaction; failures leave no elevated roles.
    """
    if not isinstance(configured_secret, str) or len(configured_secret) < 32:
        raise ValueError("A strong, deployment-only bootstrap secret is required")
    if not isinstance(supplied_secret, str) or not hmac.compare_digest(
            hashlib.sha256(supplied_secret.encode()).digest(),
            hashlib.sha256(configured_secret.encode()).digest()):
        raise PermissionError("Invalid bootstrap credentials")
    if get_role(conn, user_id) is None:
        raise ValueError("The owner must have an existing verified account")
    if conn.execute("SELECT 1 FROM native_auth_roles WHERE role='admin'").fetchone():
        raise PermissionError("An administrator has already been provisioned")
    if get_role(conn, user_id) != "passenger":
        raise PermissionError("Owner must be a normal verified account")
    try:
        conn.execute("INSERT INTO native_auth_roles(user_id,role) VALUES (?, 'admin') "
                     "ON CONFLICT(user_id) DO UPDATE SET role='admin'",
                     (user_id,))
    except sqlite3.IntegrityError as exc:
        raise PermissionError("Administrator already exists") from exc


def authorize(conn, access_token, *, required_role, now=None):
    """Re-check the DB on every request, not the role cached by the mobile app."""
    if required_role not in ROLES:
        raise ValueError("Unknown required role")
    from pd_native_auth_sessions import authenticate_session
    session = authenticate_session(conn, access_token, now=now)
    if session is None:
        return None
    actual = get_role(conn, session["user_id"])
    if actual != required_role:
        return None
    return session


def assign_pilot(conn, user_id, *, administrator_token, now=None):
    """Trusted staff operation; passenger-originated requests cannot grant roles."""
    if authorize(conn, administrator_token, required_role="admin", now=now) is None:
        raise PermissionError("Administrator authentication required")
    if get_role(conn, user_id) is None:
        raise ValueError("Unknown verified account")
    if get_role(conn, user_id) == "admin":
        raise PermissionError("Cannot replace owner role")
    conn.execute("""INSERT INTO native_auth_roles(user_id,role) VALUES (?,'pilot')
        ON CONFLICT(user_id) DO UPDATE SET role='pilot'""", (user_id,))
