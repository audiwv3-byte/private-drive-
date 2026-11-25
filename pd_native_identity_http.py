"""Manual photo review for the isolated native-auth service only.

No face matching, role grants, SMS or production imports. Photos are private
PostgreSQL bytea values; authorization is rechecked for every request.
"""
import base64
import binascii
import hashlib
import io
import json
import secrets
import threading
import time
import warnings

import psycopg
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO = 2 * 1024 * 1024
MAX_BODY = 2800000
PENDING_TTL = 72 * 3600
APPROVAL_TTL = 7 * 86400
PILOTS = {"pilot", "pilot_dispatcher", "admin"}
REVIEWERS = {"dispatcher", "pilot_dispatcher", "admin"}


def sanitize_photo(encoded):
    if not isinstance(encoded, str) or len(encoded) > MAX_BODY:
        raise ValueError("invalid_photo")
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > MAX_PHOTO:
        raise ValueError("invalid_photo")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("invalid_photo")
            if source.width * source.height > 16000000 or min(source.size) < 32:
                raise ValueError("invalid_photo")
            clean = ImageOps.exif_transpose(source).convert("RGB")
            clean.thumbnail((1280, 1280))
            output = io.BytesIO()
            # Re-encoding without metadata removes EXIF/GPS and ancillary data.
            clean.save(output, format="JPEG", quality=85)
            return output.getvalue()


