"""ISOLATED PROTOTYPE ONLY: secure web email OTP sessions for PRIVATE DRIVE.

Not registered on the production application. No email providers configured.
No existing users/orders tables altered. No payments. Tests use fake notifier.

Future integration must separately handle verified web passenger identity,
order ownership via an explicit web-user mapping, and Telegram linking.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path

from flask import Flask, jsonify, request, session

EMAIL_PATTERN=re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,20}$")
TTL_SECONDS=600
MAX_ATTEMPTS=5
START_WINDOW_SECONDS=900
START_LIMIT=3

def create_isolated_app(database, signing_key, notifier, *, clock=time.time,
                        allowed_origin="https://wilsonpark.pythonanywhere.com"):
    """Create a disposable Flask app. Never mount to current production."""
    if not isinstance(signing_key,str) or len(signing_key)<32:
        raise ValueError("The web session secret must be a random 32+ character value")
    app=Flask("pd_isolated_web_identity")
    app.config.update(
        SECRET_KEY=signing_key,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=dt.timedelta(minutes=30),
        SESSION_COOKIE_NAME="pd_web_session_staged"
    )
    dbpath=Path(database)
    def db():
        con=sqlite3.connect(dbpath)
        con.row_factory=sqlite3.Row
        return con
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS web_users(
            web_id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            verified_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS web_auth_challenges(
            challenge_id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            code_digest TEXT NOT NULL,
            issued_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS web_auth_attempts(
            email TEXT NOT NULL,
            issued_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_auth_attempts ON web_auth_attempts(email,issued_at);
        """)
    def fail(message,code=400):
        return jsonify(error=message),code
    def csrf_token():
        if "csrf" not in session:
            session["csrf"]=secrets.token_urlsafe(32)
        return session["csrf"]
    def write_ok():
        if request.headers.get("Origin")!=allowed_origin:
            return False
        submitted=request.headers.get("X-CSRF-Token","")
        stored=session.get("csrf","")
        return bool(stored and submitted and hmac.compare_digest(stored,submitted))
    def code_digest(challenge_id,code):
        material=(challenge_id+"|"+code).encode()
        return hmac.new(signing_key.encode(),material,hashlib.sha256).hexdigest()
    @app.after_request
    def sensitive_no_cache(response):
        if request.path.startswith("/api/web/"):
            response.headers["Cache-Control"]="private, no-store, max-age=0"
            response.headers["Pragma"]="no-cache"
            response.headers["Vary"]="Cookie, Origin"
        return response
    @app.get("/api/web/csrf")
    def csrf():
        return jsonify(csrf_token=csrf_token())
    @app.post("/api/web/start")
    def begin():
        if not write_ok():return fail("Invalid request token or origin",403)
        payload=request.get_json(silent=True) or {}
        email=str(payload.get("email","")).lower().strip()
        if not EMAIL_PATTERN.fullmatch(email):return fail("Invalid email")
        current=int(clock())
        with db() as con:
            # Do not leak whether email exists in user records.
            con.execute("DELETE FROM web_auth_attempts WHERE issued_at<?",
                        (current-START_WINDOW_SECONDS,))
            count=con.execute("SELECT count(*) FROM web_auth_attempts WHERE email=?",
                              (email,)).fetchone()[0]
            if count>=START_LIMIT:return fail("Try again later",429)
            con.execute("INSERT INTO web_auth_attempts(email,issued_at) VALUES(?,?)",
                        (email,current))
            challenge=secrets.token_urlsafe(18)
            code=f"{secrets.randbelow(1000000):06d}"
            con.execute("""INSERT INTO web_auth_challenges
                (challenge_id,email,code_digest,issued_at) VALUES(?,?,?,?)""",
                (challenge,email,code_digest(challenge,code),current))
        session["pending_challenge"]=challenge
        # Only explicit dependency injection can deliver OTP. No provider is
        # used by this prototype. Never return code through HTTP.
        notifier(email,code)
        return jsonify(ok=True,message="Check your email")
    @app.post("/api/web/verify")
    def verify():
        if not write_ok():return fail("Invalid request token or origin",403)
        payload=request.get_json(silent=True) or {}
        code=str(payload.get("code",""))
        challenge=session.get("pending_challenge")
        if not challenge or not re.fullmatch(r"\d{6}",code):return fail("Invalid or expired code")
        now=int(clock())
        with db() as con:
            row=con.execute("SELECT * FROM web_auth_challenges WHERE challenge_id=?",
                            (challenge,)).fetchone()
            if not row or row["used"] or now-row["issued_at"]>TTL_SECONDS or now<row["issued_at"]:
                return fail("Invalid or expired code")
            if row["attempts"]>=MAX_ATTEMPTS:return fail("Too many attempts",429)
            con.execute("UPDATE web_auth_challenges SET attempts=attempts+1 WHERE challenge_id=?",
                        (challenge,))
            if not hmac.compare_digest(row["code_digest"],code_digest(challenge,code)):
                return fail("Invalid or expired code")
            con.execute("UPDATE web_auth_challenges SET used=1 WHERE challenge_id=?",
                        (challenge,))
            existing=con.execute("SELECT web_id FROM web_users WHERE email=?",
                                 (row["email"],)).fetchone()
            if existing:ident=existing["web_id"]
            else:
                ident="web_"+secrets.token_urlsafe(18)
                con.execute("INSERT INTO web_users VALUES(?,?,?)",(ident,row["email"],now))
        session.clear()
        session.permanent=True
        session["web_uid"]=ident
        session["csrf"]=secrets.token_urlsafe(32)
        return jsonify(ok=True)
    @app.get("/api/web/me")
    def me():
        uid=session.get("web_uid")
        if not uid:return fail("Authentication required",401)
        with db() as con:
            row=con.execute("SELECT web_id,email FROM web_users WHERE web_id=?",(uid,)).fetchone()
        if not row:return fail("Authentication required",401)
        return jsonify(id=row["web_id"],email=row["email"],role="passenger")
    @app.post("/api/web/logout")
    def logout():
        if not write_ok():return fail("Invalid request token or origin",403)
        session.clear()
        return jsonify(ok=True)
    return app
