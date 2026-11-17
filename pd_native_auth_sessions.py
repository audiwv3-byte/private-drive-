"""Isolated account and opaque session storage for verified native OTP logins.

Only call issue_session after successful one-time OTP verification. Not mounted
on the production server. Tokens are returned once and only SHA-256 hashes
are stored. This module does not send messages or make payments.
"""
import hashlib
import secrets
import sqlite3
import time

from pd_native_auth import normalize_destination

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


def create_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS native_auth_users (
        id TEXT PRIMARY KEY,
        channel TEXT NOT NULL,
        destination TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE(channel, destination)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS native_auth_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        revoked_at INTEGER,
        FOREIGN KEY(user_id) REFERENCES native_auth_users(id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS native_sessions_user ON native_auth_sessions(user_id)")


def issue_session(conn, verified_channel, verified_destination, now=None):
    """Create/reuse account for a previously verified OTP result."""
    target = normalize_destination(verified_channel, verified_destination)
    now = int(time.time() if now is None else now)
    create_schema(conn)
    uid = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT OR IGNORE INTO native_auth_users(id, channel, destination, created_at) VALUES (?, ?, ?, ?)",
        (uid, verified_channel, target, now),
    )
    user_id = conn.execute(
        "SELECT id FROM native_auth_users WHERE channel=? AND destination=?",
        (verified_channel, target),
    ).fetchone()[0]
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = now + SESSION_TTL_SECONDS
    conn.execute(
        "INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at) VALUES (?,?,?,?)",
        (digest, user_id, now, expires_at),
    )
    return {"user_id": user_id, "access_token": token,
            "token_type": "Bearer", "expires_in": SESSION_TTL_SECONDS}


def authenticate_session(conn, token, now=None):
    if not isinstance(token, str) or len(token) > 256 or len(token) < 40:
        return None
    now = int(time.time() if now is None else now)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    create_schema(conn)
    row = conn.execute(
        """SELECT u.id,u.channel,u.destination FROM native_auth_sessions s
           JOIN native_auth_users u ON u.id=s.user_id
           WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?""",
        (digest, now),
    ).fetchone()
    return {"user_id": row[0], "channel": row[1], "destination": row[2]} if row else None


def revoke_session(conn, token, now=None):
    if not isinstance(token, str) or len(token) < 40 or len(token) > 256:
        return False
    now = int(time.time() if now is None else now)
    cursor = conn.execute(
        "UPDATE native_auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
        (now, hashlib.sha256(token.encode("utf-8")).hexdigest()),
    )
    return cursor.rowcount == 1
