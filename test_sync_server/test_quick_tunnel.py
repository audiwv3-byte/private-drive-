"""Offline checks of test-tunnel safety gates; NEVER starts cloudflared."""
import unittest
from run_quick_tunnel import URL_PATTERN, require_explicit_opt_in, MAX_SECONDS, choose_port


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

    def test_temporary_random_cloudflare_url_pattern(self):
        self.assertEqual(URL_PATTERN.search(
            "INF quick tunnel URL: https://quiet-garden-123.trycloudflare.com ready"
        ).group(), "https://quiet-garden-123.trycloudflare.com")
        self.assertIsNone(URL_PATTERN.search("https://example.com"))
        self.assertLessEqual(MAX_SECONDS, 30 * 60)

    def test_local_ephemeral_port(self):
        port = choose_port()
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)


if __name__ == "__main__":
    unittest.main()
