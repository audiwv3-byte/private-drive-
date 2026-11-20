"""PostgreSQL-backed, isolated native phone sign-in test WSGI application.

This is NOT mounted in the production PRIVATE DRIVE site. Real messages require
PD_NATIVE_SMS_LIVE=YES and TWILIO_VERIFY_ENABLED=true and provider credentials.
Only hashes of access tokens are persisted; never log database URLs or tokens.
"""
import hashlib
import json
import os
import secrets
import time

import psycopg

from pd_native_auth import normalize_destination
from pd_twilio_verify import VerifyError, start_verification, check_verification

TTL = 300
COOLDOWN = 60
MAX_ATTEMPTS = 5
SESSION_TTL = 30 * 86400
MAX_BODY = 2048


def initialize_database(database_url):
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS native_twilio_challenges (
                id TEXT PRIMARY KEY, phone TEXT NOT NULL,
                created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, consumed_at BIGINT
            )""")
            cur.execute("""CREATE INDEX IF NOT EXISTS native_twilio_phone_created
                ON native_twilio_challenges(phone, created_at DESC)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS native_auth_users (
                id TEXT PRIMARY KEY, channel TEXT NOT NULL,
                destination TEXT NOT NULL, created_at BIGINT NOT NULL,
                UNIQUE(channel, destination)
            )""")
            cur.execute("""CREATE TABLE IF NOT EXISTS native_auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES native_auth_users(id),
                created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
                revoked_at BIGINT
            )""")
            cur.execute("""CREATE INDEX IF NOT EXISTS native_sessions_user
                ON native_auth_sessions(user_id)""")


def make_app(database_url, *, admin_phone=None, live=False,
             start_sms=None, check_sms=None, clock=None):
    if not database_url or not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("A private PostgreSQL DATABASE_URL is required")
    if admin_phone:
        admin_phone = normalize_destination("phone", admin_phone)
    if live:
        if not (start_sms and check_sms):
            start_sms = start_sms or start_verification
            check_sms = check_sms or check_verification
    clock = clock or time.time
    initialize_database(database_url)

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
        method = environ.get("REQUEST_METHOD", "")
        if method == "GET" and route == "/health":
            return reply(start_response, "200 OK", {"status": "ok", "sms_enabled": live})
        if method != "POST" or route not in (
                "/native-auth/request-code", "/native-auth/verify-code"):
            return reply(start_response, "404 Not Found", {"error": "not_found"})
        if not live:
            return reply(start_response, "503 Service Unavailable",
                         {"error": "sms_disabled"})
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            if length < 1 or length > MAX_BODY or not environ.get(
                    "CONTENT_TYPE", "").lower().startswith("application/json"):
                raise ValueError("Invalid request content")
            payload = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Expected object")
        except (TypeError, ValueError, KeyError, UnicodeError):
            return reply(start_response, "400 Bad Request", {"error": "invalid_request"})

        now = int(clock())
        if route.endswith("/request-code"):
            if payload.get("channel") != "phone":
                return reply(start_response, "400 Bad Request", {"error": "phone_only"})
            try:
                phone = normalize_destination("phone", payload["destination"])
            except (KeyError, ValueError, TypeError):
                return reply(start_response, "400 Bad Request", {"error": "invalid_phone"})
            try:
                with psycopg.connect(database_url) as conn:
                    with conn.cursor() as cur:
                        # Lock all requests for a phone across processes, not just one worker.
                        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (phone,))
                        cur.execute("""SELECT created_at FROM native_twilio_challenges
                            WHERE phone=%s ORDER BY created_at DESC LIMIT 1""", (phone,))
                        recent = cur.fetchone()
                        if recent and recent[0] > now - COOLDOWN:
                            return reply(start_response, "429 Too Many Requests",
                                         {"error": "try_later"})
                        try:
                            start_sms(phone, env=os.environ)
                        except (VerifyError, ValueError):
                            return reply(start_response, "503 Service Unavailable",
                                         {"error": "sms_unavailable"})
                        challenge_id = secrets.token_urlsafe(32)
                        cur.execute("""INSERT INTO native_twilio_challenges
                            (id,phone,created_at,expires_at) VALUES (%s,%s,%s,%s)""",
                            (challenge_id, phone, now, now + TTL))
                return reply(start_response, "202 Accepted", {
                    "challenge_id": challenge_id, "expires_in": TTL,
                    "resend_after": COOLDOWN})
            except psycopg.Error:
                return reply(start_response, "503 Service Unavailable",
                             {"error": "database_unavailable"})

        challenge_id, code = payload.get("challenge_id"), payload.get("code")
        if not isinstance(challenge_id, str) or len(challenge_id) > 128 or not (
                isinstance(code, str) and code.isascii()
                and code.isdigit() and 4 <= len(code) <= 10):
            return reply(start_response, "400 Bad Request", {"error": "invalid_request"})
        try:
            with psycopg.connect(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT phone,expires_at,attempts,consumed_at
                        FROM native_twilio_challenges WHERE id=%s FOR UPDATE""",
                        (challenge_id,))
                    row = cur.fetchone()
                    if not row or row[1] <= now or row[2] >= MAX_ATTEMPTS or row[3] is not None:
                        return reply(start_response, "401 Unauthorized",
                                     {"error": "invalid_or_expired_code"})
                    phone = row[0]
                    # Count attempts even when the provider rejects or times out.
                    cur.execute("""UPDATE native_twilio_challenges
                        SET attempts=attempts+1 WHERE id=%s""", (challenge_id,))
                    try:
                        approved = check_sms(phone, code, env=os.environ)
                    except (VerifyError, ValueError):
                        return reply(start_response, "503 Service Unavailable",
                                     {"error": "sms_unavailable"})
                    if not approved:
                        return reply(start_response, "401 Unauthorized",
                                     {"error": "invalid_or_expired_code"})
                    cur.execute("""UPDATE native_twilio_challenges
                        SET consumed_at=%s WHERE id=%s""", (now, challenge_id))
                    uid = secrets.token_urlsafe(24)
                    cur.execute("""INSERT INTO native_auth_users
                        (id,channel,destination,created_at) VALUES (%s,'phone',%s,%s)
                        ON CONFLICT(channel,destination) DO NOTHING""",
                        (uid, phone, now))
                    cur.execute("""SELECT id FROM native_auth_users
                        WHERE channel='phone' AND destination=%s""", (phone,))
                    uid = cur.fetchone()[0]
                    token = secrets.token_urlsafe(48)
                    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                    cur.execute("""INSERT INTO native_auth_sessions
                        (token_hash,user_id,created_at,expires_at)
                        VALUES (%s,%s,%s,%s)""", (digest, uid, now, now + SESSION_TTL))
            role = "admin" if admin_phone and phone == admin_phone else "passenger"
            return reply(start_response, "200 OK", {
                "verified": True, "role": role, "user_id": uid,
                "access_token": token, "token_type": "Bearer",
                "expires_in": SESSION_TTL,
            })
        except psycopg.Error:
            return reply(start_response, "503 Service Unavailable",
                         {"error": "database_unavailable"})

    return app
