"""Isolated browser dispatcher MVP. Disabled until explicitly configured.

Existing Telegram Mini App endpoints and authentication are unchanged.
"""
import hashlib
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

from flask import redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

AUTH_PAGE = """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PRIVATE DRIVE — {{ title }}</title>
<link rel="stylesheet" href="/assets/pd-black-gold.css">
<style>
*{box-sizing:border-box}
body{background:var(--pd-black,#100e0b);color:var(--pd-ink,#f7efe1);font:16px/1.5 system-ui;margin:0;display:grid;min-height:100vh;place-items:center;padding:16px}
main{width:min(430px,100%);padding:clamp(18px,5vw,28px);background:var(--pd-surface,#1c1711);border:1px solid var(--pd-border,#77592f);border-radius:16px}
h1,h2{color:var(--pd-gold,#edca82)}
input,button{display:block;width:100%;padding:12px;margin:10px 0 16px;border-radius:8px;font:inherit;min-height:46px}
button{background:var(--pd-light,#edca82);color:#21170b;border:0;font-weight:700;cursor:pointer}
input{background:var(--pd-field,#16120d);color:inherit;border:1px solid var(--pd-border,#77592f)}
input:focus-visible,button:focus-visible{outline:2px solid var(--pd-gold-strong,#ffdfa0);outline-offset:3px}
a{color:var(--pd-gold,#edca82)}
small{color:var(--pd-muted,#c7b79e)}
</style>
<main><img src="/pd-logo-transparent.png" alt="PRIVATE DRIVE — логотип PD с автомобилем" width="112" height="112" style="display:block;width:112px;height:112px;max-width:100%;aspect-ratio:1;object-fit:contain;margin:0 auto 14px;border-radius:14px"><h1 style="text-align:center">PRIVATE DRIVE</h1><h2>{{ title }}</h2>
{% if error %}<p role="alert">{{ error }}</p>{% endif %}
{% if registered %}<p role="status">Пароль создан. Теперь войди в диспетчерскую.</p>{% endif %}
{% if ready %}
<form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
{% if registration %}<label for="invite">Код приглашения</label>
<input id="invite" name="invite" required maxlength="128" autocomplete="off" autocapitalize="none" spellcheck="false">
{% endif %}<label for="password">Пароль</label>
<input id="password" type="password" name="password" autocomplete="{{ 'new-password' if registration else 'current-password' }}" required maxlength="{{ 128 if registration else 512 }}" {% if registration %}minlength="12"{% endif %}>
{% if registration %}<label for="confirmation">Повтори пароль</label>
<input id="confirmation" type="password" name="confirmation" autocomplete="new-password" required minlength="12" maxlength="128">
{% endif %}<button>{{ 'Создать пароль' if registration else 'Войти' }}</button></form>
{% endif %}
{% if registration %}<a href="/dispatch/login">Войти в диспетчерскую</a>
{% else %}<a href="/dispatch/register">Регистрация по приглашению</a>{% endif %}
</main></html>"""


