"""Isolated browser dispatcher MVP. Disabled until explicitly configured.

Existing Telegram Mini App endpoints and authentication are unchanged.
"""
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from flask import redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash

LOGIN = """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PRIVATE DRIVE — вход диспетчера</title>
<style>body{background:#101114;color:#ecd7a1;font:16px system-ui;margin:0;display:grid;min-height:100vh;place-items:center}main{width:min(430px,88vw);padding:28px;background:#1d1e22;border:1px solid #ae935b;border-radius:16px}input,button{display:block;box-sizing:border-box;width:100%;padding:13px;margin:14px 0;border-radius:8px;font:inherit}button{background:#b89a57;color:#111;border:0;font-weight:700;cursor:pointer}input{background:white;color:#111}small{color:#bbb}</style>
<main><img src="/pd-logo.jpg" alt="PRIVATE DRIVE — логотип PD с автомобилем" width="112" height="112" style="display:block;object-fit:contain;margin:0 auto 14px;border-radius:14px"><h1 style="text-align:center">PRIVATE DRIVE</h1><h2>Вход диспетчера</h2>{% if error %}<p role="alert">{{ error }}</p>{% endif %}
<form method="post"><input type="hidden" name="csrf" value="{{ csrf }}"><label for="password">Пароль</label>
<input id="password" type="password" name="password" autocomplete="current-password" required maxlength="512">
<button>Войти</button></form><small>Доступ только для уполномоченного администратора.</small></main></html>"""

# Dashboard template belongs to the isolated test interface.
from pathlib import Path
HOME = Path(__file__).with_name("pd_dispatcher_dashboard.html").read_text(encoding="utf-8")


def register(app, core):
    secret = os.environ.get("PD_DISPATCH_SESSION_SECRET", "")
    password_hash = os.environ.get("PD_DISPATCH_PASSWORD_HASH", "")
    raw_admin = os.environ.get("PD_DISPATCH_ADMIN_ID", "")
    enabled = (len(secret) >= 32 and password_hash.startswith(("scrypt:", "pbkdf2:"))
               and raw_admin.isascii() and raw_admin.isdecimal()
               and int(raw_admin) in core.ADMIN_IDS)
    if not enabled:
        @app.get("/dispatch")
        @app.get("/dispatch/login")
        def pd_dispatch_disabled():
            return "Диспетчерская не настроена", 503
        return False

    # Fail closed on a shared Flask app: changing SECRET_KEY would invalidate
    # existing Telegram sessions and make the dispatcher share its cookie.
    # Dispatcher must be mounted as a separate Flask application for staging.
    existing_secret = app.secret_key
    if existing_secret is not None and existing_secret != secret:
        @app.get("/dispatch")
        @app.get("/dispatch/login")
        def pd_dispatch_shared_app_disabled():
            return "Диспетчерская требует отдельного Flask-приложения", 503
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

    @app.route("/dispatch/login", methods=["GET", "POST"])
    def pd_dispatch_login():
        if authorized():
            return redirect(url_for("pd_dispatch_home"))
        error = ""
        if request.method == "POST":
            ip = request.remote_addr or "unknown"
            history = attempts[ip]
            now = time.monotonic()
            while history and history[0] < now - 900:
                history.popleft()
            if len(history) >= 5:
                return "Слишком много попыток. Попробуйте позже.", 429
            if not valid_csrf():
                return "Неверный защитный токен формы", 403
            history.append(now)
            if check_password_hash(password_hash, request.form.get("password", "")) and core.is_admin(admin_id):
                session.clear()
                session.permanent = True
                session["pd_dispatch_authenticated"] = True
                session["pd_dispatch_admin_id"] = admin_id
                csrf()
                history.clear()
                return redirect(url_for("pd_dispatch_home"))
            error = "Неверный пароль"
        response = app.make_response(render_template_string(LOGIN, csrf=csrf(), error=error))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/dispatch")
    def pd_dispatch_home():
        if not authorized():
            return redirect(url_for("pd_dispatch_login"))
        response = app.make_response(render_template_string(HOME, csrf=csrf()))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/dispatch/logout")
    def pd_dispatch_logout():
        if not valid_csrf():
            return "Неверный защитный токен формы", 403
        session.clear()
        return redirect(url_for("pd_dispatch_login"))
    return True
