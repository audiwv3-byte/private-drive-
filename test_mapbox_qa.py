"""Offline Mapbox QA: no real token, network, Render or production access."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class MapboxQaTests(unittest.TestCase):
    def test_order_page_loads_public_then_optional_local_config(self):
        html = (ROOT / "site_preview/order-map.html").read_text(encoding="utf-8")
        public = '<script src="assets/mapbox-config.js"></script>'
        local = '<script src="assets/mapbox-local-config.js"></script>'
        self.assertEqual(html.count(public), 1)
        self.assertEqual(html.count(local), 1)
        self.assertLess(html.index(public), html.index(local))
        self.assertLess(html.index(local), html.index("const token=window.PD_MAPBOX_PUBLIC_TOKEN"))
        self.assertIn("https://api.mapbox.com/styles/v1/mapbox/", html)

    def test_local_override_is_git_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("site_preview/assets/mapbox-local-config.js", ignored)
        self.assertFalse((ROOT / "site_preview/assets/mapbox-local-config.js").exists(),
                         "Local Mapbox config must never be committed")

    def test_committed_browser_config_has_no_token(self):
        config = (ROOT / "site_preview/assets/mapbox-config.js").read_text(encoding="utf-8")
        self.assertEqual(config.strip(), 'window.PD_MAPBOX_PUBLIC_TOKEN = "";')

    def test_local_setup_rejects_secret_tokens(self):
        script = (ROOT / "ops/setup-local-mapbox.ps1").read_text(encoding="utf-8")
        self.assertIn("git check-ignore -q", script)
        self.assertIn("git ls-files", script)
        self.assertIn("Read-Host -AsSecureString", script)
        self.assertIn("http://localhost:5500", script)
        self.assertNotIn("http://127.0.0.1:5500", script)
        self.assertIn("if ($token -notmatch '^pk\\.", script)

    def test_render_generator_only_accepts_public_tokens(self):
        code = (ROOT / "build_website_map_config.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "site_preview/assets").mkdir(parents=True)
            (base / "build_website_map_config.py").write_text(code, encoding="utf-8")
            target = base / "site_preview/assets/mapbox-config.js"

            def run(token):
                env = dict(os.environ, MAPBOX_WEB_PUBLIC_TOKEN=token)
                return subprocess.run(
                    [sys.executable, str(base / "build_website_map_config.py")],
                    cwd=base, env=env, capture_output=True, text=True, timeout=10,
                )

            blank = run("")
            self.assertEqual(blank.returncode, 0, blank.stderr)
            self.assertEqual(target.read_text(encoding="utf-8").strip(),
                             'window.PD_MAPBOX_PUBLIC_TOKEN = "";')

            sample = "pk.testing_public_token_123456"
            valid = run(sample)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(target.read_text(encoding="utf-8").strip(),
                             "window.PD_MAPBOX_PUBLIC_TOKEN = " + json.dumps(sample) + ";")

            forbidden = run("sk.must_not_be_used")
            self.assertNotEqual(forbidden.returncode, 0)
            self.assertNotIn(forbidden.args[-1] if isinstance(forbidden.args[-1], str)
                             else "UNLIKELY", forbidden.stdout)
            self.assertEqual(target.read_text(encoding="utf-8").strip(),
                             "window.PD_MAPBOX_PUBLIC_TOKEN = " + json.dumps(sample) + ";")


if __name__ == "__main__":
    unittest.main(verbosity=2)
