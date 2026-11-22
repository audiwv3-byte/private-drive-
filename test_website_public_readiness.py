"""Read-only, offline release checks for PRIVATE DRIVE corporate website."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
import re
import unittest

ROOT = Path(__file__).resolve().parent / "site_preview"
PAGE = ROOT / "index.html"

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.images, self.ids = [], [], set()
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.add(d["id"])
        if tag == "a" and "href" in d:
            self.links.append(d["href"])
        if tag == "img" and "src" in d:
            self.images.append(d["src"])

class WebsiteReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = PAGE.read_text(encoding="utf-8")
        cls.parser = LinkParser()
        cls.parser.feed(cls.content)

    def test_navigation_targets_and_image(self):
        p = self.parser
        for target in ("top", "taxi", "transfers", "extras", "registration", "documents", "contact"):
            self.assertIn(target,p.ids)
        for href in p.links:
            if href.startswith("#"):
                self.assertIn(href[1:],p.ids,href)
            elif href.startswith("mailto:"):
                self.assertIn("eurobaltictransfer@gmail.com",href)
            elif href in ("privacy.html", "terms.html", "pilot-privacy.html"):
                self.assertTrue((ROOT / href).is_file(), href)
            elif href == "https://t.me/PrivateDraive":
                continue
            else:
                u=urlparse(href)
                self.assertEqual(u.scheme,"https")
                self.assertEqual(u.hostname,"wilsonpark.pythonanywhere.com")
                self.assertIn(u.path,("/privacy","/legal"))
        for src in p.images:
            self.assertTrue((ROOT / src).is_file(),src)

    def test_correct_fares_and_no_unapproved_discounts(self):
        for line in ("130 €","200 €","40 €","+15 €","0,66 € / км","0,79 € / км","предварительный заказ +3 €"):
            self.assertIn(line,self.content)
        self.assertNotIn("110 €",self.content)
        self.assertNotIn("10%",self.content)

    def test_no_false_registration_or_live_order_claims(self):
        self.assertNotIn("ТЕСТОВЫЙ МАКЕТ",self.content)
        self.assertNotIn("Дизайн для согласования",self.content)
        self.assertIn("https://t.me/PrivateDraive",self.parser.links)
        self.assertNotIn("https://t.me/EuroBalticTransferBot",self.parser.links)
        self.assertNotIn("site_preview/registration.html",self.content)
        self.assertIn("пока недоступна",self.content)
        self.assertIn("не принимает онлайн-заказы и оплату",self.content)

    def test_legal_links_exist_in_source_templates(self):
        # Source templates exist; live URL availability and accuracy require manual review.
        for target in ("privacy.html", "terms.html", "pilot-privacy.html"):
            self.assertIn(target, self.parser.links)
        # Source documents stay in place; corporate pages reference the authoritative URLs.
        self.assertIn("https://wilsonpark.pythonanywhere.com/privacy?lang=ru", (ROOT / "privacy.html").read_text())
        self.assertIn("https://wilsonpark.pythonanywhere.com/legal?lang=ru", (ROOT / "terms.html").read_text())
        for name in ("privacy_ru.html","legal_ru.html"):
            self.assertTrue((ROOT.parent / "miniapp" / "templates" / name).exists())

if __name__ == "__main__":
    unittest.main()
