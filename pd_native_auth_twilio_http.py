"""Opt-in Twilio Verify WSGI adapter for isolated PRIVATE DRIVE SMS sign-in.

No production mounts, no payments, no privileged roles.  This module only
receives a verified phone and issues the existing passenger session.  The
Twilio adapter refuses network requests unless TWILIO_VERIFY_ENABLED=true
and valid server-side Twilio credentials are present.  Do not use an
in-memory SQLite connection when multiple WSGI workers are running.
"""
import io
import json
import secrets
import sqlite3
import time

from pd_native_auth import normalize_destination
from pd_native_auth_sessions import issue_session
from pd_twilio_verify import start_verification, check_verification, VerifyError

MAX_BODY = 2048
CHALLENGE_TTL = 300
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS native_twilio_challenges (
        id TEXT PRIMARY KEY,
        phone TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed_at INTEGER
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS native_twilio_phone ON native_twilio_challenges(phone, expires_at)")


def make_twilio_native_auth_app(conn, *, start_sms=start_verification,
                                check_sms=check_verification, clock=None):
    """Construct a *separate*, explicitly mounted test WSGI app.

    Tests inject fake provider functions. By default, provider functions
    independently require Twilio opt-in and credentials; never send on import.
    """
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("SQLite connection required")
    if not callable(start_sms) or not callable(check_sms):
        raise TypeError("SMS provider callbacks required")
    clock = clock or time.time
    _schema(conn)
    conn.commit()
    ip_requests = {}

    def reply(start_response, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        start_response(status, [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ])
        return [body]

    def app(environ, start_response):
        route = environ.get("PATH_INFO", "")
        if environ.get("REQUEST_METHOD") != "POST" or route not in (
                "/native-auth/request-code", "/native-auth/verify-code"):
            return reply(start_response, "404 Not Found", {"error": "not_found"})
        try:
            size = int(environ.get("CONTENT_LENGTH") or "0")
            if size < 1 or size > MAX_BODY or not environ.get(
                    "CONTENT_TYPE", "").lower().startswith("application/json"):
                raise ValueError("invalid body")
            data = json.loads(environ["wsgi.input"].read(size).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("invalid JSON object")
        except (KeyError, ValueError, TypeError, UnicodeError):
            return reply(start_response, "400 Bad Request", {"error": "invalid_request"})

        now = int(clock())
        if route.endswith("/request-code"):
            if data.get("channel") != "phone":
                return reply(start_response, "400 Bad Request", {"error": "phone_only"})
            try:
                phone = normalize_destination("phone", data["destination"])
            except (KeyError, ValueError, TypeError):
                return reply(start_response, "400 Bad Request", {"error": "invalid_phone"})
            # IP throttle is supplemental. Persisted per-phone cooldown protects
            # against server restarts and basic IP rotation.
            ip = environ.get("REMOTE_ADDR", "unknown")
            recent = [x for x in ip_requests.get(ip, []) if x > now - 60]
            if len(recent) >= 4:
                return reply(start_response, "429 Too Many Requests", {"error": "rate_limited"})
            ip_requests[ip] = recent + [now]
            latest = conn.execute(
                "SELECT expires_at FROM native_twilio_challenges WHERE phone=? "
                "ORDER BY rowid DESC LIMIT 1", (phone,)).fetchone()
            if latest and latest[0] > now + CHALLENGE_TTL - RESEND_SECONDS:
                return reply(start_response, "429 Too Many Requests", {"error": "try_later"})
            try:
                start_sms(phone)
            except (VerifyError, ValueError):
                return reply(start_response, "503 Service Unavailable", {"error": "sms_unavailable"})
            # One-time random opaque handle; no SMS code is held or logged.
            challenge_id = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO native_twilio_challenges(id, phone, expires_at) VALUES (?,?,?)",
                (challenge_id, phone, now + CHALLENGE_TTL))
            conn.commit()
            return reply(start_response, "202 Accepted", {
                "challenge_id": challenge_id,
                "expires_in": CHALLENGE_TTL,
                "resend_after": RESEND_SECONDS,
            })

        challenge_id = data.get("challenge_id")
        code = data.get("code")
        if not isinstance(challenge_id, str) or len(challenge_id) > 128 or not (
                isinstance(code, str) and code.isascii()
                and code.isdigit() and 4 <= len(code) <= 10):
            return reply(start_response, "400 Bad Request", {"error": "invalid_request"})
        row = conn.execute(
            "SELECT phone, expires_at, attempts, consumed_at "
            "FROM native_twilio_challenges WHERE id=?", (challenge_id,)
        ).fetchone()
        if not row or row[1] <= now or row[2] >= MAX_ATTEMPTS or row[3] is not None:
            return reply(start_response, "401 Unauthorized", {"error": "invalid_or_expired_code"})
        phone = row[0]
        conn.execute(
            "UPDATE native_twilio_challenges SET attempts=attempts+1 WHERE id=?",
            (challenge_id,))
        conn.commit()
        try:
            approved = check_sms(phone, code)
        except (VerifyError, ValueError):
            return reply(start_response, "503 Service Unavailable", {"error": "sms_unavailable"})
        if not approved:
            return reply(start_response, "401 Unauthorized", {"error": "invalid_or_expired_code"})
        try:
            conn.execute(
                "UPDATE native_twilio_challenges SET consumed_at=? "
                "WHERE id=? AND consumed_at IS NULL", (now, challenge_id))
            session = issue_session(conn, "phone", phone, now=now)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            return reply(start_response, "500 Internal Server Error",
                         {"error": "session_unavailable"})
        # Existing privileged users are not modified or enumerated.
        return reply(start_response, "200 OK", {
            "verified": True, "role": "passenger", **session
        })

    return app
