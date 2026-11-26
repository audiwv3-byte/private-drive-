import hashlib
import hmac
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import psycopg
from werkzeug.serving import make_server

from pd_native_auth_postgres_http import initialize_database
from pd_qa25_wsgi import create_application


def test_native_cabins_against_isolated_postgres(monkeypatch, tmp_path):
    dsn = os.environ["PD_AUTH_TEST_DATABASE_URL"]
    assert dsn == "postgresql://postgres:isolated-test@127.0.0.1:5432/private_drive_test"
    assert os.environ["PD_NATIVE_SMS_ISOLATED"] == "YES"
    assert os.environ["PD_NATIVE_SMS_LIVE"] == "NO"
    assert os.environ["PD_PAYMENT_MODE"] == "disabled"
    initialize_database(dsn)

    now = int(time.time())
    tokens = {role: marker * 48 for role, marker in (
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
    telegram_token = "qa25-synthetic-qa39-cabin"
    csrf = "qa26-synthetic-qa39-cabin"
    for key, value in {
        "PD_QA25_WSGI": "1",
        "PD_QA25_TELEGRAM_TEST_TOKEN": telegram_token,
        "PD_QA25_PASSENGERS": "101",
        "PD_QA25_ADMINS": "201",
        "PD_QA26_ASSIGNMENT": "1",
        "PD_QA26_CSRF": csrf,
        "PD_QA33_TRIP": "1",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_DISPATCH_PERSISTENT_QUEUE": "1",
        "PD_NATIVE_PILOT_ASSIGNMENT": "1",
        "PD_DISPATCH_ORDERS_DATABASE_URL": api_dsn,
        "PD_PILOT_ASSIGNMENT_DATABASE_URL": api_dsn,
    }.items():
        monkeypatch.setenv(key, value)

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True, timeout=20)

    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 201})}
    signing_key = hmac.digest(b"WebAppData", telegram_token.encode(), "sha256")
    fields = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    values["hash"] = hmac.new(signing_key, fields.encode(), hashlib.sha256).hexdigest()
    server = make_server("127.0.0.1", 0, create_application(), ssl_context=(str(cert), str(key)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        subprocess.run([
            "flutter", "test", "qa/qa39_1_server_cabins_live_test.dart",
            "--no-pub", "--reporter", "expanded",
            f"--dart-define=PD_NATIVE_AUTH_API_URL=https://127.0.0.1:{server.server_port}",
        ], cwd="flutter_app", check=True, timeout=180, env={
            **os.environ,
            "QA39_CERT": str(cert),
            "QA39_DISPATCH_INIT_DATA": urlencode(values),
            "QA39_CSRF": csrf,
            **{f"QA39_{role.upper()}_TOKEN": token for role, token in tokens.items()},
        })
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    with psycopg.connect(dsn) as db:
        rows = db.execute("""
            SELECT o.status, owner.user_id, assignment.pilot_user_id
            FROM public.pd_dispatch_orders o
            JOIN public.pd_native_order_owners owner ON owner.order_id = o.id
            JOIN public.pd_native_order_assignments assignment ON assignment.order_id = o.id
        """).fetchall()
    assert rows == [("finished", "qa39-passenger", "qa39-pilot")]
