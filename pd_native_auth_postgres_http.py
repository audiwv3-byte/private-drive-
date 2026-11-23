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

from pd_native_auth import native_phone_role_resolver, normalize_destination
from pd_twilio_verify import VerifyError, start_verification, check_verification
from pd_native_auth_schema_readiness import SchemaReadinessGate
from pd_native_auth_postgres_session_lifecycle import _digest

TTL = 300
COOLDOWN = 60
MAX_ATTEMPTS = 5
SESSION_TTL = 30 * 86400
MAX_BODY = 2048


def make_app(database_url, *, admin_phone=None, dispatcher_phone=None, pilot_phone=None,
             live=False,
             start_sms=None, check_sms=None, clock=None, readiness_clock=None):
    if not database_url or not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("A private PostgreSQL DATABASE_URL is required")
    role_for_phone = native_phone_role_resolver(
        admin_phone=admin_phone, dispatcher_phone=dispatcher_phone, pilot_phone=pilot_phone)
    if live:
        if not (start_sms and check_sms):
            start_sms = start_sms or start_verification
            check_sms = check_sms or check_verification
    clock = clock or time.time
    # Schema installation is an explicit, separate migration step. No runtime DDL.
    readiness = SchemaReadinessGate(database_url, monotonic=readiness_clock)
    readiness.status()  # initial fail-closed probe; subsequent checks are throttled

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
        schema_ready, schema_status = readiness.status()
        if method == "GET" and route == "/health":
            if not schema_ready:
                return reply(start_response, "503 Service Unavailable",
                             {"status": "not_ready", "error": schema_status,
                              "sms_enabled": False})
            return reply(start_response, "200 OK", {"status": "ok", "sms_enabled": live})
        # Fail closed even with a real SMS provider configured: no SMS or DB
        # write is allowed until an explicit migration created every table.
        if not schema_ready:
            return reply(start_response, "503 Service Unavailable",
                         {"error": schema_status})
        if method == "GET" and route == "/native-auth/session":
            auth = environ.get("HTTP_AUTHORIZATION", "")
            if not isinstance(auth,str) or not auth.startswith("Bearer "):
                return reply(start_response, "401 Unauthorized",
                             {"error":"invalid_session"})
            token = auth[7:]
            digest = _digest(token)
            if digest is None or any(char.isspace() for char in token):
                return reply(start_response, "401 Unauthorized",
                             {"error":"invalid_session"})
            try:
                with psycopg.connect(database_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("""SELECT user_id,server_role,expires_at
                            FROM public.pd_validate_native_session(%s,%s)""",
                            (digest,int(clock())))
                        row = cur.fetchone()
                if not row:
                    return reply(start_response, "401 Unauthorized",
                                 {"error":"invalid_session"})
                return reply(start_response, "200 OK",
                             {"user_id":row[0],"role":row[1],
                              "expires_at":row[2]})
            except psycopg.Error:
                readiness.mark_database_unavailable()
                return reply(start_response, "503 Service Unavailable",
                             {"error":"database_unavailable"})
        if method == "POST" and route == "/native-auth/logout":
            # A per-device logout is independent of whether SMS is enabled.
            # Never accept user_id, token hash or a role in the request body.
            auth = environ.get("HTTP_AUTHORIZATION", "")
            if not isinstance(auth, str) or not auth.startswith("Bearer "):
                return reply(start_response, "401 Unauthorized",
                             {"error": "invalid_session"})
            token = auth[7:]
            digest = _digest(token)
            if digest is None or any(ch.isspace() for ch in token):
                return reply(start_response, "401 Unauthorized",
                             {"error": "invalid_session"})
            try:
                with psycopg.connect(database_url) as conn:
                    with conn.cursor() as cur:
                        # Privileged, narrow PostgreSQL function accepts ONLY
                        # the cryptographic digest of THIS bearer token.
                        cur.execute(
                            "SELECT public.pd_revoke_current_session(%s,%s)",
                            (digest,int(clock())))
                        revoked = cur.fetchone()[0]
                if not revoked:
                    return reply(start_response, "401 Unauthorized",
                                 {"error": "invalid_session"})
                return reply(start_response, "200 OK", {"status":"logged_out"})
            except psycopg.Error:
                readiness.mark_database_unavailable()
                return reply(start_response, "503 Service Unavailable",
                             {"error": "database_unavailable"})
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
                readiness.mark_database_unavailable()
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
                    cur.execute("""SELECT role FROM native_auth_roles WHERE user_id=%s""", (uid,))
                    stored_role = cur.fetchone()
                    stored_role = stored_role[0] if stored_role else "passenger"
                    token = secrets.token_urlsafe(48)
                    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                    cur.execute("""INSERT INTO native_auth_sessions
                        (token_hash,user_id,created_at,expires_at)
                        VALUES (%s,%s,%s,%s)""", (digest, uid, now, now + SESSION_TTL))
            return reply(start_response, "200 OK", {
                "verified": True, "role": stored_role, "user_id": uid,
                "access_token": token, "token_type": "Bearer",
                "expires_in": SESSION_TTL,
            })
        except psycopg.Error:
            readiness.mark_database_unavailable()
            return reply(start_response, "503 Service Unavailable",
                         {"error": "database_unavailable"})

    return app
