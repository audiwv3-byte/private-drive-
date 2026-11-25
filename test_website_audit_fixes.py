"""Release regression checks; no payment, messages or outbound requests."""
from base64 import b64encode
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import unittest


ROOT = Path(__file__).parent / "site_preview"


class Page(HTMLParser):
    def __init__(self, name):
        super().__init__()
        self.source = (ROOT / name).read_text(encoding="utf-8")
        self.tags = []
        self.feed(self.source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def of(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]


class WebsiteAuditTests(unittest.TestCase):
    def test_leaflet_core_assets_are_local_and_match_the_browser_integrity_check(self):
        p = Page("order-map.html")
        for name, attribute, ext in (("link", "href", "css"), ("script", "src", "js")):
            expected_path = f"assets/vendor/leaflet-1.9.4/leaflet.{ext}"
            asset, = [d for d in p.of(name) if d.get(attribute, "").endswith(f"leaflet.{ext}")]
            self.assertEqual(asset[attribute], expected_path)
            digest = b64encode(sha256((ROOT / expected_path).read_bytes()).digest()).decode()
            self.assertEqual(asset.get("integrity"), f"sha256-{digest}")
        vendor = ROOT / "assets/vendor/leaflet-1.9.4"
        for img in ("layers.png", "layers-2x.png", "marker-icon.png", "marker-icon-2x.png", "marker-shadow.png"):
            self.assertTrue((vendor / "images" / img).is_file())
        self.assertTrue((vendor / "LICENSE").is_file())

    def test_booking_keeps_disclosure_and_preserves_the_existing_form(self):
        p = Page("order-map.html")
        self.assertIn("Отправка через Telegram", p.source)
        self.assertIn("Открыть заявку в Telegram", p.source)
        self.assertIn("https://t.me/PrivateDraive?text=", p.source)
        for key in ("orderForm", "rideDate", "rideTime", "map", "rideComfort", "radioOther", "music"):
            self.assertTrue(any(attrs.get("id") == key for _, attrs in p.tags), key)

    def test_unverified_transfer_data_is_not_published_on_payment_page(self):
        p = Page("payments.html")
        for forbidden in ("data-copy", "wallet-copy", "bc1q", "0x", "IBAN Swedbank", "TIP-PD"):
            self.assertNotIn(forbidden, p.source)
        self.assertIn("На сайте нет списаний", p.source)
        self.assertIn("Запросить платёжную ссылку в Telegram", p.source)
        self.assertIn("https://t.me/PrivateDraive?text=", p.source)

    def test_language_navigation_and_honest_link_to_current_booking(self):
        home, lt = Page("index.html"), Page("lt.html")
        self.assertEqual(lt.of("html")[0]["lang"], "lt")
        self.assertTrue(any(a.get("href") == "lt.html" for a in home.of("a")))
        self.assertTrue(any(a.get("href") == "index.html" for a in lt.of("a")))
        self.assertIn("Atidaryti užsakymo formą (rusų kalba)", lt.source)
        for anchor in lt.of("a"):
            url = urlsplit(anchor["href"])
            if not url.scheme and not url.netloc:
                self.assertTrue((ROOT / url.path).is_file())
