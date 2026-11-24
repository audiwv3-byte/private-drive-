"""Closed-pilot no-SMS sign-in. Mount only in the isolated native WSGI."""
import hashlib
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

INVITE_PATH = "/native-auth/redeem-invite"
PILOT_INVITE_PATH = "/native-auth/redeem-pilot-invite"
TEST_DB = "private_drive_test"
INVITE_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_OFF = {"", "0", "false", "no", "off"}


class InviteStorageUnavailable(Exception):
    """An isolated invite store could not be reached; do not log the cause."""


def pilot_enabled(database_url, env):
    if (env.get("PD_NATIVE_CLOSED_PILOT_INVITES") != "1"
            or env.get("PD_NATIVE_SMS_ISOLATED") != "YES"
            or env.get("PD_PAYMENT_MODE") != "disabled"
            or any(env.get(key, "").lower() not in _OFF for key in
                   ("PD_NATIVE_SMS_LIVE", "TWILIO_VERIFY_ENABLED"))):
        return False
    try:
        uri = urlsplit(database_url)
        return (uri.scheme in {"postgres", "postgresql"} and uri.hostname
                and uri.path == "/" + TEST_DB and not uri.query and not uri.fragment)
    except (ValueError, TypeError, AttributeError):
        return False


def _hash(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def pilot_account_invites_enabled(database_url, env):
    return (pilot_enabled(database_url, env)
            and env.get("PD_NATIVE_PILOT_INVITE_ONBOARDING") == "1")


def _exchange_in_db(database_url, invite_digest, session_digest, *, allow_pilot):
    import psycopg
    try:
        with psycopg.connect(database_url, connect_timeout=4,
                             options="-c statement_timeout=4000") as db:
            query = (
                "SELECT user_id,server_role,expires_at FROM public.pd_redeem_closed_pilot_account_invite(%s,%s)"
                if allow_pilot else
                "SELECT user_id,server_role,expires_at FROM public.pd_redeem_closed_pilot_invite(%s,%s)"
            )
            return db.execute(query, (invite_digest, session_digest)).fetchone()
    except psycopg.Error:
        raise InviteStorageUnavailable() from None


def exchange_in_db(database_url, invite_digest, session_digest):
    return _exchange_in_db(database_url, invite_digest, session_digest, allow_pilot=False)


def exchange_pilot_account_in_db(database_url, invite_digest, session_digest):
    return _exchange_in_db(database_url, invite_digest, session_digest, allow_pilot=True)


class _Limiter:
    # Per-process, bounded-memory backstop for this small closed pilot. High
    # entropy is the security boundary; never trust client IP forwarding.
    def __init__(self, clock):
        self.clock = clock
        self.lock = threading.Lock()
        self.last = clock()
        self.tokens = 25.0

    def allow(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(25.0, self.tokens + max(0.0, now - self.last) * 2.0)
            self.last = now
            if self.tokens < 1.0:
                return False
            self.tokens -= 1.0
            return True


def make_closed_invites_app(next_app, database_url, *, environ=None,
                            exchange=exchange_in_db, token=secrets.token_urlsafe,
                            pilot_exchange=exchange_pilot_account_in_db,
                            monotonic=time.monotonic):
    env = os.environ if environ is None else environ
    limiter = _Limiter(monotonic)

    def app(wsgi, start_response):
        path = wsgi.get("PATH_INFO")
        if path == INVITE_PATH and pilot_enabled(database_url, env):
            redeem, expected_role = exchange, "passenger"
        elif path == PILOT_INVITE_PATH and pilot_account_invites_enabled(database_url, env):
            redeem, expected_role = pilot_exchange, "pilot"
        else:
            return next_app(wsgi, start_response)

        def reply(status, data):
            body = json.dumps(data, separators=(",", ":")).encode("utf-8")
            start_response(status, [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ])
            return [body]

        if wsgi.get("REQUEST_METHOD") != "POST":
            return reply("405 Method Not Allowed", {"error": "method_not_allowed"})
        if not limiter.allow():
            return reply("429 Too Many Requests", {"error": "rate_limited"})
        try:
            size = int(wsgi.get("CONTENT_LENGTH", "0"))
            if (not 0 < size <= 256 or wsgi.get("QUERY_STRING")
                    or wsgi.get("CONTENT_TYPE", "").split(";")[0] != "application/json"):
                raise ValueError()
            data = json.loads(wsgi["wsgi.input"].read(size))
            if (not isinstance(data, dict) or set(data) != {"invite_code"}
                    or not isinstance(data["invite_code"], str)
                    or not INVITE_RE.fullmatch(data["invite_code"])):
                raise ValueError()
        except (TypeError, ValueError, KeyError, UnicodeError):
            return reply("400 Bad Request", {"error": "invalid_invite_request"})

        access_token = token(48)
        try:
            row = redeem(database_url, _hash(data["invite_code"]), _hash(access_token))
        except InviteStorageUnavailable:
            return reply("503 Service Unavailable", {"error": "invite_service_unavailable"})
        if not row or row[1] != expected_role:
            return reply("401 Unauthorized", {"error": "invalid_or_expired_invite"})
        return reply("200 OK", {
            "user_id": row[0], "role": row[1], "expires_at": row[2],
            "access_token": access_token, "token_type": "Bearer",
        })

    return app