class DispatcherPasswords:
    """Store the single dispatcher credential in a dedicated Postgres table."""

    def __init__(self, dsn):
        self.dsn = dsn

    def connect(self):
        import psycopg

        return psycopg.connect(self.dsn, connect_timeout=4,
                               options="-c statement_timeout=4000")

    def read(self, admin_id):
        from psycopg.errors import UndefinedTable

        try:
            with self.connect() as db:
                row = db.execute(
                    "SELECT password_hash FROM private_drive_dispatcher_passwords WHERE admin_id = %s",
                    (admin_id,),
                ).fetchone()
        except UndefinedTable:
            return ""
        return row[0] if row else ""

    def create(self, admin_id, password_hash):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(192784221, 1)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS private_drive_dispatcher_passwords (
                    admin_id bigint PRIMARY KEY,
                    password_hash text NOT NULL
                )
            """)
            result = db.execute("""
                INSERT INTO private_drive_dispatcher_passwords (admin_id, password_hash)
                VALUES (%s, %s)
                ON CONFLICT (admin_id) DO NOTHING
            """, (admin_id, password_hash))
            return result.rowcount == 1


def auth_page(app, registration=False, ready=False, status=200, **context):
    title = "Регистрация диспетчера" if registration else "Вход диспетчера"
    page = render_template_string(AUTH_PAGE, title=title, registration=registration,
                                  ready=ready, **context)
    return app.make_response((page, status, {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; "
                                   "style-src 'self' 'unsafe-inline'; form-action 'self'; "
                                   "base-uri 'none'; frame-ancestors 'none'",
    }))


def register(app, core):
    secret = os.environ.get("PD_DISPATCH_SESSION_SECRET", "")
    password_hash = os.environ.get("PD_DISPATCH_PASSWORD_HASH", "")
    raw_admin = os.environ.get("PD_DISPATCH_ADMIN_ID", "")
    dsn = os.environ.get("PD_DISPATCH_DATABASE_URL", "")
    invite_hash = os.environ.get("PD_DISPATCH_INVITE_SHA256", "")
    raw_expiration = os.environ.get("PD_DISPATCH_INVITE_EXPIRES", "")
    expires = int(raw_expiration) if re.fullmatch(r"[0-9]{1,12}", raw_expiration) else 0
    passwords = DispatcherPasswords(dsn) if dsn and not password_hash else None
    valid_admin = re.fullmatch(r"[0-9]{1,18}", raw_admin) and int(raw_admin) in core.ADMIN_IDS
    configured = password_hash.startswith(("scrypt:", "pbkdf2:")) or passwords is not None
    existing_secret = app.secret_key
    if (len(secret) < 32 or not valid_admin or not configured
            or existing_secret not in (None, secret)):
        @app.get("/dispatch")
        @app.get("/dispatch/login")
        def pd_dispatch_disabled():
            return auth_page(app, status=503, error="Вход пока недоступен.")

        @app.route("/dispatch/register", methods=["GET", "POST"])
        def pd_dispatch_registration_disabled():
            return auth_page(app, registration=True, status=503,
                             error="Регистрация по приглашению пока недоступна.")
        return False

    app.secret_key = secret
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    admin_id = int(raw_admin)
    attempts = defaultdict(deque)

    def csrf():
        if "pd_dispatch_csrf" not in session:
            session["pd_dispatch_csrf"] = secrets.token_urlsafe(32)
        return session["pd_dispatch_csrf"]

    def valid_csrf():
        value = session.get("pd_dispatch_csrf", "")
        supplied = request.form.get("csrf", "")
        return bool(value) and secrets.compare_digest(value, supplied)

    def authorized():
        return (session.get("pd_dispatch_authenticated") is True
                and session.get("pd_dispatch_admin_id") == admin_id
                and core.is_admin(admin_id))

    def within_attempt_limit(kind):
        ip = request.remote_addr or "unknown"
        history = attempts[kind, ip]
        now = time.monotonic()
        while history and history[0] < now - 900:
            history.popleft()
        if len(history) >= 5:
            return False
        history.append(now)
        return True

    def verify_form(kind):
        if request.content_length is None or request.content_length > 8192:
            return "Недопустимый размер формы", 413
        if not valid_csrf():
            return "Неверный защитный токен формы", 403
        if not within_attempt_limit(kind):
            return "Слишком много попыток. Попробуйте позже.", 429
        return None

    @app.route("/dispatch/register", methods=["GET", "POST"])
    def pd_dispatch_register():
        def page(error="", status=200, ready=False):
            return auth_page(app, registration=True, status=status, ready=ready,
                             csrf=csrf() if ready else "", error=error)

        if not passwords or not core.is_admin(admin_id):
            return page("Регистрация по приглашению сейчас закрыта.", 403)
        if request.method == "POST":
            failure = verify_form("register")
            if failure:
                return failure
        try:
            if passwords.read(admin_id):
                return page("Пароль диспетчера уже создан.")
            if not re.fullmatch(r"[0-9a-f]{64}", invite_hash) or time.time() >= expires:
                return page("Действующее приглашение отсутствует.", 403)
            if request.method == "GET":
                return page(ready=True)
            invite = request.form.get("invite", "").strip()
            digest = hashlib.sha256(invite.encode()).hexdigest()
            if not secrets.compare_digest(invite_hash, digest):
                return page("Код приглашения неверный.", 403, ready=True)
            password = request.form.get("password", "")
            if not 12 <= len(password) <= 128 or password.isspace():
                return page("Введи пароль длиной от 12 до 128 символов.", 400, ready=True)
            if password != request.form.get("confirmation", ""):
                return page("Пароли не совпадают.", 400, ready=True)
            if not passwords.create(admin_id, generate_password_hash(password)):
                return page("Пароль диспетчера уже создан.")
        except Exception as exc:
            app.logger.error("Dispatcher registration unavailable (%s)", type(exc).__name__)
            return page("Регистрация временно недоступна. Попробуй позже.", 503)
        session.clear()
        return redirect(url_for("pd_dispatch_login", registered=1), code=303)

    @app.route("/dispatch/login", methods=["GET", "POST"])
    def pd_dispatch_login():
        if authorized():
            return redirect(url_for("pd_dispatch_home"))
        error = ""
        if request.method == "POST":
            failure = verify_form("login")
            if failure:
                return failure
            try:
                credential = passwords.read(admin_id) if passwords else password_hash
            except Exception as exc:
                app.logger.error("Dispatcher credential unavailable (%s)", type(exc).__name__)
                return auth_page(app, status=503, error="Вход временно недоступен.")
            if credential and check_password_hash(credential, request.form.get("password", "")) and core.is_admin(admin_id):
                session.clear()
                session.permanent = True
                session["pd_dispatch_authenticated"] = True
                session["pd_dispatch_admin_id"] = admin_id
                csrf()
                attempts.pop(("login", request.remote_addr or "unknown"), None)
                return redirect(url_for("pd_dispatch_home"))
            error = "Неверный пароль"
        return auth_page(app, csrf=csrf(), error=error, ready=True,
                         registered=bool(passwords) and request.args.get("registered") == "1")

    @app.get("/dispatch")
    def pd_dispatch_home():
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        dashboard = Path(__file__).with_name("pd_dispatcher_dashboard.html").read_text(encoding="utf-8")
        response = app.make_response(render_template_string(dashboard, csrf=csrf()))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/dispatch/logout")
    def pd_dispatch_logout():
        if not valid_csrf():
            return "Неверный защитный токен формы", 403
        session.clear()
        return redirect(url_for("pd_dispatch_login"))
    return True
