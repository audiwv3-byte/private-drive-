"""Issue #30: execute SHA-pinned deployed onboarding with an in-memory patch.

Only PythonAnywhere operation is GET of pd_onboarding.py; all Flask requests
target a local Flask TESTING app and a temporary SQLite database.
Never save or upload the fetched source, documents, DB or payloads.
"""
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import quote

import requests
from PIL import Image
from flask import Flask, jsonify, request

import pd_issue30_patch_live_onboarding_offline as patcher


def get_verified_live_bytes():
    token = "".join(os.environ.get("PA_API_TOKEN", "").strip().split())
    if not token:
        raise RuntimeError("PA_API_TOKEN absent; live-source end-to-end tests cannot run")
    path = "/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_onboarding.py"
    url = ("https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"
           + quote(path, safe="/"))
    response = requests.get(url, headers={"Authorization": "Token " + token},
                            timeout=35)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != patcher.EXPECTED_SHA256:
        raise patcher.PatchMismatch("Live onboarding source changed: stop; no patch applied")
    return response.content


class FakeCore:
    USERS_DB = "synthetic"
    def __init__(self, path):
        self.path = path
        self.notifications = []

    @contextmanager
    def db(self, _):
        c = sqlite3.connect(self.path, isolation_level=None, timeout=8)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=8000")
        try:
            yield c
            if c.in_transaction:
                c.commit()
        except BaseException:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()

    def initialize(self):
        pass

    def clean_phone(self, value):
        return "".join(ch for ch in value if ch.isdigit() or ch == "+")

    def now(self):
        return datetime(2026, 11, 17, 12, 0)

    def is_admin(self, uid):
        return uid == 9001

    def notify_admins(self, text):
        self.notifications.append("synthetic-notification")


def make_photo(color):
    # Fully valid image accepted by actual live read_photos(), not dummy bytes.
    img = Image.new("RGB", (1200, 800), color)
    stream = io.BytesIO()
    img.save(stream, format="JPEG")
    return stream.getvalue()


class LivePatchIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = get_verified_live_bytes()
        cls.original_source = raw.decode("utf-8")
        cls.patched_source = patcher.patch_source(raw)
        # Real deployed source is never written to disk or into a GitHub artifact.
        assert "ON CONFLICT(telegram_id,side) DO UPDATE SET image" not in cls.patched_source
        assert "pilot_insert_missing" in cls.patched_source
        cls.doc_images = {
            "license_front": make_photo((220, 30, 30)),
            "license_back": make_photo((20, 220, 20)),
            "car_front": make_photo((20, 20, 220)),
            "car_rear": make_photo((240, 190, 30)),
            "car_interior": make_photo((60, 120, 180)),
            "registration_front": make_photo((60, 120, 30)),
            "ltsa": make_photo((120, 60, 30)),
            "activity": make_photo((120, 30, 80)),
            "insurance": make_photo((30, 150, 140)),
            "portrait": make_photo((190, 80, 150)),
        }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pd-issue30-patched-")
        self.core = FakeCore(os.path.join(self.temp.name, "synthetic.sqlite"))
        self.app = Flask("pd_issue30_synthetic_actual_routes")
        self.app.config["TESTING"] = True
        self.app.add_url_rule("/api/me", endpoint="me",
                              view_func=lambda: jsonify(ok=True))
        self.current_user = 1001

        # pd_languages module is not relevant to registration; avoid importing
        # live site state when executing the in-memory isolated source.
        lang = types.ModuleType("pd_languages")
        lang.language = lambda: "ru"
        lang.response_for = lambda content, language: content
        old_lang = sys.modules.get("pd_languages")
        sys.modules["pd_languages"] = lang
        try:
            module = types.ModuleType("pd_onboarding_synthetic_live_patch")
            module.__file__ = __file__  # synthetic local path; no deployed file access
            exec(compile(self.patched_source, "<verified-live-in-memory>", "exec"),
                 module.__dict__)
            self.onboarding = module
            def trusted_auth():
                return self.current_user, {}
            module.register(self.app, self.core, trusted_auth)
        finally:
            if old_lang is None:
                sys.modules.pop("pd_languages", None)
            else:
                sys.modules["pd_languages"] = old_lang

        # No migration touches real DB; only the temporary synthetic file.
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("CREATE TABLE IF NOT EXISTS pd_document_reviews ("
                      "telegram_id INTEGER NOT NULL,side TEXT NOT NULL,"
                      "status TEXT NOT NULL,content_sha256 TEXT NOT NULL,"
                      "reviewer_id INTEGER NOT NULL,reviewed_at TEXT NOT NULL,"
                      "reason TEXT NOT NULL DEFAULT '',"
                      "PRIMARY KEY(telegram_id,side))")
            c.execute("CREATE TABLE IF NOT EXISTS pd_document_review_events ("
                      "id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,"
                      "side TEXT NOT NULL,decision TEXT NOT NULL,"
                      "content_sha256 TEXT NOT NULL,reviewer_id INTEGER NOT NULL,"
                      "reviewed_at TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '')")

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, stage, sides):
        import json
        fields = {
            "name": "Synthetic Pilot", "phone": "+37060000000",
            "city": "Vilnius", "vehicle": "Synthetic Vehicle",
            "vehicle_year": 2020, "plate": "TST123", "seats": 4,
        }
        return dict(
            application=json.dumps(fields),
            **{side: (io.BytesIO(self.doc_images[side]), side + ".jpg")
               for side in sides}
        )

    def submit(self, stage, sides):
        with self.app.test_client() as client:
            return client.post("/api/driver/application",
                               data=self.payload(stage, sides))

    def admin_approve(self):
        self.current_user = 9001
        try:
            with self.app.test_client() as client:
                return client.post("/api/admin/driver-applications/1001/decision",
                                   json={"status": "approved"})
        finally:
            self.current_user = 1001

    def status(self):
        with self.core.db(self.core.USERS_DB) as c:
            row = c.execute("SELECT status,stage FROM pd_driver_applications "
                            "WHERE telegram_id=1001").fetchone()
            return (row[0], row[1]) if row else None

    def image(self, side):
        with self.core.db(self.core.USERS_DB) as c:
            r = c.execute("SELECT image FROM pd_driver_documents "
                          "WHERE telegram_id=1001 AND side=?", (side,)).fetchone()
            return bytes(r[0]) if r else None

    def test_full_real_routes_two_stage_flow(self):
        self.assertEqual(self.submit(1, ("license_front", "license_back",
                      "car_front","car_rear","car_interior")).status_code, 200)
        self.assertEqual(self.status(), ("pending", 1))
        self.assertEqual(self.admin_approve().status_code, 200)
        self.assertEqual(self.status(), ("stage2", 1))
        self.assertEqual(self.submit(2, ("registration_front","ltsa",
                      "activity","insurance","portrait")).status_code, 200)
        self.assertEqual(self.status(), ("pending", 2))
        self.assertEqual(self.admin_approve().status_code, 200)
        self.assertEqual(self.status(), ("approved", 2))

    def test_pilot_cannot_replace_previous_stage_documents(self):
        self.submit(1, ("license_front","license_back",
                        "car_front","car_rear","car_interior"))
        self.admin_approve()
        original = self.image("license_front")
        # Stage 2 can receive legacy stage-1 photo fields, but must reject.
        with self.assertRaises((ValueError, Exception)):
            self.submit(2, ("license_front","registration_front",
                            "ltsa","activity","insurance","portrait"))
        self.assertEqual(self.image("license_front"), original)
        self.assertEqual(self.status(), ("stage2",1))

    def test_submission_rolls_back_when_required_photo_missing(self):
        with self.assertRaises(ValueError):
            self.submit(1, ("license_front","license_back","car_front","car_rear"))
        self.assertIsNone(self.status())
        self.assertIsNone(self.image("license_front"))

    def test_stage1_pending_resubmit_cannot_replace_photos(self):
        self.submit(1, ("license_front","license_back",
                        "car_front","car_rear","car_interior"))
        before = self.image("license_front")
        with self.assertRaises(ValueError):
            self.submit(1, ("license_front","license_back",
                            "car_front","car_rear","car_interior"))
        self.assertEqual(self.image("license_front"),before)
        self.assertEqual(self.status(), ("pending",1))

    def test_unauthorized_dispatcher_cannot_approve(self):
        self.submit(1, ("license_front","license_back",
                        "car_front","car_rear","car_interior"))
        with self.app.test_client() as client:
            with self.assertRaises(PermissionError):
                client.post("/api/admin/driver-applications/1001/decision",
                            json={"status":"approved"})
        self.assertEqual(self.status(), ("pending",1))

    def test_stale_stage_change_blocks_commit(self):
        self.submit(1, ("license_front","license_back",
                        "car_front","car_rear","car_interior"))
        self.admin_approve()
        with self.assertRaises(ValueError):
            self.submit(2, ("registration_front",))
        self.assertEqual(self.status(), ("stage2",1))

    def test_patch_rejects_unknown_live_source(self):
        with self.assertRaises(patcher.PatchMismatch):
            patcher.patch_source(self.original_source.encode() + b"\n# unexpected change")

    def test_original_routes_preserved(self):
        registered = {str(rule) for rule in self.app.url_map.iter_rules()}
        for route in (
            "/api/driver/application",
            "/api/admin/driver-applications",
            "/api/admin/driver-applications/<int:applicant>/decision",
            "/api/driver/documents/<int:applicant>/<side>",
        ):
            self.assertIn(route, registered)

if __name__ == "__main__":
    unittest.main()
