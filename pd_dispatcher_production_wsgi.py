"""WSGI entry point for the separate dispatcher web app on PythonAnywhere."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

from flask import Flask, redirect, send_from_directory, url_for

from pd_web_dispatcher import decode_totp_key, register


class OwnerCredentials:
    """Persist MFA attempts and consumed codes independently of the trip database."""

    def __init__(self, directory, password_hash):
        self.path = directory / "owner-mfa.sqlite3"
        self.password_hash = password_hash
        with closing(sqlite3.connect(self.path, timeout=5)) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS owner_mfa (
                    admin_id INTEGER PRIMARY KEY,
                    attempt_window INTEGER NOT NULL,
                    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 1 AND 5),
                    last_counter INTEGER NOT NULL DEFAULT -1
                )
            """)

    def read(self, admin_id):
        return self.password_hash

    def reserve_owner_attempt(self, admin_id, window):
        with closing(sqlite3.connect(self.path, timeout=5)) as conn, conn:
            cursor = conn.execute("""
                INSERT INTO owner_mfa (admin_id, attempt_window, attempts)
                VALUES (?, ?, 1)
                ON CONFLICT (admin_id) DO UPDATE SET
                    attempts = CASE WHEN owner_mfa.attempt_window = excluded.attempt_window
                                    THEN owner_mfa.attempts + 1 ELSE 1 END,
                    attempt_window = excluded.attempt_window
                WHERE owner_mfa.attempt_window < excluded.attempt_window
                    OR (owner_mfa.attempt_window = excluded.attempt_window AND owner_mfa.attempts < 5)
            """, (admin_id, window))
            return cursor.rowcount == 1

    def consume_totp(self, admin_id, counter):
        with closing(sqlite3.connect(self.path, timeout=5)) as conn, conn:
            cursor = conn.execute("""
                UPDATE owner_mfa SET last_counter = ?
                WHERE admin_id = ? AND last_counter < ?
            """, (counter, admin_id, counter))
            return cursor.rowcount == 1


@contextmanager
def read_orders(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as conn:
        conn.row_factory = sqlite3.Row
        yield conn


def create_app():
    if (os.environ.get("PD_DISPATCH_STAGING_ONLY") == "1"
            or os.environ.get("PD_DISPATCH_REQUIRE_MFA") != "1"
            or os.environ.get("PD_DISPATCH_LIVE_ORDERS") != "1"):
        raise RuntimeError("The production dispatcher requires the live orders and MFA flags")

    admin = os.environ.get("PD_DISPATCH_ADMIN_ID", "")
    password_hash = os.environ.get("PD_DISPATCH_PASSWORD_HASH", "")
    if (not re.fullmatch(r"[1-9][0-9]{0,17}", admin)
            or not password_hash.startswith(("scrypt:", "pbkdf2:"))
            or len(os.environ.get("PD_DISPATCH_SESSION_SECRET", "")) < 32
            or not decode_totp_key(os.environ.get("PD_DISPATCH_TOTP_BASE32", ""))):
        raise RuntimeError("Configure the dispatcher owner's credentials before starting")
    admin_id = int(admin)

    base = Path(__file__).resolve().parent
    orders = Path(os.environ["PD_DISPATCH_ORDERS_SQLITE"]).resolve(strict=True)
    state = Path(os.environ["PD_DISPATCH_OWNER_STATE_DIR"]).resolve(strict=True)
    if not orders.is_file() or not state.is_dir() or state.stat().st_mode & 0o077:
        raise RuntimeError("A source database and a private owner state directory are required")

    app = Flask(__name__, static_folder=None)
    app.config.update(SESSION_COOKIE_NAME="pd_dispatch_owner_session", SESSION_COOKIE_PATH="/dispatch")

    @app.context_processor
    def dispatch_assets():
        return {"dispatch_asset_prefix": "/dispatch"}
    core = SimpleNamespace(ADMIN_IDS=frozenset({admin_id}), is_admin=lambda uid: uid == admin_id,
                           ORDERS_DB=orders, USERS_DB=Path(os.environ.get("PD_DISPATCH_USERS_SQLITE", orders.with_name("users.db"))), db=read_orders)
    from pd_pilot_qa_intake import register_production_form

    pilot_intake = register_production_form(app, state)
    if not register(app, core, owner_passwords=OwnerCredentials(state, password_hash),
                    pilot_intake=pilot_intake):
        raise RuntimeError("Dispatcher could not enable owner authentication")

    @app.get("/")
    def home():
        return redirect(url_for("pd_dispatch_home"))

    @app.get("/dispatch/pd-logo-transparent.png")
    def brand_logo():
        return send_from_directory(base / "assets", "pd-logo-transparent.png")

    @app.get("/dispatch/assets/pd-black-gold.css")
    def brand_styles():
        return send_from_directory(base / "assets", "pd-black-gold.css")

    return app


def mount_dispatcher(miniapp, dispatcher=None):
    """Host the owner-only dispatcher and the Telegram Mini App in one WSGI slot."""
    if dispatcher is None:
        dispatcher = create_app()

    def application(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if (path == "/dispatch" or path.startswith("/dispatch/")
                or (path == "/pilot-registration" and hasattr(dispatcher, "view_functions")
                    and "pilot_registration" in dispatcher.view_functions)):
            return dispatcher(environ, start_response)
        return miniapp(environ, start_response)

    return application
