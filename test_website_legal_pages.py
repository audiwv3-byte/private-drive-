"""Offline guardrails for the corporate legal drafts. No live API or payments."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent / "site_preview"

class LegalParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.forms = 0
        self.lang = ""
        self.titles = 0
        self.ids = set()
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="html": self.lang=a.get("lang","")
        if tag=="a": self.links.append(a.get("href",""))
        if tag=="form": self.forms+=1
        if tag=="h1": self.titles+=1
        if "id" in a: self.ids.add(a["id"])

class CorporateLegalTests(unittest.TestCase):
    def page(self, filename):
        content=(ROOT / filename).read_text(encoding="utf-8")
        p=LegalParser()
        p.feed(content)
        self.assertEqual(p.lang,"ru")
        self.assertEqual(p.titles,1)
        self.assertEqual(p.forms,0)
        self.assertIn("index.html",p.links)
        for name in ("privacy.html","terms.html","pilot-privacy.html"):
            self.assertIn(name,p.links)
        for href in p.links:
            if href.startswith(("http://","https://")):
                self.assertTrue(href.startswith(("https://wilsonpark.pythonanywhere.com/","https://vdai.lrv.lt/")),href)
            elif href.startswith("mailto:"):
                self.assertTrue(href.startswith("mailto:eurobaltictransfer@gmail.com"))
            else:
                self.assertTrue((ROOT / href).is_file(),href)
        self.assertNotIn("<script",content)
        self.assertNotIn("type=\"submit\"",content)
        return content

    def test_corporate_privacy_is_narrow_and_preserves_gdpr_rights(self):
        s=self.page("privacy.html")
        for required in (
            "Yauheni Ivantsou", "eurobaltictransfer@gmail.com",
            "статья 6(1)(b)", "статья 6(1)(f)", "статья 6(1)(c)",
            "права", "доступ", "исправление", "удаление", "возразить",
            "в течение месяца", "VDAI", "не содержит формы регистрации",
            "https://wilsonpark.pythonanywhere.com/privacy?lang=ru",
        ):
            self.assertIn(required,s)

    def test_terms_retain_passenger_protections_and_no_live_payment(self):
        s=self.page("terms.html")
        for required in (
            "не принимает платежи", "не списывает средства", "не означает автоматически принятый заказ",
            "возврату", "обязательных прав пассажира",
            "не устанавливает штраф", "20% после пяти минут",
            "не устанавливает право автоматически удерживать 80%",
            "https://wilsonpark.pythonanywhere.com/legal?lang=ru",
            "не меняет и не отменяет",
        ):
            self.assertIn(required,s)
        self.assertNotIn("checkout.stripe.com",s)

    def test_pilot_is_unapproved_draft_and_disallows_document_collection(self):
        s=self.page("pilot-privacy.html")
        for required in (
            "Не утверждена", "не включаются", "паспорт", "правовые основания",
            "сроки хранения", "VDAI", "публичная регистрация пилотов не включена",
            "не дают права выполнять поездки", "статья 6(1)(b)",
        ):
            self.assertIn(required,s)
        self.assertNotIn("<input",s)

    def test_home_links_to_all_three_documents_without_live_pilot_signup(self):
        home=(ROOT / "index.html").read_text(encoding="utf-8")
        for p in ("privacy.html","terms.html","pilot-privacy.html"):
            self.assertIn('href="'+p+'"',home)
        self.assertNotIn('href="registration.html"',home)
        for name in ("privacy.html", "terms.html", "pilot-privacy.html"):
            self.assertIn('href="' + name + '" target="_blank" rel="noopener noreferrer"', home)
        self.assertIn('id="contact"',home)
        self.assertIn("Запросить поездку",home)
        self.assertIn("пока недоступна",home)

if __name__=="__main__":
    unittest.main()
