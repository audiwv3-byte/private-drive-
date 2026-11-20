"""Offline safeguards for isolated corporate preview build."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from build_corporate_preview import build, FILES, validate_source

class CorporatePreviewBuildTests(unittest.TestCase):
    def test_source_is_static_and_links_are_allowlisted(self):
        self.assertEqual(validate_source(), set(FILES))

    def test_preview_has_no_app_or_registration_runtime(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "release"
            archive = build(root)
            self.assertTrue(archive.exists())
            with zipfile.ZipFile(archive) as z:
                names = set(z.namelist())
                self.assertEqual(names,set(FILES)|{"_headers","robots.txt","AUDIT.json"})
                for forbidden in ("registration.html","registration-client.mjs",
                                  "private-test-bootstrap.js","compare.html","preview.html",
                                  "main.dart.js","netlify.toml"):
                    self.assertNotIn(forbidden,names)
                audit=json.loads(z.read("AUDIT.json"))
                self.assertFalse(audit["publicly_hosted"])
                self.assertTrue(audit["auth_required_before_https_deployment"])
                for name, digest in audit["files_sha256"].items():
                    self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),digest)
                self.assertIn(b"noindex,nofollow,noarchive",z.read("index.html"))
                self.assertIn(b"form-action 'none'",z.read("_headers"))
                self.assertIn(b"Disallow: /",z.read("robots.txt"))
                for html_name in [name for name in names if name.endswith(".html")]:
                    html=z.read(html_name)
                    self.assertNotIn(b"<form",html)
                    self.assertNotIn(b"<script",html)
                    self.assertIn("ИЗОЛИРОВАННЫЙ ПРЕДПРОСМОТР".encode(),html)

if __name__=="__main__":
    unittest.main()
