"""Issue #30 HTML patch — private GET source, synthetic parse assertions."""
import os
import unittest
from urllib.parse import quote
import requests
import pd_issue30_patch_live_admin_html_offline as patch

class HtmlAdminIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token="".join(os.environ.get("PA_API_TOKEN","").strip().split())
        if not token:raise RuntimeError("No GET-only source credentials")
        path="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/miniapp/templates/index.html"
        url="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path"+quote(path,safe="/")
        response=requests.get(url,headers={"Authorization":"Token "+token},timeout=35)
        response.raise_for_status()
        cls.raw=response.content
        cls.patched=patch.patch_source(cls.raw)

    def test_document_review_metadata_is_checked_before_admin_approval(self):
        self.assertIn("pdDocsApproved=pdRequired.every",self.patched)
        self.assertIn("a.status==='stage2'||!pdDocsApproved",self.patched)

    def test_per_pilot_document_review_button_and_mount(self):
        self.assertIn("reviewButton.textContent=pdL('Проверить документы')",self.patched)
        self.assertIn("mod.mountIssue30Review(panel,Number(a.telegram_id)",self.patched)
        self.assertIn("window.Telegram?.WebApp?.initData",self.patched)

    def test_original_order_and_other_functions_retained(self):
        source=self.raw.decode("utf-8")
        self.assertEqual(source.count("async function pdLoadDriverApplications(){"),1)
        self.assertEqual(self.patched.count("async function pdLoadDriverApplications(){"),1)
        self.assertIn("async function pdLoadDriverApplications(){",self.patched)
        self.assertIn("pdStage2ApprovalHint",self.patched)
        self.assertIn("area.append(row)",self.patched)

    def test_responsive_stylesheet_is_wired_into_patched_html(self):
        self.assertEqual(self.patched.count('/static/pd_issue30_admin_review.css'), 1)
        self.assertIn('<link rel="stylesheet" href="/static/pd_issue30_admin_review.css">', self.patched)

    def test_changed_live_html_rejected(self):
        with self.assertRaises(patch.HtmlPatchMismatch):
            patch.patch_source(self.raw+b"\n<!-- unexpected -->")

    def test_patch_is_not_reapplied(self):
        with self.assertRaises(patch.HtmlPatchMismatch):
            patch.patch_source(self.patched.encode())

if __name__=="__main__":unittest.main()
