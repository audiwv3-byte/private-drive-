"""Offline checks of test-tunnel safety gates; NEVER starts cloudflared."""
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from pd_demo_server import ApiServer, DemoStore
from run_quick_tunnel import (URL_PATTERN, require_explicit_opt_in,
    MAX_SECONDS, SAFARI_PREVIEW_ORIGIN, choose_port, seed_synthetic_chat_trip)


class QuickTunnelSafetyTests(unittest.TestCase):
    def test_tunnel_is_off_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "explicitly"):
            require_explicit_opt_in({}, find_executable=lambda _: "/fake/cloudflared")

    def test_requires_official_cloudflared_binary(self):
        with self.assertRaisesRegex(RuntimeError, "cloudflared"):
            require_explicit_opt_in({"PD_DEMO_PUBLIC_TUNNEL": "YES"},
                                    find_executable=lambda _: None)

    def test_refuses_existing_tokens_even_if_opted_in(self):
        with self.assertRaisesRegex(RuntimeError, "pre-existing"):
            require_explicit_opt_in(
                {"PD_DEMO_PUBLIC_TUNNEL": "YES",
                 "PD_DEMO_PILOT_TOKEN": "example-stale-test-token"},
                find_executable=lambda _: "/fake/cloudflared")

    def test_accepts_only_intended_opt_in(self):
        self.assertEqual(require_explicit_opt_in(
            {"PD_DEMO_PUBLIC_TUNNEL": "YES"},
            find_executable=lambda _: "/fake/cloudflared"), "/fake/cloudflared")

    def test_browser_origin_only_allows_existing_safari_netlify_preview(self):
        self.assertEqual(SAFARI_PREVIEW_ORIGIN,
                         "https://luxury-mochi-84e459.netlify.app")
        self.assertEqual(require_explicit_opt_in({
            "PD_DEMO_PUBLIC_TUNNEL": "YES",
            "PD_DEMO_BROWSER_ORIGIN": SAFARI_PREVIEW_ORIGIN,
        }, find_executable=lambda _: "/fake/cloudflared"), "/fake/cloudflared")
        for origin in ("https://evil.example",
                       "http://luxury-mochi-84e459.netlify.app",
                       "https://luxury-mochi-84e459.netlify.app.evil.example"):
            with self.subTest(origin=origin):
                with self.assertRaisesRegex(RuntimeError, "Browser origin"):
                    require_explicit_opt_in({
                        "PD_DEMO_PUBLIC_TUNNEL": "YES",
                        "PD_DEMO_BROWSER_ORIGIN": origin,
                    }, find_executable=lambda _: "/fake/cloudflared")

    def test_temporary_random_cloudflare_url_pattern(self):
        self.assertEqual(URL_PATTERN.search(
            "INF quick tunnel URL: https://quiet-garden-123.trycloudflare.com ready"
        ).group(), "https://quiet-garden-123.trycloudflare.com")
        self.assertIsNone(URL_PATTERN.search("https://example.com"))
        self.assertLessEqual(MAX_SECONDS, 30 * 60)

    def test_quick_tunnel_preseeds_chat_for_both_role_sessions(self):
        # This test starts a loopback-only server, never Cloudflare or production.
        tokens = {"passenger": "p" * 40, "pilot": "d" * 40,
                  "dispatcher": "a" * 40}
        credentials = {
            hashlib.sha256(token.encode()).digest(): (role, role + "_test")
            for role, token in tokens.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            store = DemoStore(str(Path(directory) / "test.sqlite"))
            server = ApiServer(("127.0.0.1", 0), store, credentials)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                trip_id = seed_synthetic_chat_trip(server.server_port, tokens)
                passenger_trip = store.get(trip_id, "passenger", "passenger_test")
                pilot_trip = store.get(trip_id, "pilot", "pilot_test")
                self.assertEqual(passenger_trip["status"], "assigned")
                self.assertEqual(passenger_trip["id"], pilot_trip["id"])
                self.assertEqual(pilot_trip["pilot"], "pilot_test")
                self.assertEqual(store.messages(trip_id, "passenger",
                                                "passenger_test", 0), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                store.close()

    def test_local_ephemeral_port(self):
        port = choose_port()
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)


if __name__ == "__main__":
    unittest.main()
