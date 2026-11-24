"""Tests destructive setup only in the local synthetic PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from urllib.parse import urlsplit

from pd_issue_closed_pilot_invite import issue
from pd_native_closed_invites import PILOT_INVITE_PATH, make_closed_invites_app
from pd_native_auth_postgres_session_lifecycle import inspect_session, revoke_current_session
from test_native_closed_invites import FLAGS, fallback, request

DSN = os.environ.get("PD_CI_CLOSED_INVITES_TEST_PG", "")
PG_OWNER = "pd_invite_ci"
PILOT_FLAGS = {**FLAGS, "PD_NATIVE_PILOT_INVITE_ONBOARDING": "1"}


@unittest.skipUnless(DSN, "requires isolated local Postgres fixture")
class ClosedInvitePgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from pd_native_auth_schema_migration import initialize_database
        parsed = urlsplit(DSN)
        if ((parsed.hostname, parsed.port, parsed.username, parsed.path) !=
                ("127.0.0.1", 55438, PG_OWNER, "/private_drive_test")
                or parsed.query or parsed.fragment):
            raise RuntimeError("refusing DDL outside the disposable local fixture")
        cls.psycopg = psycopg
        initialize_database(DSN)
        with psycopg.connect(DSN, autocommit=True) as db:
            db.execute(Path("migrations/native_auth_session_functions.sql").read_text())
            db.execute(Path("migrations/native_closed_pilot_invites.sql").read_text())
            # Existing already-issued passenger credential remains compatible.
            cls.legacy_user_id = "existing-invite-passenger"
            cls.legacy_session_digest = hashlib.sha256(b"z" * 64).hexdigest()
            now = int(time.time())
            db.execute("INSERT INTO public.native_auth_users VALUES (%s,'invite','previous-invite-id',%s)",
                       (cls.legacy_user_id, now-30))
            db.execute("INSERT INTO public.native_auth_sessions "
                       "(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",
                       (cls.legacy_session_digest, cls.legacy_user_id, now-30, now+600))
            db.execute(Path("migrations/native_pilot_invite_onboarding.sql").read_text())
            db.execute("CREATE ROLE pd_closed_invite_runtime")
            db.execute("CREATE ROLE pd_closed_invite_outsider")
            db.execute("GRANT EXECUTE ON FUNCTION public.pd_redeem_closed_pilot_invite(TEXT,TEXT), "
                       "public.pd_redeem_closed_pilot_account_invite(TEXT,TEXT) "
                       "TO pd_closed_invite_runtime")

    def issue(self, *, user_id=None, approved_pilot_id=None, env=FLAGS):
        with tempfile.TemporaryDirectory() as temp:
            secret_file = Path(temp) / "secret.json"
            issue(DSN, secret_file, 1, env=env, user_id=user_id,
                  approved_pilot_id=approved_pilot_id)
            self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
            return json.loads(secret_file.read_text())

    def pilot_account(self):
        # Pre-provisioned by the synthetic operator, not by invitation issuance.
        uid = self.issue()["user_id"]
        with self.psycopg.connect(DSN) as db:
            db.execute("INSERT INTO public.native_auth_roles VALUES (%s,'pilot')", (uid,))
        return uid

    def test_legacy_invite_session_migrates_and_cannot_inherit_a_pilot_grant(self):
        with self.psycopg.connect(DSN) as db:
            def active():
                return db.execute(
                    "SELECT user_id,server_role FROM public.pd_validate_native_session(%s,%s)",
                    (self.legacy_session_digest, int(time.time())),
                ).fetchone()
            self.assertEqual(active(), (self.legacy_user_id, "passenger"))
            db.execute("INSERT INTO public.native_auth_roles VALUES (%s,'pilot')",
                       (self.legacy_user_id,))
            self.assertIsNone(active())

    def test_pilot_issue_requires_operator_approval_and_explicit_flag(self):
        passenger = self.issue()["user_id"]
        pilot = self.pilot_account()
        for kwargs in (
            {"approved_pilot_id": passenger, "env": PILOT_FLAGS},
            {"approved_pilot_id": "not-provisioned", "env": PILOT_FLAGS},
            {"approved_pilot_id": pilot, "env": FLAGS},
            {"approved_pilot_id": pilot, "env": {**PILOT_FLAGS, "PD_NATIVE_SMS_LIVE": "YES"}},
            {"approved_pilot_id": pilot,
             "env": {**PILOT_FLAGS, "PD_PAYMENT_MODE": "enabled"}},
            {"approved_pilot_id": pilot, "env": PILOT_FLAGS, "user_id": passenger},
            {"user_id": pilot, "env": PILOT_FLAGS},
        ):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "secret.json"
                with self.assertRaises(ValueError):
                    issue(DSN, path, 1, **kwargs)
                self.assertFalse(path.exists())

    def test_pilot_redeems_exactly_once_only_when_enabled_and_session_has_purpose(self):
        pilot = self.pilot_account()
        item = self.issue(approved_pilot_id=pilot, env=PILOT_FLAGS)
        payload = {"invite_code": item["invite_code"]}
        off = make_closed_invites_app(fallback, DSN, environ=FLAGS)
        on = make_closed_invites_app(fallback, DSN, environ=PILOT_FLAGS)
        # Wrong purpose cannot consume a code even when both routes are on.
        self.assertEqual(request(on, payload=payload)["status"], 401)
        self.assertEqual(request(off, path=PILOT_INVITE_PATH, payload=payload)["status"], 404)
        passenger = self.issue()
        self.assertEqual(request(on, path=PILOT_INVITE_PATH,
                                 payload={"invite_code": passenger["invite_code"]})["status"], 401)
        self.assertEqual(request(on, payload={"invite_code": passenger["invite_code"]})["status"], 200)
        self.assertEqual(request(on, path=PILOT_INVITE_PATH,
                                 payload={**payload, "role": "pilot"})["status"], 400)
        with ThreadPoolExecutor(max_workers=6) as pool:
            outputs = list(pool.map(lambda _: request(on, path=PILOT_INVITE_PATH,
                                                      payload=payload), range(6)))
        self.assertEqual(sorted(r["status"] for r in outputs), [200, 401, 401, 401, 401, 401])
        auth = next(r["body"] for r in outputs if r["status"] == 200)
        self.assertEqual((auth["user_id"], auth["role"]), (pilot, "pilot"))
        digest = hashlib.sha256(auth["access_token"].encode()).hexdigest()
        with self.psycopg.connect(DSN) as db:
            self.assertEqual(db.execute(
                "SELECT user_id,server_role,expires_at FROM public.pd_validate_native_session(%s,%s)",
                (digest, int(time.time())),
            ).fetchone(), (pilot, "pilot", auth["expires_at"]))
            self.assertEqual(db.execute(
                "SELECT purpose FROM public.pd_native_closed_invite_sessions WHERE token_hash=%s",
                (digest,),
            ).fetchone(), ("pilot",))

    def test_demotion_and_repromotion_never_revive_old_pilot_codes_or_sessions(self):
        pilot = self.pilot_account()
        redeemed = self.issue(approved_pilot_id=pilot, env=PILOT_FLAGS)
        app = make_closed_invites_app(fallback, DSN, environ=PILOT_FLAGS)
        auth = request(app, path=PILOT_INVITE_PATH, payload={"invite_code": redeemed["invite_code"]})["body"]
        digest = hashlib.sha256(auth["access_token"].encode()).hexdigest()
        old = self.issue(approved_pilot_id=pilot, env=PILOT_FLAGS)
        with self.psycopg.connect(DSN) as db:
            db.execute("UPDATE public.native_auth_roles SET role='passenger' WHERE user_id=%s",
                       (pilot,))
            db.execute("UPDATE public.native_auth_roles SET role='pilot' WHERE user_id=%s",
                       (pilot,))
            self.assertIsNone(db.execute(
                "SELECT user_id FROM public.pd_validate_native_session(%s,%s)",
                (digest, int(time.time())),
            ).fetchone())
        self.assertEqual(request(app, path=PILOT_INVITE_PATH,
                                 payload={"invite_code": old["invite_code"]})["status"], 401)
        new = self.issue(approved_pilot_id=pilot, env=PILOT_FLAGS)
        self.assertEqual(request(app, path=PILOT_INVITE_PATH,
                                 payload={"invite_code": new["invite_code"]})["status"], 200)

    def test_transactional_single_redeem_existing_session_and_revoke(self):
        item = self.issue()
        code = item["invite_code"]
        digest = hashlib.sha256(code.encode("ascii")).hexdigest()
        app = make_closed_invites_app(fallback, DSN, environ=FLAGS)
        with ThreadPoolExecutor(max_workers=6) as pool:
            outputs = list(pool.map(lambda _: request(app, payload={"invite_code": code}), range(6)))
        self.assertEqual(sorted(response["status"] for response in outputs), [200, 401, 401, 401, 401, 401])
        auth = next(response["body"] for response in outputs if response["status"] == 200)
        self.assertEqual(auth["user_id"], item["user_id"])
        with self.psycopg.connect(DSN) as db:
            self.assertEqual(inspect_session(db, auth["access_token"]), (item["user_id"], "passenger"))
            self.assertEqual(db.execute(
                "SELECT count(*) FROM public.native_auth_sessions WHERE user_id=%s",
                (item["user_id"],),
            ).fetchone(), (1,))
            self.assertEqual(db.execute(
                "SELECT invite_hash,consumed_at IS NOT NULL FROM public.pd_native_closed_pilot_invites WHERE user_id=%s",
                (item["user_id"],),
            ).fetchone(), (digest, True))
            self.assertTrue(revoke_current_session(db, auth["access_token"]))
            self.assertIsNone(inspect_session(db, auth["access_token"]))

    def test_reissue_keeps_identity_and_voids_old_code(self):
        old = self.issue()
        replacement = self.issue(user_id=old["user_id"])
        app = make_closed_invites_app(fallback, DSN, environ=FLAGS)
        self.assertEqual(request(app, payload={"invite_code": old["invite_code"]})["status"], 401)
        response = request(app, payload={"invite_code": replacement["invite_code"]})
        self.assertEqual((response["status"], response["body"]["user_id"]), (200, old["user_id"]))

    def test_expired_and_elevated_invites_cannot_issue_session(self):
        expired = self.issue()
        elevated = self.issue()
        with self.psycopg.connect(DSN) as db:
            db.execute("UPDATE public.pd_native_closed_pilot_invites SET created_at=1,expires_at=2 WHERE user_id=%s",
                       (expired["user_id"],))
            db.execute("INSERT INTO public.native_auth_roles (user_id,role) VALUES (%s,'pilot')",
                       (elevated["user_id"],))
        app = make_closed_invites_app(fallback, DSN, environ=FLAGS)
        for item in (expired, elevated):
            self.assertEqual(request(app, payload={"invite_code": item["invite_code"]})["status"], 401)
        with self.psycopg.connect(DSN) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM public.native_auth_sessions WHERE user_id=ANY(%s)",
                ([expired["user_id"], elevated["user_id"]],),
            ).fetchone(), (0,))

    def test_failed_session_insert_rolls_back_invite_consumption(self):
        item = self.issue()
        code = item["invite_code"]
        app = make_closed_invites_app(fallback, DSN, environ=FLAGS)
        collision_token = "Z" * 64
        collision_digest = hashlib.sha256(collision_token.encode("ascii")).hexdigest()
        with self.psycopg.connect(DSN) as db:
            db.execute(
                "INSERT INTO public.native_auth_sessions "
                "(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,1,2)",
                (collision_digest, item["user_id"]),
            )
        collision_app = make_closed_invites_app(
            fallback, DSN, environ=FLAGS, token=lambda n: collision_token,
        )
        self.assertEqual(request(collision_app, payload={"invite_code": code})["status"], 503)
        self.assertEqual(request(app, payload={"invite_code": code})["status"], 200)

    def test_wsgirole_cannot_read_store_and_outsider_cannot_redeem(self):
        item = self.issue()
        digest = hashlib.sha256(item["invite_code"].encode("ascii")).hexdigest()
        with closing(self.psycopg.connect(DSN, autocommit=True)) as db:
            db.execute("SET ROLE pd_closed_invite_outsider")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.pd_redeem_closed_pilot_invite(%s,%s)", (digest, "a"*64))
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.pd_redeem_closed_pilot_account_invite(%s,%s)",
                           (digest, "b" * 64))
            db.execute("SET ROLE pd_closed_invite_runtime")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.pd_redeem_closed_invite_bound(%s,%s,'pilot')",
                           (digest, "c" * 64))
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.pd_native_closed_invite_sessions")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.pd_native_closed_pilot_invites")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM public.native_auth_sessions")
            result = db.execute(
                "SELECT user_id,server_role FROM public.pd_redeem_closed_pilot_invite(%s,%s)", (digest, "a"*64)
            ).fetchone()
            self.assertEqual(result, (item["user_id"], "passenger"))


if __name__ == "__main__":
    unittest.main()
