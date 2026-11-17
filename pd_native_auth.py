"""Isolated OTP challenge primitives for future native-app authentication.

Not registered as an API route. No SMS/email is sent here; a verified delivery
provider must be integrated before exposing any endpoint.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time

OTP_TTL_SECONDS = 300
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60


def normalize_destination(channel, destination):
    if not isinstance(destination, str):
        raise ValueError("Invalid destination")
    value = destination.strip()
    if channel == "email":
        value = value.lower()
        if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email")
    elif channel == "phone":
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
            raise ValueError("Phone must be E.164")
    else:
        raise ValueError("Unsupported channel")
    return value


def create_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS native_auth_challenges (
        id TEXT PRIMARY KEY,
        channel TEXT NOT NULL,
        destination TEXT NOT NULL,
        code_digest TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        next_send_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed_at INTEGER
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS native_auth_target ON native_auth_challenges(channel, destination, next_send_at)")


def _digest(secret, challenge_id, code):
    return hmac.new(secret, (challenge_id + ":" + code).encode(), hashlib.sha256).hexdigest()


def issue_code(conn, secret, channel, destination, now=None):
    """Return (challenge_id, code) to trusted server-side delivery code only.

    Caller must enforce per-IP/account rate limits before invoking this function.
    """
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("Strong server secret required")
    target = normalize_destination(channel, destination)
    now = int(time.time() if now is None else now)
    create_schema(conn)
    row = conn.execute("""SELECT MAX(next_send_at) FROM native_auth_challenges
                          WHERE channel=? AND destination=?""", (channel, target)).fetchone()
    if row[0] is not None and row[0] > now:
        raise ValueError("Please wait before requesting another code")
    challenge_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(1000000):06d}"
    conn.execute("""INSERT INTO native_auth_challenges
                    (id, channel, destination, code_digest, expires_at, next_send_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 (challenge_id, channel, target, _digest(secret, challenge_id, code),
                  now + OTP_TTL_SECONDS, now + RESEND_SECONDS))
    return challenge_id, code


def verify_code(conn, secret, challenge_id, code, now=None):
    """Return verified (channel, destination) exactly once or None.

    Does not create a user or issue a login token.
    """
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("Strong server secret required")
    if not isinstance(challenge_id, str) or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return None
    now = int(time.time() if now is None else now)
    row = conn.execute("""SELECT channel, destination, code_digest, expires_at,
                                 attempts, consumed_at FROM native_auth_challenges WHERE id=?""",
                       (challenge_id,)).fetchone()
    if row is None or row[5] is not None or row[3] <= now or row[4] >= MAX_ATTEMPTS:
        return None
    valid = hmac.compare_digest(row[2], _digest(secret, challenge_id, code))
    conn.execute("""UPDATE native_auth_challenges
                    SET attempts=attempts+1, consumed_at=CASE WHEN ? THEN ? ELSE consumed_at END
                    WHERE id=? AND consumed_at IS NULL AND attempts<?""",
                 (int(valid), now, challenge_id, MAX_ATTEMPTS))
    if not valid:
        return None
    return row[0], row[1]
