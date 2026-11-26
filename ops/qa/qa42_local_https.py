"""Local QA42.1 harness; run only against a disposable loopback database."""
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode
import psycopg
from werkzeug.serving import make_server
from pd_native_auth_postgres_http import initialize_database
from pd_qa25_wsgi import create_application

def prepare():
    dsn = "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    if os.environ.get("PD_QA42_LOCAL") != "1":
        raise RuntimeError("Explicit local QA opt-in required")
    if os.environ.get("PD_AUTH_TEST_DATABASE_URL") != dsn:
        raise RuntimeError("Disposable loopback database required")
    with psycopg.connect(dsn) as db:
        if db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]:
            raise RuntimeError("Fresh empty QA database required")
    # Remove inherited application configuration before initialization.
    for key in list(os.environ):
        if key.startswith(("PD_", "TWILIO_", "PG")) or key == "DATABASE_URL":
            del os.environ[key]
    os.environ.update(PD_NATIVE_SMS_ISOLATED="YES", PD_NATIVE_SMS_LIVE="NO", PD_PAYMENT_MODE="disabled")
    initialize_database(dsn)

    now = int(time.time())
    tokens = {role: secrets.token_urlsafe(48) for role in ("passenger", "other_passenger", "pilot")}
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
                public.pd_revoke_current_session(text,bigint),
                public.pd_qa27_write_gps(text,uuid,boolean,double precision,double precision,bigint,bigint),
                public.pd_qa27_dispatch_gps(uuid,bigint),
                public.pd_native_pilot_order_state(text,bigint),
                public.pd_native_pilot_trip_action(text,text,text,bigint) TO qa39_cabin_api
        """)
        for identity, token in tokens.items():
            user_id = "qa39-" + identity
            role = "pilot" if identity == "pilot" else "passenger"
            db.execute("INSERT INTO native_auth_users VALUES (%s,'phone',%s,0)", (user_id, user_id))
            db.execute("INSERT INTO native_auth_roles VALUES (%s,%s)", (user_id, role))
            db.execute("""
                INSERT INTO native_auth_sessions(token_hash,user_id,created_at,expires_at)
                VALUES (%s,%s,%s,%s)
            """, (hashlib.sha256(token.encode()).hexdigest(), user_id, now, now + 900))
            if role == "pilot":
                db.execute("""
                    INSERT INTO native_identity_checks(id,user_id,status,created_at,expires_at,decided_at)
                    VALUES (%s,%s,'approved',%s,%s,%s)
                """, (user_id, user_id, now - 10, now + 900, now - 5))

    api_dsn = "postgresql://qa39_cabin_api:synthetic-api@127.0.0.1:5432/private_drive_test"
    telegram_token = "qa25-synthetic-" + secrets.token_urlsafe(32)
    csrf = "qa26-synthetic-" + secrets.token_urlsafe(32)
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


    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 201})}
    signing_key = hmac.digest(b"WebAppData", telegram_token.encode(), "sha256")
    fields = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    values["hash"] = hmac.new(signing_key, fields.encode(), hashlib.sha256).hexdigest()
    return create_application(), tokens, urlencode(values), csrf

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    app, tokens, dispatch, csrf = prepare()
    # Credentials are intentionally not printed or committed.
    server = make_server("127.0.0.1", 443, app, ssl_context=(args.cert, args.key))
    try:
        server.serve_forever()
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
