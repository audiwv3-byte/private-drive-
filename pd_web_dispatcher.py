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
{% if registration %}<label for="invite">{{ 'Код восстановления' if recovery else 'Код приглашения' }}</label>
<input id="invite" name="invite" required maxlength="128" autocomplete="off" autocapitalize="none" spellcheck="false">
{% endif %}<label for="password">Пароль</label>
<input id="password" type="password" name="password" autocomplete="{{ 'new-password' if registration else 'current-password' }}" required maxlength="{{ 128 if registration else 512 }}" {% if registration %}minlength="12"{% endif %}>
{% if registration %}<label for="confirmation">Повтори пароль</label>
<input id="confirmation" type="password" name="confirmation" autocomplete="new-password" required minlength="12" maxlength="128">
{% endif %}<button>{{ 'Сохранить новый пароль' if recovery else ('Создать пароль' if registration else 'Войти') }}</button></form>
{% endif %}
{% if registration %}<a href="/dispatch/login">Войти в диспетчерскую</a>
{% else %}<a href="/dispatch/register">Регистрация по приглашению</a> · <a href="/dispatch/recover">Восстановить пароль</a>{% endif %}
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


    def recover(self, admin_id, previous_hash, new_hash, token_hash):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(192784221, 1)")
            db.execute("""
                CREATE TABLE IF NOT EXISTS private_drive_dispatcher_recoveries (
                    token_hash text PRIMARY KEY
                )
            """)
            if db.execute(
                "SELECT 1 FROM private_drive_dispatcher_recoveries WHERE token_hash = %s",
                (token_hash,),
            ).fetchone():
                return False
            result = db.execute("""
                UPDATE private_drive_dispatcher_passwords SET password_hash = %s
                WHERE admin_id = %s AND password_hash = %s
            """, (new_hash, admin_id, previous_hash))
            if result.rowcount != 1:
                return False
            db.execute(
                "INSERT INTO private_drive_dispatcher_recoveries VALUES (%s)",
                (token_hash,),
            )
            return True


