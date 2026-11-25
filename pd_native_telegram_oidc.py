"""Telegram authorization code exchange for the isolated mobile auth service."""

import base64
import hashlib
import hmac
import json
import re
import secrets
from html import escape
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt
import psycopg

from pd_native_auth import normalize_destination

ISSUER = "https://oauth.telegram.org"
PREFIX = "/native-auth/telegram/"
TTL = 300
MAX_ATTEMPTS = 5
TICKET = re.compile(r"[A-Za-z0-9_-]{43}")
HANDOFF_TEXT = {
    "RU": ("Код входа: {code}. Введи его в приложении Private Drive.",
           "Вход не завершён. Вернись в приложение и повтори, разрешив передачу номера."),
    "EN": ("Sign-in code: {code}. Enter it in the Private Drive app.",
           "Sign-in was not completed. Return to the app and allow access to your phone number."),
    "LT": ("Prisijungimo kodas: {code}. Įvesk jį „Private Drive“ programėlėje.",
           "Prisijungimas nebaigtas. Grįžk į programėlę ir leisk perduoti telefono numerį."),
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TelegramOidc:
    def __init__(self, client_id, client_secret, callback_url):
        callback = urlsplit(callback_url)
        if (not client_id.isdecimal() or not client_secret
                or callback.scheme != "https" or not callback.hostname
                or callback.username is not None or callback.query or callback.fragment
                or callback.path != PREFIX + "callback"):
            raise ValueError("Invalid Telegram OIDC configuration")
        self.client_id = client_id
        self.client_secret = client_secret
        self.callback_url = callback_url
        self.opener = build_opener(NoRedirect())
        self.keys = jwt.PyJWKClient(ISSUER + "/.well-known/jwks.json", timeout=6)

    def authorization_url(self, state, verifier):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        return ISSUER + "/auth?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.callback_url,
            "response_type": "code",
            "scope": "openid phone",
            "state": state,
            "code_challenge": challenge.decode().rstrip("="),
            "code_challenge_method": "S256",
        })

    def verified_identity(self, code, verifier):
        basic = base64.b64encode(
            (self.client_id + ":" + self.client_secret).encode()
        ).decode()
        request = Request(ISSUER + "/token", data=urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.callback_url,
            "code_verifier": verifier,
        }).encode(), headers={
            "Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        })
        with self.opener.open(request, timeout=8) as response:
            raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError("Oversized token response")
        payload = json.loads(raw)
        token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(token, str):
            raise ValueError("Missing identity token")
        claims = jwt.decode(
            token, self.keys.get_signing_key_from_jwt(token).key,
            algorithms=["RS256", "ES256", "EdDSA", "ES256K"],
            audience=self.client_id, issuer=ISSUER,
            options={"require": ["iss", "aud", "sub", "iat", "exp"]},
        )
        return verified_phone_claim(claims)

    def handoff_digest(self, state, code):
        return hmac.new(self.client_secret.encode(),
                        (state + ":" + code).encode(), hashlib.sha256).hexdigest()


def verified_phone_claim(claims):
    subject = claims.get("sub")
    number = claims.get("phone_number")
    # Telegram documents its signed phone scope as verified. Reject an
    # explicit negative claim even when the provider included a number.
    if (not isinstance(subject, str) or not 1 <= len(subject) <= 255
            or not isinstance(number, str)
            or claims.get("phone_number_verified", True) is not True):
        raise ValueError("Verified Telegram phone unavailable")
    phone = normalize_destination("phone", "+" + number.removeprefix("+"))
    return subject, phone


def initialize_telegram(database_url):
    with psycopg.connect(database_url) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS native_telegram_attempts (
            state TEXT PRIMARY KEY, app_hash TEXT NOT NULL, verifier TEXT,
            expires_at BIGINT NOT NULL, subject TEXT, phone TEXT,
            handoff_hash TEXT, finish_attempts INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute("""CREATE INDEX IF NOT EXISTS native_telegram_attempt_expiry
            ON native_telegram_attempts (expires_at)""")
        conn.execute("""ALTER TABLE native_telegram_attempts
            ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'RU'""")
        conn.execute("""CREATE TABLE IF NOT EXISTS native_telegram_links (
            subject TEXT PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE REFERENCES native_auth_users(id)
        )""")


def _browser_reply(start_response, status, heading, language):
    body = (
        f'<!doctype html><html lang="{language.lower()}"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>PRIVATE DRIVE</title><h1>PRIVATE DRIVE</h1><p>'
        + escape(heading) + "</p></html>"
    ).encode()
    start_response(status, [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Content-Type-Options", "nosniff"),
        ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
    ])
    return [body]


def make_telegram_routes(database_url, oidc, *, reply, read_json, clock,
                         get_phone_account, issue_session):
    initialize_telegram(database_url)

    def callback(environ, start_response, now):
        language = "RU"
        try:
            fields = parse_qs(environ.get("QUERY_STRING", ""), max_num_fields=12)
            state, code = fields["state"], fields["code"]
            if (len(state) != 1 or not TICKET.fullmatch(state[0])
                    or len(code) != 1 or not 1 <= len(code[0]) <= 2048):
                raise ValueError("Invalid authorization response")
            state, code = state[0], code[0]
            with psycopg.connect(database_url) as conn:
                attempt = conn.execute("""SELECT verifier,language FROM native_telegram_attempts
                    WHERE state=%s AND expires_at>%s FOR UPDATE""",
                    (state, now)).fetchone()
                if attempt and attempt[1] in HANDOFF_TEXT:
                    language = attempt[1]
                if not attempt or not attempt[0]:
                    raise ValueError("Authorization already used or expired")
                conn.execute("UPDATE native_telegram_attempts SET verifier=NULL WHERE state=%s",
                             (state,))
            subject, phone = oidc.verified_identity(code, attempt[0])
            handoff = f"{secrets.randbelow(100_000_000):08d}"
            with psycopg.connect(database_url) as conn:
                result = conn.execute("""UPDATE native_telegram_attempts
                    SET subject=%s, phone=%s, handoff_hash=%s
                    WHERE state=%s AND expires_at>%s""",
                    (subject, phone, oidc.handoff_digest(state, handoff), state, int(clock())))
                if result.rowcount != 1:
                    raise ValueError("Authorization expired")
            return _browser_reply(start_response, "200 OK",
                HANDOFF_TEXT[language][0].format(code=handoff), language)
        except (ValueError, KeyError, URLError, TimeoutError, jwt.PyJWTError):
            return _browser_reply(start_response, "400 Bad Request",
                HANDOFF_TEXT[language][1], language)

    def app(environ, start_response):
        route = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD")
        now = int(clock())
        try:
            if route == PREFIX + "callback" and method == "GET":
                return callback(environ, start_response, now)
            if method != "POST" or route not in (PREFIX + "start", PREFIX + "finish"):
                return reply(start_response, "404 Not Found", {"error": "not_found"})
            try:
                payload = read_json(environ)
                secret = payload.get("app_secret")
                if not isinstance(secret, str) or not TICKET.fullmatch(secret):
                    raise ValueError("Missing app proof")
            except (TypeError, ValueError, KeyError, UnicodeError):
                return reply(start_response, "400 Bad Request", {"error": "invalid_request"})
            if route.endswith("/start"):
                state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                requested_language = payload.get("language")
                language = (requested_language if isinstance(requested_language, str)
                            and requested_language in HANDOFF_TEXT else "RU")
                with psycopg.connect(database_url) as conn:
                    conn.execute("DELETE FROM native_telegram_attempts WHERE expires_at<=%s", (now,))
                    conn.execute("""INSERT INTO native_telegram_attempts
                        (state,app_hash,verifier,expires_at,language) VALUES (%s,%s,%s,%s,%s)""",
                        (state, digest(secret), verifier, now + TTL, language))
                return reply(start_response, "201 Created", {
                    "state": state, "authorization_url": oidc.authorization_url(state, verifier)})
            state, code = payload.get("state"), payload.get("code")
            if (not isinstance(state, str) or not TICKET.fullmatch(state)
                    or not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code)):
                return reply(start_response, "400 Bad Request", {"error": "invalid_request"})
            with psycopg.connect(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT subject,phone,handoff_hash,finish_attempts
                        FROM native_telegram_attempts WHERE state=%s AND app_hash=%s
                        AND expires_at>%s FOR UPDATE""", (state, digest(secret), now))
                    row = cur.fetchone()
                    if not row or not row[2] or row[3] >= MAX_ATTEMPTS:
                        return reply(start_response, "401 Unauthorized", {"error": "telegram_code_invalid"})
                    if not hmac.compare_digest(row[2], oidc.handoff_digest(state, code)):
                        cur.execute("""UPDATE native_telegram_attempts SET finish_attempts=finish_attempts+1
                            WHERE state=%s""", (state,))
                        return reply(start_response, "401 Unauthorized", {"error": "telegram_code_invalid"})
                    cur.execute("DELETE FROM native_telegram_attempts WHERE state=%s", (state,))
                    subject, phone = row[:2]
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                                ("telegram:" + subject,))
                    cur.execute("""SELECT u.destination FROM native_telegram_links l
                        JOIN native_auth_users u ON u.id=l.user_id WHERE l.subject=%s""", (subject,))
                    linked = cur.fetchone()
                    if linked and linked[0] != phone:
                        return reply(start_response, "409 Conflict", {"error": "telegram_link_conflict"})
                    uid = get_phone_account(cur, phone, now)
                    cur.execute("""INSERT INTO native_telegram_links(subject,user_id) VALUES (%s,%s)
                        ON CONFLICT DO NOTHING""", (subject, uid))
                    cur.execute("SELECT user_id FROM native_telegram_links WHERE subject=%s", (subject,))
                    if cur.fetchone() != (uid,):
                        return reply(start_response, "409 Conflict", {"error": "telegram_link_conflict"})
                    session = issue_session(cur, uid, now)
            return reply(start_response, "200 OK", session)
        except psycopg.Error:
            return reply(start_response, "503 Service Unavailable", {"error": "database_unavailable"})
    return app
