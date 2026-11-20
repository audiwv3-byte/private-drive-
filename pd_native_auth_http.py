"""Isolated WSGI OTP HTTP API for native app integration testing.

Not mounted on the production application. Inject a private database connection,
strong secret and delivery callback. Never return verification codes over HTTP.
Verification proves destination ownership; it does NOT create a user or session.
"""
import io
import json
import re
import sqlite3
import time
from pd_native_auth import issue_code, verify_code
from pd_native_auth_sessions import issue_session
from pd_native_auth_roles import get_role

MAX_BODY = 2048
MAX_IP_REQUESTS_PER_MINUTE = 4


def make_native_auth_app(conn, secret, deliver, clock=None):
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("SQLite connection required")
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("Strong server secret required")
    if not callable(deliver):
        raise TypeError("Trusted delivery callback required")
    clock = clock or time.time
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
            "/native-auth/request-code", "/native-auth/verify-code"
        ):
            return reply(start_response, "404 Not Found", {"error": "not_found"})
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except (ValueError, TypeError):
            length = -1
        if length < 1 or length > MAX_BODY or not environ.get(
            "CONTENT_TYPE", ""
        ).lower().startswith("application/json"):
            return reply(start_response, "400 Bad Request", {"error": "invalid_request"})
        try:
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Object expected")
        except (ValueError, UnicodeError, KeyError):
            return reply(start_response, "400 Bad Request", {"error": "invalid_json"})

        now = int(clock())
        if route.endswith("/request-code"):
            # This is only a per-process safeguard for an isolated test server.
            # Production requires shared, durable rate limiting and a verified
            # provider before mounting these routes.
            ip = environ.get("REMOTE_ADDR", "unknown")
            recent = [t for t in ip_requests.get(ip, []) if t > now - 60]
            if len(recent) >= MAX_IP_REQUESTS_PER_MINUTE:
                return reply(start_response, "429 Too Many Requests", {"error": "rate_limited"})
            recent.append(now)
            ip_requests[ip] = recent
            try:
                channel = data["channel"]
                destination = data["destination"]
                cid, code = issue_code(conn, secret, channel, destination, now=now)
            except (KeyError, ValueError, TypeError):
                return reply(start_response, "400 Bad Request", {"error": "invalid_or_limited_target"})
            # Transactional delivery is a future integration concern.
            # No real SMS/email provider is connected here.
            deliver(channel, destination.strip(), code)
            conn.commit()
            return reply(start_response, "202 Accepted", {
                "challenge_id": cid, "expires_in": 300, "resend_after": 60
            })

        try:
            challenge_id = data["challenge_id"]
            code = data["code"]
            result = verify_code(conn, secret, challenge_id, code, now=now)
        except (KeyError, TypeError, ValueError):
            result = None
        if result is None:
            conn.commit()
            return reply(start_response, "401 Unauthorized", {"error": "invalid_or_expired_code"})
        channel, destination = result
        # Verified destination is trusted only after the one-time OTP succeeds.
        # Both the consumed challenge and the session must commit together.
        try:
            session = issue_session(conn, channel, destination, now=now)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            return reply(start_response, "500 Internal Server Error", {"error": "session_unavailable"})
        return reply(start_response, "200 OK", {
            "verified": True, "channel": channel, "destination": destination,
            "role": get_role(conn, session["user_id"]), **session
        })

    return app
