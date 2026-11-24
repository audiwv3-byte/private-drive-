"""Exercise the real protected browser bridge against a disposable loopback DB."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import psycopg
import pytest
from PIL import Image
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from pd_dispatcher_staging_wsgi import create_app
from pd_native_auth_schema_migration import initialize_database
from pd_native_identity_http import make_identity_app, purge_expired, sanitize_photo
from pd_web_native_photo_review import ROUTE, web_review_credential_proof

USER = "pd_web_photo_review_owner"
TEST_PASSWORD = "synthetic-only"
REVIEW_PASSWORD = "synthetic-web-reviewer-only"
BROWSER_SECRET = "synthetic-review-session-token-012345"
ADMIN = 1001
REVIEWER = "private-synthetic-native-reviewer"


def fake_jpeg():
    canvas = io.BytesIO()
    Image.new("RGB", (45, 45), "blue").save(canvas, format="PNG")
    return sanitize_photo(base64.b64encode(canvas.getvalue()).decode("ascii"))


def set_up_database():
    dsn = os.getenv("PD_SYNTHETIC_WEB_PHOTO_REVIEW_DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an isolated start-empty localhost PostgreSQL fixture")
    parts = urlsplit(dsn)
    if not (os.getenv("PD_CI_FAKE_DB_ONLY") == "YES" and parts.scheme == "postgresql"
            and parts.hostname == "127.0.0.1" and parts.port == 55444
            and parts.username == USER and parts.password == TEST_PASSWORD
            and parts.path == "/private_drive_test" and not parts.query and not parts.fragment):
        raise RuntimeError("refusing to use a non-synthetic database")
    initialize_database(dsn)
    sql_dir = Path(__file__).resolve().parents[1] / "migrations"
    bridge = (sql_dir / "native_web_photo_review.sql").read_text()
    with psycopg.connect(parts._replace(path="/postgres").geturl(), autocommit=True) as wrong:
        with pytest.raises(psycopg.errors.RaiseException, match="private_drive_test"):
            wrong.execute(bridge)
        wrong.execute("ROLLBACK")
        assert wrong.execute("SELECT to_regclass('public.pd_web_photo_review_links')").fetchone() == (None,)

    db = psycopg.connect(dsn, autocommit=True)
    if db.execute("SELECT COUNT(*) FROM public.native_auth_users").fetchone()[0]:
        db.close()
        raise RuntimeError("synthetic database must be empty")
    for path in ("native_auth_session_functions.sql", "native_pilot_identity.sql",
                 "native_dispatch_orders.sql", "native_pilot_assignment.sql"):
        db.execute((sql_dir / path).read_text())
    db.execute(bridge)
    db.execute("CREATE ROLE pd_web_photo_internal LOGIN PASSWORD 'synthetic-only'")
    db.execute("CREATE ROLE pd_web_photo_outsider LOGIN PASSWORD 'synthetic-only'")
    db.execute("""
        GRANT USAGE ON SCHEMA public TO pd_web_photo_internal, pd_web_photo_outsider;
        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            public.pd_open_web_native_photo_review(BIGINT,TEXT,TEXT),
            public.pd_decide_web_native_photo_review(BIGINT,TEXT,TEXT,TEXT)
        TO pd_web_photo_internal;
    """)

    def url(user):
        return parts._replace(netloc=f"{user}:{TEST_PASSWORD}@127.0.0.1:{parts.port}").geturl()
    return db, dsn, url("pd_web_photo_internal"), url("pd_web_photo_outsider")


def csrf_from(response):
    m = re.search(rb'name="csrf" value="([^"]+)"', response.data)
    assert m is not None
    return m.group(1).decode("ascii")


def claim_from(response):
    m = re.search(rb'name="claim" value="([^"]+)"', response.data)
    assert m is not None
    return m.group(1).decode("ascii")


def login(app):
    client = app.test_client()
    csrf = csrf_from(client.get("/dispatch/login"))
    assert client.post("/dispatch/login", data={"csrf": csrf, "password": REVIEW_PASSWORD}).status_code == 302
    return client, csrf_from(client.get(ROUTE))


def test_secure_browser_review_and_native_assignment_share_existing_contract(monkeypatch):
    db, isolated, reviewer_role_url, outsider = set_up_database()
    try:
        password_hash = generate_password_hash(REVIEW_PASSWORD, method="pbkdf2:sha256:2000")
        version = hashlib.sha256(password_hash.encode()).hexdigest()
        proof = web_review_credential_proof(BROWSER_SECRET, ADMIN, version)
        for key, value in {
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_DISPATCH_ADMIN_ID": str(ADMIN),
            "PD_DISPATCH_SESSION_SECRET": BROWSER_SECRET,
            "PD_DISPATCH_PASSWORD_HASH": password_hash,
            "PD_PAYMENT_MODE": "disabled",
            "PD_DISPATCH_ORDERS_DATABASE_URL": isolated,
            "PD_WEB_NATIVE_PHOTO_REVIEW_DATABASE_URL": reviewer_role_url,
            "PD_WEB_NATIVE_PHOTO_REVIEW": "1",
        }.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("PD_DISPATCH_DATABASE_URL", raising=False)
        app = create_app()
        assert app.test_client().get(ROUTE).status_code == 401
        client, csrf = login(app)
        alternate_client, alternate_csrf = login(app)
        now = int(time.time())
        jpeg = fake_jpeg()

        def seed_user(user, role):
            db.execute("INSERT INTO public.native_auth_users VALUES (%s,'invite',%s,%s)",
                       (user, user, now-2000))
            db.execute("INSERT INTO public.native_auth_roles VALUES (%s,%s)", (user, role))

        def photo(check, user, *, submitted, expires):
            db.execute("""INSERT INTO public.native_identity_checks
                (id,user_id,status,photo,created_at,expires_at)
                VALUES (%s,%s,'pending',%s,%s,%s)""", (check, user, jpeg, submitted, expires))

        def pair(pilot):
            db.execute("INSERT INTO public.pd_web_photo_review_pairs VALUES (%s,%s,%s,NULL)",
                       (ADMIN, pilot, now-200))

        def send(subject=client, token=csrf, **fields):
            form = {"action": "open", "password": REVIEW_PASSWORD, "csrf": token, **fields}
            return subject.post(ROUTE, data=form)

        def check(check_id):
            return db.execute("SELECT status,photo,reviewer_id FROM public.native_identity_checks WHERE id=%s",
                              (check_id,)).fetchone()

        def eligible(user):
            return db.execute("SELECT public.pd_pilot_assignment_is_eligible(%s,%s)",
                              (user, int(time.time()))).fetchone()[0]

        seed_user(REVIEWER, "admin")
        seed_user("private-synthetic-approved-pilot", "pilot")
        seed_user("private-synthetic-unpaired-pilot", "pilot")
        seed_user("private-synthetic-expired-pilot", "pilot")
        # In a web-only release the native API must not offer a second path.
        # The pilot's normal photo status/submit endpoints remain available.
        native = Client(make_identity_app(Response("not found", status=404), isolated,
            start_cleanup=False, restricted_runtime=True, web_review_only=True), Response)
        synthetic_reviewer_token = "z" * 64
        reviewer_headers = {"Authorization": f"Bearer {synthetic_reviewer_token}"}
        db.execute("""INSERT INTO public.native_auth_sessions
            (token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)""",
            (hashlib.sha256(synthetic_reviewer_token.encode()).hexdigest(), REVIEWER, now-20, now+1000))
        assert native.get("/native-identity/queue", headers=reviewer_headers).status_code == 404
        assert native.get("/native-identity/photo/any", headers=reviewer_headers).status_code == 404
        assert native.post("/native-identity/decision/any", headers=reviewer_headers,
                           json={"decision": "approved"}).status_code == 404
        assert native.get("/native-identity/status").status_code == 401
        photo("private-synthetic-approval-id", "private-synthetic-approved-pilot",
              submitted=now-400, expires=now+1000)
        photo("private-synthetic-unpaired-id", "private-synthetic-unpaired-pilot",
              submitted=now-600, expires=now+1000)
        photo("private-synthetic-self-id", REVIEWER, submitted=now-500, expires=now+1000)
        photo("private-synthetic-expired-id", "private-synthetic-expired-pilot",
              submitted=now-1000, expires=now-1)

        monkeypatch.setenv("PD_WEB_NATIVE_PHOTO_REVIEW", "0")
        assert send().status_code == 503
        monkeypatch.setenv("PD_WEB_NATIVE_PHOTO_REVIEW", "1")
        monkeypatch.setenv("PD_PAYMENT_MODE", "live")
        assert send().status_code == 503
        monkeypatch.setenv("PD_PAYMENT_MODE", "disabled")
        monkeypatch.setenv("PD_WEB_NATIVE_PHOTO_REVIEW_DATABASE_URL",
                           reviewer_role_url.replace("private_drive_test", "unsafe"))
        assert send().status_code == 503
        monkeypatch.setenv("PD_WEB_NATIVE_PHOTO_REVIEW_DATABASE_URL", reviewer_role_url)

        assert send().status_code == 409  # Browser password alone cannot bind a native identity.
        db.execute("INSERT INTO public.pd_web_photo_review_links VALUES (%s,%s,%s,%s,NULL)",
                   (ADMIN, REVIEWER, proof, now-200))
        pair(REVIEWER)  # Even deliberately bad, synthetic operator data cannot permit self review.
        pair("private-synthetic-expired-pilot")
        assert send().status_code == 409
        pair("private-synthetic-approved-pilot")
        # A cookie's visible credential version is not the server proof,
        # even if presented directly by the constrained role.
        with psycopg.connect(reviewer_role_url) as limited:
            assert limited.execute("SELECT public.pd_open_web_native_photo_review(%s,%s,%s)",
                                   (ADMIN, version, "a"*64)).fetchone() == (None,)

        cross_site = client.post(ROUTE, data={"action": "open", "csrf": csrf, "password": REVIEW_PASSWORD},
                                 headers={"Sec-Fetch-Site": "cross-site"})
        assert cross_site.status_code == 403
        assert send(token="forged").status_code == 403
        assert send(password="incorrect").status_code == 403
        assert send(user_id="private-synthetic-approved-pilot").status_code == 400
        assert client.get(ROUTE+"?check=private-synthetic-approval-id").status_code == 400
        assert client.get(ROUTE+"/photos").status_code == 404
        assert b"data:image" not in client.get(ROUTE).data

        opened = send()
        assert opened.status_code == 200
        assert opened.data.count(b"data:image/jpeg;base64,") == 1
        assert base64.b64encode(jpeg) in opened.data
        for hidden in (b"private-synthetic-", REVIEW_PASSWORD.encode(), version.encode(), proof.encode()):
            assert hidden not in opened.data
        assert "no-store" in opened.headers["Cache-Control"]
        assert "default-src 'none'" in opened.headers["Content-Security-Policy"]
        assert opened.headers["Referrer-Policy"] == "no-referrer"
        reference = claim_from(opened)
        assert send().status_code == 409  # Never return a second image while one case is open.
        assert send(action="decide", decision="approved", claim=reference).status_code == 200
        assert check("private-synthetic-approval-id") == ("approved", None, REVIEWER)
        assert eligible("private-synthetic-approved-pilot")
        assert send(action="decide", decision="approved", claim=reference).status_code == 409
        assert check("private-synthetic-self-id") == ("pending", jpeg, None)
        assert check("private-synthetic-unpaired-id") == ("pending", jpeg, None)
        assert check("private-synthetic-expired-id") == ("pending", jpeg, None)
        purge_expired(isolated, int(time.time()))
        assert check("private-synthetic-expired-id") == ("expired", None, None)

        seed_user("private-synthetic-rejected-pilot", "pilot")
        pair("private-synthetic-rejected-pilot")
        photo("private-synthetic-reject-id", "private-synthetic-rejected-pilot",
              submitted=now-300, expires=now+1000)
        second = send()
        another = claim_from(second)
        # Claims bind to the login session, not just a dispatcher ID/password.
        assert send(alternate_client, alternate_csrf, action="decide",
                    decision="approved", claim=another).status_code == 409
        assert send(action="decide", decision="approved", claim=another, password="wrong").status_code == 403
        db.execute("UPDATE public.native_auth_roles SET role='passenger' WHERE user_id=%s", (REVIEWER,))
        assert send(action="decide", decision="approved", claim=another).status_code == 409
        db.execute("UPDATE public.native_auth_roles SET role='admin' WHERE user_id=%s", (REVIEWER,))
        db.execute("UPDATE public.pd_web_photo_review_pairs SET revoked_at=%s WHERE native_pilot_id=%s",
                   (now, "private-synthetic-rejected-pilot"))
        assert send(action="decide", decision="approved", claim=another).status_code == 409
        db.execute("UPDATE public.pd_web_photo_review_pairs SET revoked_at=NULL WHERE native_pilot_id=%s",
                   ("private-synthetic-rejected-pilot",))
        assert check("private-synthetic-reject-id") == ("pending", jpeg, None)

        cookie = client.get_cookie("pd_dispatch_staging_session", path="/dispatch")
        def reject_race(_):
            worker = app.test_client()
            worker.set_cookie("pd_dispatch_staging_session", cookie.value, path="/dispatch")
            return send(worker, action="decide", decision="rejected", claim=another).status_code
        with ThreadPoolExecutor(2) as workers:
            assert sorted(workers.map(reject_race, range(2))) == [200,409]
        assert check("private-synthetic-reject-id") == ("rejected", None, REVIEWER)
        assert not eligible("private-synthetic-rejected-pilot")

        seed_user("private-synthetic-newer-pilot", "pilot")
        pair("private-synthetic-newer-pilot")
        photo("private-synthetic-older-case", "private-synthetic-newer-pilot",
              submitted=now-300, expires=now+1000)
        third = claim_from(send())
        db.execute("UPDATE public.pd_web_photo_review_claims SET expires_at=%s WHERE browser_admin_id=%s",
                   (now-1, ADMIN))
        assert send(action="decide", decision="approved", claim=third).status_code == 409
        fourth = claim_from(send())
        db.execute("UPDATE public.pd_web_photo_review_links SET credential_proof=%s WHERE browser_admin_id=%s",
                   ("0"*64, ADMIN))
        assert send(action="decide", decision="approved", claim=fourth).status_code == 409
        db.execute("UPDATE public.pd_web_photo_review_links SET credential_proof=%s WHERE browser_admin_id=%s",
                   (proof, ADMIN))
        photo("private-synthetic-newest-case", "private-synthetic-newer-pilot",
              submitted=now-200, expires=now+1000)
        assert send(action="decide", decision="approved", claim=fourth).status_code == 409
        assert check("private-synthetic-older-case") == ("pending", jpeg, None)
        assert not eligible("private-synthetic-newer-pilot")

        for restricted, statement in (
            (reviewer_role_url, "SELECT photo FROM public.native_identity_checks"),
            (reviewer_role_url, "SELECT * FROM public.pd_web_photo_review_links"),
            (reviewer_role_url, "SELECT * FROM public.pd_web_photo_review_case(1001,'unknown',10,NULL)"),
            (outsider, "SELECT public.pd_open_web_native_photo_review(1001,NULL,NULL)"),
            (outsider, "SELECT public.pd_decide_web_native_photo_review(1001,NULL,NULL,NULL)"),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with psycopg.connect(restricted) as limited:
                    limited.execute(statement)

        db.execute("UPDATE public.pd_web_photo_review_links SET revoked_at=%s WHERE browser_admin_id=%s",
                   (now, ADMIN))
        assert send().status_code == 409
        # Second browser can't gain authority simply by building a legacy route.
        assert db.execute("SELECT to_regclass('public.pd_qa_pilot_applications')").fetchone() == (None,)
    finally:
        db.close()
