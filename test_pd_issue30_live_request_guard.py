"""GET-only deployed request guard contract tests in synthetic Flask.

The exact live pd_request_security.py source is fetched for SHA comparison,
patched ONLY IN MEMORY and registered on an in-memory Flask app. No production
URLs are called by the test client, no real users/documents/DB are touched.
"""
import hashlib
import os
import types
import unittest
from urllib.parse import quote
import requests
from flask import Flask, jsonify

import pd_issue30_patch_live_request_guard_offline as patch

SOURCE="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/pd_request_security.py"

class RequestGuardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token=os.environ.get("PA_API_TOKEN","").strip()
        if not token: raise RuntimeError("GET-only token unavailable")
        url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(SOURCE,safe="/")
        r=requests.get(url,headers={"Authorization":"Token "+token},timeout=35)
        r.raise_for_status()
        cls.original=r.content
        cls.patched=patch.patch_source(r.content)
    def setUp(self):
        self.app=Flask("issue30_request_guard_synthetic")
        self.app.config["TESTING"]=True
        namespace={"__name__":"issue30_request_guard_synthetic"}
        exec(compile(self.patched,"<verified-patched-guard>", "exec"),namespace)
        namespace["register_request_guard"](self.app)
        @self.app.post("/api/admin/driver-applications/<int:applicant>/documents/<side>/replace")
        def fake_replace(applicant, side):
            return jsonify(applicant=applicant,side=side)
        @self.app.post("/api/driver/application")
        def fake_registration():
            return jsonify(route="pilot")
        @self.app.post("/api/admin/driver-applications/<int:applicant>/document-reviews/<side>")
        def fake_review(applicant,side):
            return jsonify(status="review accepted")
        @self.app.post("/api/admin/other")
        def fake_other():
            return jsonify(route="other")
        @self.app.post("/api/stripe/webhook")
        def fake_webhook():
            return jsonify(route="stripe")

    def test_source_sha_pinned(self):
        self.assertEqual(hashlib.sha256(self.original).hexdigest(),patch.EXPECTED_SHA256)
    def test_only_exact_admin_replacement_multipart_allowed(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/driver-applications/1001/documents/license_front/replace",
                          data={"license_front":( __import__("io").BytesIO(b"fake only"),"synthetic.jpg")})
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.json["side"],"license_front")
    def test_other_admin_multipart_denied(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/other",data={"x":(__import__("io").BytesIO(b"x"),"x.jpg")})
            self.assertEqual(r.status_code,415)
    def test_unknown_side_multipart_denied(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/driver-applications/1001/documents/other/replace",
                          data={"other":(__import__("io").BytesIO(b"fake"),"fake.jpg")})
            self.assertEqual(r.status_code,415)
    def test_no_broad_applicant_match(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/driver-applications/0/documents/license_front/replace",
                          data={"license_front":(__import__("io").BytesIO(b"fake"),"fake.jpg")})
            self.assertEqual(r.status_code,415)
    def test_pilot_multipart_legacy_behavior_retained(self):
        with self.app.test_client() as client:
            r=client.post("/api/driver/application",data={"license_front":(__import__("io").BytesIO(b"synthetic"),"fake.jpg")})
            self.assertEqual(r.status_code,200)
    def test_admin_json_review_retained(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/driver-applications/1001/document-reviews/license_front",
                          json={"status":"approved","sha256":"a"*64})
            self.assertEqual(r.status_code,200)
    def test_admin_json_array_still_rejected(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/driver-applications/1001/document-reviews/license_front",json=[1])
            self.assertEqual(r.status_code,400)
    def test_missing_content_type_rejected(self):
        with self.app.test_client() as client:
            r=client.post("/api/admin/driver-applications/1001/documents/license_front/replace",data=b"raw")
            self.assertEqual(r.status_code,415)
    def test_stripe_signed_raw_body_exemption_preserved(self):
        with self.app.test_client() as client:
            r=client.post("/api/stripe/webhook",data=b"raw webhook")
            self.assertEqual(r.status_code,200)
    def test_changed_source_fails_closed(self):
        with self.assertRaises(patch.RequestGuardPatchMismatch):
            patch.patch_source(self.original+b"\n# altered")
if __name__=="__main__":
    unittest.main()