def auth_page(app, registration=False, ready=False, status=200, recovery=False, **context):
    title = "Восстановление пароля" if recovery else (
        "Регистрация диспетчера" if registration else "Вход диспетчера"
    )
    page = render_template_string(AUTH_PAGE, title=title, registration=registration,
                                  ready=ready, recovery=recovery, **context)
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
    invite_code = os.environ.get("PD_DISPATCH_INVITE_CODE", "")
    if not invite_hash and re.fullmatch(r"[A-Za-z0-9_-]{43}", invite_code):
        invite_hash = hashlib.sha256(invite_code.encode()).hexdigest()
    raw_expiration = os.environ.get("PD_DISPATCH_INVITE_EXPIRES", "")
    expires = int(raw_expiration) if re.fullmatch(r"[0-9]{1,12}", raw_expiration) else 0
    recovery_hash = os.environ.get("PD_DISPATCH_RECOVERY_SHA256", "")
    recovery_expiry = os.environ.get("PD_DISPATCH_RECOVERY_EXPIRES", "")
    recovery_deadline = int(recovery_expiry) if re.fullmatch(r"[0-9]{1,12}", recovery_expiry) else 0
    passwords = DispatcherPasswords(dsn) if dsn else None
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
        if not (session.get("pd_dispatch_authenticated") is True
                and session.get("pd_dispatch_admin_id") == admin_id
                and core.is_admin(admin_id)):
            return False
        try:
            credential = passwords.read(admin_id) if passwords else password_hash
        except Exception as exc:
            app.logger.error("Dispatcher credential unavailable (%s)", type(exc).__name__)
            return False
        return bool(credential) and secrets.compare_digest(
            session.get("pd_dispatch_credential_version", ""),
            hashlib.sha256(credential.encode()).hexdigest(),
        )

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

    @app.route("/dispatch/recover", methods=["GET", "POST"])
    def pd_dispatch_recover():
        def page(error="", status=200, ready=False):
            return auth_page(app, registration=True, recovery=True, status=status,
                             error=error, ready=ready, csrf=csrf() if ready else "")

        if (not passwords or not core.is_admin(admin_id)
                or not re.fullmatch(r"[0-9a-f]{64}", recovery_hash)
                or time.time() >= recovery_deadline):
            return page("Нет действующего кода восстановления.", 403)
        if request.method == "GET":
            return page(ready=True)
        failure = verify_form("recover")
        if failure:
            return failure
        supplied = request.form.get("invite", "").strip()
        if not secrets.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(), recovery_hash):
            return page("Код восстановления неверен или уже использован.", 403, ready=True)
        password = request.form.get("password", "")
        if not 12 <= len(password) <= 128 or password.isspace():
            return page("Введи пароль длиной от 12 до 128 символов.", 400, ready=True)
        if password != request.form.get("confirmation", ""):
            return page("Пароли не совпадают.", 400, ready=True)
        try:
            previous = passwords.read(admin_id)
            if not previous or not passwords.recover(
                admin_id, previous, generate_password_hash(password), recovery_hash
            ):
                return page("Код восстановления неверен или уже использован.", 403)
        except Exception as exc:
            app.logger.error("Dispatcher recovery unavailable (%s)", type(exc).__name__)
            return page("Восстановление временно недоступно.", 503)
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
                session["pd_dispatch_credential_version"] = hashlib.sha256(credential.encode()).hexdigest()
                csrf()
                attempts.pop(("login", request.remote_addr or "unknown"), None)
                return redirect(url_for("pd_dispatch_home"))
            error = "Неверный пароль"
        return auth_page(app, csrf=csrf(), error=error, ready=True,
                         registered=bool(passwords) and request.args.get("registered") == "1")

    if passwords and os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1":
        from pd_site_analytics import register as register_site_analytics
        register_site_analytics(app, authorized, passwords.connect)

    from pd_dispatch_persistent import enabled as persistent_queue_ready
    from pd_dispatch_persistent import register as register_persistent_queue
    register_persistent_queue(app, authorized)
    from pd_native_pilot_assignment import dispatcher_assignment_enabled, register_dispatch_assignment
    register_dispatch_assignment(app, authorized, valid_csrf, admin_id)
    persistent_queue_enabled = persistent_queue_ready()

    test_sync_enabled = (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
                         and os.environ.get("PD_DISPATCH_TEST_SYNC") == "1")
    telegram_test_ready = False
    if test_sync_enabled:
        from pd_dispatch_test_sync import register as register_test_sync, telegram_test_enabled
        register_test_sync(app, authorized, valid_csrf, csrf=csrf)
        telegram_test_ready = telegram_test_enabled()

    # Unified registry has no write routes and stays disabled until reviewed migration.
    if os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1":
        from pd_dispatch_accounts import register as register_dispatch_accounts
        register_dispatch_accounts(app, authorized, passwords.connect if passwords else None)

    pilot_intake_available = False
    if os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1":
        from pd_pilot_qa_intake import configured as pilot_intake_configured
        pilot_intake_available = pilot_intake_configured()

    # Separate, fail-closed pilot intake shares the existing dispatcher session.
    if os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1":
        from pd_pilot_qa_intake import register as register_qa_pilots
        register_qa_pilots(app, authorized, csrf, valid_csrf)

    @app.get("/dispatch")
    def pd_dispatch_home():
        if test_sync_enabled or persistent_queue_enabled:
            return pd_dispatch_map()
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        dashboard = Path(__file__).with_name("pd_dispatcher_dashboard.html").read_text(encoding="utf-8")
        response = app.make_response(render_template_string(dashboard, csrf=csrf(),
                                     analytics_enabled="pd_site_analytics" in app.view_functions))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get("/dispatch/map")
    def pd_dispatch_map():
        """Mapbox dashboard shares the existing authenticated dispatcher session."""
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        token = os.environ.get("MAPBOX_WEB_PUBLIC_TOKEN", "").strip()
        if not re.fullmatch(r"pk\.[A-Za-z0-9_.-]{1,512}", token):
            token = ""
        page = Path(__file__).with_name("pd_dispatcher_mapbox.html").read_text(encoding="utf-8")
        use_test_queue = test_sync_enabled and (
            not persistent_queue_enabled or request.args.get("queue") == "test"
        )
        response = app.make_response(render_template_string(
            page, mapbox_token=token, test_sync_enabled=use_test_queue,
            persistent_queue_enabled=persistent_queue_enabled and not use_test_queue,
            pilot_availability_enabled=dispatcher_assignment_enabled() and not use_test_queue,
            gps_sync_enabled=test_sync_enabled,
            test_queue_link=url_for("pd_dispatch_map", queue="test")
                if test_sync_enabled and not use_test_queue else None,
            telegram_test_enabled=telegram_test_ready,
            analytics_enabled="pd_site_analytics" in app.view_functions,
            csrf=csrf() if test_sync_enabled else "",
            pilot_intake_enabled=pilot_intake_available,
            pilot_add_url="/pilot-registration" if pilot_intake_available else None,
            staging_registry="dispatch_accounts_state" in app.view_functions,
        ))
        response.headers.update({
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": (
                "default-src 'none'; "
                "script-src 'self' 'unsafe-inline' https://unpkg.com https://api.mapbox.com; "
                "style-src 'self' 'unsafe-inline' https://unpkg.com https://api.mapbox.com; "
                "img-src 'self' data: blob: https://*.mapbox.com https://tile.openstreetmap.org https://unpkg.com; "
                "worker-src blob:; "
                "connect-src 'self' https://api.mapbox.com https://events.mapbox.com; "
                "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            ),
        })
        return response

    @app.post("/dispatch/logout")
    def pd_dispatch_logout():
        if not valid_csrf():
            return "Неверный защитный токен формы", 403
        session.clear()
        return redirect(url_for("pd_dispatch_login"))
    return True
