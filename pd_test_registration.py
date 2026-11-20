"""PRIVATE DRIVE isolated registration harness. Never mount in production.

Explicit factory only: no listening socket, deployment, SMS/email or production DB.
Use an in-memory SQLite database and an injected test-only code sink.
Pilot enrollment remains pending and provides no pilot permission.
"""
import io
import json
import secrets
import sqlite3

from pd_native_auth_http import make_native_auth_app

MAX_BODY = 2048
LOOPBACK = frozenset(("127.0.0.1", "::1"))


def make_test_registration_app(*, clock=None):
    """Return (WSGI app, test inbox). Never expose the inbox over HTTP."""
    db = sqlite3.connect(":memory:")
    inbox = {}
    challenge_roles = {}
    # A unique, runtime-only secret; no credentials in source or configuration.
    secret = secrets.token_bytes(48)

    def capture(channel, destination, code):
        inbox[(channel, destination)] = code

    native_app = make_native_auth_app(db, secret, capture, clock=clock)

    def reply(start_response, status, payload):
        data = json.dumps(payload).encode("utf-8")
        start_response(status, [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ])
        return [data]

    def application(environ, start_response):
        if environ.get("REMOTE_ADDR") not in LOOPBACK:
            return reply(start_response, "403 Forbidden", {"error": "local_only"})
        route = environ.get("PATH_INFO", "")
        if route not in ("/test-registration/request-code", "/test-registration/verify-code"):
            return reply(start_response, "404 Not Found", {"error": "not_found"})
        if environ.get("REQUEST_METHOD") != "POST":
            return reply(start_response, "405 Method Not Allowed", {"error": "method_not_allowed"})
        try:
            size = int(environ.get("CONTENT_LENGTH") or "-1")
            if not 0 < size <= MAX_BODY or not environ.get("CONTENT_TYPE", "").lower().startswith("application/json"):
                raise ValueError()
            raw = environ["wsgi.input"].read(size)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError):
            return reply(start_response, "400 Bad Request", {"error": "invalid_json"})

        request_code = route.endswith("request-code")
        if request_code and data.get("role") not in ("passenger", "pilot"):
            return reply(start_response, "400 Bad Request", {"error": "invalid_role"})
        if not request_code and (not isinstance(data.get("challenge_id"), str) or data.get("challenge_id") not in challenge_roles):
            return reply(start_response, "401 Unauthorized", {"error": "unknown_challenge"})
        native_path = "/native-auth/request-code" if request_code else "/native-auth/verify-code"
        native_environ = dict(environ, PATH_INFO=native_path, CONTENT_LENGTH=str(len(raw)), **{"wsgi.input": io.BytesIO(raw)})
        status_holder = []
        response_headers = []
        def start(status, headers):
            status_holder.append(status)
            response_headers.extend(headers)
        response_bytes = b"".join(native_app(native_environ, start))
        result = json.loads(response_bytes)
        status = status_holder[0]
        if request_code:
            if status.startswith("202"):
                challenge_roles[result["challenge_id"]] = data["role"]
        else:
            role = challenge_roles[data["challenge_id"]]
            if status.startswith("200"):
                # Role is server-bound to the challenge, never taken from verify payload.
                challenge_roles.pop(data["challenge_id"], None)
                result["role"] = role
                result["approval_status"] = "pending" if role == "pilot" else "not_required"
                result["pilot_access"] = False
        return reply(start_response, status, result)

    return application, inbox
