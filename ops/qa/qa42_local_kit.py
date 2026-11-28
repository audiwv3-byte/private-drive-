"""Disposable PRIVATE DRIVE QA42 local kit. Never import into production."""
import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import ssl
import time
import threading
from pathlib import Path
from urllib.parse import urlencode
import psycopg
from werkzeug.serving import make_server
from pd_native_auth_postgres_http import initialize_database
from pd_qa25_wsgi import create_application

def prepare(*, mobile_codes=None, dispatcher_password=None):
    if os.environ.get("PD_QA42_LOCAL") != "YES":
        raise RuntimeError("Explicit QA42 gate required")
    if os.environ.get("PD_AUTH_TEST_DATABASE_URL") != "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test":
        raise RuntimeError("Only disposable loopback database allowed")
    if any(k.startswith(("PG","TWILIO","STRIPE","PAYPAL","PAYSERA","PD_PILOT_QA_","MAPBOX")) or k in ("PD_DISPATCH_DATABASE_URL","PD_DISPATCH_INVITE_CODE","PD_DISPATCH_INVITE_SHA256","PD_DISPATCH_RECOVERY_SHA256","PD_DISPATCH_ORDERS_INGEST_SECRET") for k in os.environ):
        raise RuntimeError("Unexpected provider or database override environment")
    if any(os.environ.get(k) != v for k,v in {"PD_NATIVE_SMS_ISOLATED":"YES","PD_NATIVE_SMS_LIVE":"NO","PD_PAYMENT_MODE":"disabled"}.items()):
        raise RuntimeError("Isolation flags required")
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    with psycopg.connect(dsn) as db:
        if db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]:
            raise RuntimeError("Fresh disposable database required")
    initialize_database(dsn)

    now = int(time.time())
    tokens = {role: secrets.token_urlsafe(48) for role, marker in (
        ("passenger", "a"), ("other_passenger", "b"), ("pilot", "c"))}
    with psycopg.connect(dsn, autocommit=True) as db:
        for migration in (
            "native_auth_session_functions.sql",
            "native_dispatch_orders.sql",
            "native_pilot_identity.sql",
            "qa26_pilot_assignment.sql",
            "qa27_pilot_gps.sql",
            "qa32_trip_waiting.sql",
            "qa33_trip_controls.sql",
        ):
            db.execute((Path("migrations") / migration).read_text())
        db.execute("CREATE ROLE qa39_cabin_api LOGIN PASSWORD 'synthetic-api'")
        db.execute("GRANT USAGE ON SCHEMA public TO qa39_cabin_api")
        db.execute("""
            GRANT SELECT, INSERT ON public.pd_dispatch_orders,
                public.pd_native_order_owners, public.pd_native_order_quotes TO qa39_cabin_api
        """)
        db.execute("""
            GRANT EXECUTE ON FUNCTION public.pd_validate_native_session(text,bigint),
                public.pd_assign_native_order(uuid,text,text,bigint),
                public.pd_pilot_assignment_candidates(bigint),
                public.pd_native_pilot_order_state(text,bigint),
                public.pd_native_pilot_trip_action(text,text,text,bigint),
                public.pd_revoke_current_session(text,bigint),
                public.pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint),
                public.pd_qa27_dispatch_gps(uuid,bigint) TO qa39_cabin_api
        """)
        for identity, token in tokens.items():
            user_id = "qa39-" + identity
            role = "pilot" if identity == "pilot" else "passenger"
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)", (user_id, user_id))
            db.execute("INSERT INTO native_auth_roles VALUES (%s,%s)", (user_id, role))
            db.execute("""
                INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at)
                VALUES (%s,%s,%s,%s)
            """, (hashlib.sha256(token.encode()).hexdigest(), user_id, now, now + 3600))
            if role == "pilot":
                db.execute("""
                    INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at)
                    VALUES (%s,%s,'approved',%s,%s,%s)
                """, (user_id, user_id, now - 10, now + 3600, now - 5))

    api_dsn = "postgresql://qa39_cabin_api:synthetic-api@127.0.0.1:5432/private_drive_test"
    telegram_token = "qa25-synthetic-" + secrets.token_hex(32)
    csrf = "qa26-synthetic-" + secrets.token_hex(32)
    for key, value in {
        "PD_QA25_WSGI": "1",
        "PD_QA25_TELEGRAM_TEST_TOKEN": telegram_token,
        "PD_QA25_PASSENGERS": "101",
        "PD_QA25_ADMINS": "201",
        "PD_QA26_ASSIGNMENT": "1",
        "PD_QA26_CSRF": csrf,
        "PD_QA33_TRIP": "1",
        "PD_QA27_GPS": "1",
        "PD_NATIVE_SESSION_FUNCTIONS": "1",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1",
        "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_DISPATCH_ORDERS_DATABASE_URL": api_dsn,
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": api_dsn,
    }.items():
        os.environ[key] = value


    from pd_native_auth_postgres_http import session_request, reply
    from werkzeug.wrappers import Request
    orders = create_application(qa_booking=True)
    web = None
    web_assets = ("/assets/pd-black-gold.css", "/pd-logo-transparent.png")
    if dispatcher_password is not None:
        from flask import Flask, request, send_from_directory
        from types import SimpleNamespace
        from werkzeug.security import generate_password_hash
        from pd_web_dispatcher import register
        os.environ.update(PD_DISPATCH_SESSION_SECRET=secrets.token_hex(32), PD_DISPATCH_PASSWORD_HASH=generate_password_hash(dispatcher_password), PD_DISPATCH_ADMIN_ID="201", PD_DISPATCH_TEST_SYNC="0")
        web = Flask("qa42_browser_dispatcher")
        web.config.update(SESSION_COOKIE_NAME="pd_qa42_session", SESSION_COOKIE_PATH="/dispatch")
        @web.get(web_assets[0])
        @web.get(web_assets[1])
        def dispatcher_asset():
            return send_from_directory(Path(__file__).resolve().parents[2] / "assets",
                                       Path(request.path).name)
        if not register(web, SimpleNamespace(ADMIN_IDS=frozenset({201}), is_admin=lambda uid: uid==201)):
            raise RuntimeError("QA42 dispatcher initialization failed")
    from ops.qa.qa42_mobile_login import MobileLogin
    login = MobileLogin(mobile_codes, tokens) if mobile_codes is not None else None
    def app(environ, start_response):
        req = Request(environ)
        if req.path in ("/native-auth/session", "/native-auth/sign-out") and req.method == "POST":
            return session_request(api_dsn, environ, start_response, req.path, int(time.time()))
        if login is not None and req.path in ("/native-auth/request-code", "/native-auth/verify-code") and req.method == "POST":
            return login.handle(environ, start_response)
        if req.path.startswith("/native-auth/"):
            return reply(start_response, "503 Service Unavailable", {"error": "external_auth_disabled"})
        if req.path.startswith("/payment") or req.path.startswith("/v1/"):
            return reply(start_response, "403 Forbidden", {"error": "external_service_disabled"})
        if web is not None and (req.path in web_assets or req.path == "/dispatch"
                                or req.path.startswith("/dispatch/")):
            return web(environ, start_response)
        return orders(environ, start_response)

    return app, tokens, telegram_token, csrf

