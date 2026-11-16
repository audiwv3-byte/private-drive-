"""Issue #30: synthetic Flask + independent SQLite connections, no production API."""
import hashlib
import io
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request
import pd_document_review as review
import pd_issue30_document_storage_guard as storage
import pd_issue30_flask_integration as integration

PILOT = 1001
ADMIN = 9001
BEFORE = b"synthetic initial document"
AFTER = b"synthetic changed document"


class FakeCore:
    USERS_DB = "synthetic.db"

    def __init__(self, path):
        self.path = path

    @contextmanager
    def db(self, _):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.execute("PRAGMA busy_timeout=10000")
        try:
            yield c
        finally:
            c.close()

    def is_admin(self, uid):
        return uid == ADMIN


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="issue30-synthetic-")
        self.path = os.path.join(self.temp.name, "fake.sqlite")
        self.core = FakeCore(self.path)
        with self.core.db(self.core.USERS_DB) as c:
            c.executescript("""
            CREATE TABLE pd_driver_applications (
              telegram_id INTEGER PRIMARY KEY, status TEXT NOT NULL, stage INTEGER NOT NULL);
            CREATE TABLE pd_driver_documents (
              telegram_id INTEGER NOT NULL, side TEXT NOT NULL, image BLOB NOT NULL,
              updated_at TEXT NOT NULL, PRIMARY KEY(telegram_id, side));
            INSERT INTO pd_driver_applications VALUES (1001,'pending',1);
            """)
            review.ensure_tables(c)
            storage.ensure_tables(c)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        def auth():
            # Test-only fake authentication. Production must use Telegram auth.
            return int(request.headers.get("X-Synthetic-User", "1001")), None
        integration.register_offline_routes(
            self.app, self.core, auth, lambda b:b, allow_synthetic=True
        )

    def tearDown(self):
        self.temp.cleanup()

    def pilot(self, side="license_front", image=BEFORE, uid=PILOT):
        with self.app.test_client() as client:
            return client.post("/api/driver/application/documents/" + side,
                               data={"image": (io.BytesIO(image), "synthetic.jpg")},
                               headers={"X-Synthetic-User":str(uid)})

    def dispatcher(self, *, applicant=PILOT, side="license_front",
                   image=AFTER, expected=None, uid=ADMIN):
        if expected is None:
            expected=hashlib.sha256(BEFORE).hexdigest()
        with self.app.test_client() as client:
            return client.post(
                f"/api/admin/driver-applications/{applicant}/documents/{side}/replace",
                data={"image":(io.BytesIO(image),"synthetic.jpg"),
                      "expected_sha256":expected},
                headers={"X-Synthetic-User":str(uid)})

    def read(self, side="license_front"):
        with self.core.db(self.core.USERS_DB) as c:
            r=c.execute("SELECT image FROM pd_driver_documents "
                        "WHERE telegram_id=? AND side=?",(PILOT,side)).fetchone()
            audit=c.execute("SELECT COUNT(*) FROM pd_document_replacements").fetchone()[0]
            app=c.execute("SELECT status,stage FROM pd_driver_applications "
                          "WHERE telegram_id=?",(PILOT,)).fetchone()
            return (r[0] if r else None),audit,app

    def test_initial_upload_and_impossible_second_upload(self):
        self.assertEqual(self.pilot().status_code,201)
        self.assertEqual(self.pilot(image=AFTER).status_code,409)
        self.assertEqual(self.read()[0],BEFORE)

    def test_unauthorized_dispatcher_cannot_modify(self):
        self.pilot()
        self.assertEqual(self.dispatcher(uid=PILOT).status_code,403)
        self.assertEqual(self.read()[:2],(BEFORE,0))

    def test_authorized_dispatcher_replace_and_pending(self):
        self.pilot()
        with self.core.db(self.core.USERS_DB) as c:
            review.decide(c, applicant=PILOT,side="license_front",
                          action="approved",reviewer_id=ADMIN,
                          expected_sha256=hashlib.sha256(BEFORE).hexdigest())
        res=self.dispatcher()
        self.assertEqual(res.status_code,200)
        self.assertEqual(res.json["status"],"pending")
        self.assertEqual(self.read()[:2],(AFTER,1))
        with self.core.db(self.core.USERS_DB) as c:
            self.assertEqual(review.states(c,PILOT)["license_front"]["status"],"pending")

    def test_stale_sha_no_write_or_audit(self):
        self.pilot()
        result=self.dispatcher(expected="0"*64)
        self.assertEqual(result.status_code,409)
        self.assertEqual(self.read()[:2],(BEFORE,0))

    def test_admin_cannot_change_approved_applicant(self):
        self.pilot()
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("UPDATE pd_driver_applications SET status='approved'")
        self.assertEqual(self.dispatcher().status_code,409)
        self.assertEqual(self.read()[:2],(BEFORE,0))

    def test_pilot_cannot_change_stage1_document_in_stage2(self):
        self.pilot()
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("UPDATE pd_driver_applications SET stage=2,status='pending'")
        self.assertEqual(self.pilot(image=AFTER).status_code,409)
        self.assertEqual(self.pilot("insurance",b"fake insurance").status_code,201)

    def test_missing_file_and_bad_lease(self):
        self.assertEqual(self.dispatcher().status_code,409)
        self.pilot()
        self.assertEqual(self.dispatcher(expected="not-a-sha").status_code,409)

    def test_legacy_upsert_is_explicit_installation_blocker(self):
        unsafe=("INSERT INTO pd_driver_documents(telegram_id,side,image,updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(telegram_id,side) "
                "DO UPDATE SET image=excluded.image")
        with self.assertRaises(RuntimeError):
            integration.assert_no_legacy_upsert(unsafe)
        self.assertTrue(integration.assert_no_legacy_upsert(
            "INSERT INTO pd_driver_documents VALUES(?,?,?,?) "
            "ON CONFLICT(telegram_id,side) DO NOTHING"))

    def test_cannot_register_on_non_test_app(self):
        app = Flask("production-disallowed")
        with self.assertRaises(RuntimeError):
            integration.register_offline_routes(
                app,self.core,lambda:(ADMIN,None),lambda b:b,
                allow_synthetic=True)

    def test_concurrent_pilot_uploads_only_one_wins(self):
        barrier=threading.Barrier(2)
        def writer(i):
            barrier.wait(timeout=4)
            return self.pilot(image=b"synthetic concurrent " + bytes([i])).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1=pool.submit(writer,1)
            f2=pool.submit(writer,2)
            codes=sorted((f1.result(timeout=8),f2.result(timeout=8)))
        self.assertEqual(codes,[201,409])
        self.assertEqual(self.read()[1],0)

    def test_competing_dispatcher_replacements_stale_loser(self):
        self.pilot()
        barrier=threading.Barrier(2)
        digest=hashlib.sha256(BEFORE).hexdigest()
        def writer(i):
            barrier.wait(timeout=4)
            return self.dispatcher(image=b"synthetic new " + bytes([i]),
                                   expected=digest).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1=pool.submit(writer,1)
            f2=pool.submit(writer,2)
            codes=sorted((f1.result(timeout=8),f2.result(timeout=8)))
        self.assertEqual(codes,[200,409])
        self.assertEqual(self.read()[1],1)

    def test_rollback_on_failed_audit_through_flask(self):
        self.pilot()
        with self.core.db(self.core.USERS_DB) as c:
            c.execute("CREATE TRIGGER simulate_fail BEFORE INSERT ON "
                      "pd_document_replacements BEGIN "
                      "SELECT RAISE(ABORT,'synthetic audit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.dispatcher()
        self.assertEqual(self.read()[:2],(BEFORE,0))


if __name__ == "__main__":
    unittest.main()