def initialize_identity(database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS native_identity_checks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES native_auth_users(id),
            status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')),
            photo BYTEA, created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
            reviewer_id TEXT REFERENCES native_auth_users(id), decided_at BIGINT
        )""")
        conn.execute("""CREATE INDEX IF NOT EXISTS native_identity_user_created
            ON native_identity_checks(user_id, created_at DESC)""")


def purge_expired(database_url, now):
    with psycopg.connect(database_url) as conn:
        conn.execute("""UPDATE native_identity_checks SET photo=NULL,
            status=CASE WHEN status='pending' THEN 'expired' ELSE status END
            WHERE photo IS NOT NULL AND expires_at<=%s""", (now,))


def make_identity_app(next_app, database_url, *, clock=time.time, start_cleanup=True,
                      sms_enabled=False, telegram_enabled=False, session_resume_enabled=False):
    initialize_identity(database_url)

    if start_cleanup:
        def cleanup():
            while True:
                try:
                    purge_expired(database_url, int(clock()))
                except psycopg.Error:
                    pass  # Do not put connection strings, tokens or photo data in logs.
                time.sleep(60)
        threading.Thread(target=cleanup, daemon=True, name="identity-photo-cleanup").start()

    def reply(start_response, status, data):
        body = json.dumps(data, separators=(",", ":")).encode()
        start_response(status, [("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff")])
        return [body]

    def app(environ, start_response):
        route = environ.get("PATH_INFO", "")
        if route == "/health" and environ.get("REQUEST_METHOD") == "GET":
            return reply(start_response, "200 OK", {"status": "ok", "sms_enabled": sms_enabled,
                "telegram_enabled": telegram_enabled,
                "session_resume_enabled": session_resume_enabled,
                "identity_enabled": True, "identity_revision": "photo-review-v1"})
        if not route.startswith("/native-identity/"):
            return next_app(environ, start_response)
        method = environ.get("REQUEST_METHOD", "")
        endpoint = route.removeprefix("/native-identity/")
        now = int(clock())
        auth = environ.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith("Bearer ") or not 40 <= len(auth[7:]) <= 256:
            return reply(start_response, "401 Unauthorized", {"error": "invalid_session"})
        digest = hashlib.sha256(auth[7:].encode()).hexdigest()
        try:
            purge_expired(database_url, now)
            with psycopg.connect(database_url) as conn:
                row = conn.execute("""SELECT s.user_id,COALESCE(r.role,'passenger')
                    FROM native_auth_sessions s LEFT JOIN native_auth_roles r ON r.user_id=s.user_id
                    WHERE s.token_hash=%s AND s.expires_at>%s AND s.revoked_at IS NULL""",
                    (digest, now)).fetchone()
                if not row:
                    return reply(start_response, "401 Unauthorized", {"error": "invalid_session"})
                uid, role = row
                if (endpoint in {"status", "submit"} and role not in PILOTS) or (
                        endpoint not in {"status", "submit"} and role not in REVIEWERS):
                    return reply(start_response, "403 Forbidden", {"error": "role_required"})
                if endpoint == "status" and method == "GET":
                    row = conn.execute("""SELECT id,status,decided_at FROM native_identity_checks
                        WHERE user_id=%s ORDER BY created_at DESC,id DESC LIMIT 1""", (uid,)).fetchone()
                    status = row[1] if row else "unverified"
                    if row and status == "approved" and now >= row[2] + APPROVAL_TTL:
                        status = "expired"
                    return reply(start_response, "200 OK", {"status": status})
                if endpoint == "queue" and method == "GET":
                    rows = conn.execute("""SELECT id,user_id FROM native_identity_checks
                        WHERE status='pending' AND expires_at>%s AND user_id<>%s
                        ORDER BY created_at LIMIT 50""", (now, uid)).fetchall()
                    return reply(start_response, "200 OK", {"items": [
                        {"id": r[0], "user_id": r[1]} for r in rows]})
                if endpoint.startswith("photo/") and method == "GET":
                    row = conn.execute("""SELECT photo FROM native_identity_checks
                        WHERE id=%s AND user_id<>%s AND status='pending' AND expires_at>%s""",
                        (endpoint[6:], uid, now)).fetchone()
                    if not row or row[0] is None:
                        return reply(start_response, "404 Not Found", {"error": "not_found"})
                    return reply(start_response, "200 OK", {"photo": base64.b64encode(row[0]).decode()})
                if method != "POST" or not (endpoint == "submit" or endpoint.startswith("decision/")):
                    return reply(start_response, "404 Not Found", {"error": "not_found"})
                try:
                    length = int(environ.get("CONTENT_LENGTH", "0"))
                    limit = MAX_BODY if endpoint == "submit" else 1024
                    if not 0 < length <= limit or not environ.get("CONTENT_TYPE", "").startswith("application/json"):
                        raise ValueError("invalid_request")
                    payload = json.loads(environ["wsgi.input"].read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("invalid_request")
                except (ValueError, TypeError, KeyError, UnicodeError):
                    return reply(start_response, "400 Bad Request", {"error": "invalid_request"})
                if endpoint == "submit":
                    # Lock per account: retries and concurrent requests cannot create a queue flood.
                    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (uid,))
                    existing = conn.execute("""SELECT id,created_at FROM native_identity_checks
                        WHERE user_id=%s AND status='pending' AND expires_at>%s
                        ORDER BY created_at DESC LIMIT 1""", (uid, now)).fetchone()
                    if existing:
                        return reply(start_response, "200 OK", {"id": existing[0], "status": "pending"})
                    recent = conn.execute("SELECT MAX(created_at) FROM native_identity_checks WHERE user_id=%s", (uid,)).fetchone()[0]
                    if recent is not None and now - recent < 60:
                        return reply(start_response, "429 Too Many Requests", {"error": "try_later"})
                    try:
                        photo = sanitize_photo(payload.get("photo"))
                    except (ValueError, TypeError, binascii.Error, UnidentifiedImageError,
                            OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                        return reply(start_response, "400 Bad Request", {"error": "invalid_photo"})
                    check_id = secrets.token_urlsafe(24)
                    conn.execute("""INSERT INTO native_identity_checks
                        (id,user_id,status,photo,created_at,expires_at) VALUES (%s,%s,'pending',%s,%s,%s)""",
                        (check_id, uid, photo, now, now + PENDING_TTL))
                    return reply(start_response, "202 Accepted", {"id": check_id, "status": "pending"})
                decision = payload.get("decision")
                if not isinstance(decision, str) or decision not in {"approved", "rejected"}:
                    return reply(start_response, "400 Bad Request", {"error": "invalid_decision"})
                updated = conn.execute("""UPDATE native_identity_checks SET status=%s,
                    photo=NULL,reviewer_id=%s,decided_at=%s
                    WHERE id=%s AND user_id<>%s AND status='pending' AND expires_at>%s
                    RETURNING id""", (decision, uid, now, endpoint[9:], uid, now)).fetchone()
                if not updated:
                    return reply(start_response, "409 Conflict", {"error": "not_pending"})
                return reply(start_response, "200 OK", {"status": decision})
        except psycopg.Error:
            return reply(start_response, "503 Service Unavailable", {"error": "database_unavailable"})
    return app