def make_tls_server(address, cert, key, app, *, port=443):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return make_server(address, port, app, ssl_context=context)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--credentials", required=True)
    args = parser.parse_args()
    ip = ipaddress.ip_address(args.bind)
    if ip.version != 4 or not (ip.is_loopback or any(ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"))):
        parser.error("Only explicit loopback or RFC1918 IPv4 bind allowed")
    from ops.qa.qa42_mobile_login import new_codes
    codes = new_codes()
    dispatcher_password = secrets.token_urlsafe(24)
    app, tokens, telegram_token, csrf = prepare(mobile_codes=codes, dispatcher_password=dispatcher_password)
    values = {"auth_date":str(int(time.time())), "user":json.dumps({"id":201})}
    key = hmac.digest(b"WebAppData", telegram_token.encode(), "sha256")
    fields = "\n".join(f"{k}={v}" for k,v in sorted(values.items()))
    values["hash"] = hmac.new(key, fields.encode(), hashlib.sha256).hexdigest()
    fd = os.open(args.credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd,"w") as f:
        json.dump({"mobile_codes":codes,"dispatcher_password":dispatcher_password},f)
    try:
        server = make_tls_server(args.bind, args.cert, args.key, app)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    finally:
        Path(args.credentials).unlink(missing_ok=True)

if __name__ == "__main__":
    main()
