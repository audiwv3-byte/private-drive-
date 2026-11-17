"""GET-only source patch test: WSGI routes are NOT deployed."""
import ast
import hashlib
import os
import unittest
from urllib.parse import quote

import requests
import pd_issue30_patch_live_wsgi_offline as wsgi

class WsgiSourcePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token="".join(os.environ.get("PA_API_TOKEN","").strip().split())
        if not token:
            raise RuntimeError("Read-only source access unavailable")
        path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp_server.py"
        url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(path,safe="/")
        response=requests.get(url,headers={"Authorization":"Token "+token},timeout=35)
        response.raise_for_status()
        cls.raw=response.content
        cls.rewritten=wsgi.patch_source(cls.raw)

    def test_source_fingerprint_precondition(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),wsgi.EXPECTED_SHA256)

    def test_review_route_registration_is_added_after_existing_onboarding(self):
        lines=self.rewritten.splitlines()
        first=lines.index("pd_onboarding.register(app, core, auth)")
        self.assertEqual(lines[first+1],"import pd_issue30_admin_review_routes as pd_issue30_admin_routes")
        self.assertEqual(lines[first+2],
                         "pd_issue30_admin_routes.register(app,core,auth,pd_onboarding.read_photos)")

    def test_existing_wsgi_app_definition_unchanged(self):
        old=ast.parse(self.raw.decode())
        new=ast.parse(self.rewritten)
        def functions(t):
            return sorted(n.name for n in ast.walk(t) if isinstance(n,ast.FunctionDef))
        self.assertEqual(functions(old),functions(new))
        self.assertIn("application = app",self.rewritten)

    def test_changed_source_rejected(self):
        with self.assertRaises(wsgi.WsgiPatchMismatch):
            wsgi.patch_source(self.raw+b"\n# unexpected")
    def test_patch_cannot_apply_twice(self):
        with self.assertRaises(wsgi.WsgiPatchMismatch):
            wsgi.patch_source(self.rewritten.encode())

if __name__=="__main__":
    unittest.main()
