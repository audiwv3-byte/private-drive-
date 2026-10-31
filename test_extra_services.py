"""Без обращения к продакшену: тесты дополнительных услуг PRIVATE DRIVE."""
import unittest
from decimal import Decimal
from pd_extra_services import breakdown


class ExtraServicesTests(unittest.TestCase):
    def test_base_unchanged(self):
        self.assertEqual(breakdown("40.00", {})["total"], "40.00")

    def test_meeting_fixed_twenty(self):
        r = breakdown("40.00", {"extras":["Встреча с табличкой"]})
        self.assertEqual(r["meeting"], "20.00")
        self.assertEqual(r["total"], "60.00")

    def test_sober_doubles_route_base(self):
        r = breakdown("40.00", {"extras":["Трезвый водитель"]})
        self.assertEqual(r["sober"], "40.00")
        self.assertEqual(r["total"], "80.00")

    def test_both_services(self):
        self.assertEqual(
            breakdown("40.00", {"extras":["Трезвый водитель", "Встреча с табличкой"]})["total"],
            "100.00"
        )

    def test_pet_and_two_new_services(self):
        r = breakdown("40.00", {"extras":["Перевозка животного","Трезвый водитель","Встреча с табличкой"]})
        self.assertEqual(r["pet"], "4.00")
        self.assertEqual(r["total"], "104.00")

    def test_untrusted_input_rejected(self):
        for invalid in (None, "oops", ["x"], {"extras":"Встреча с табличкой"},
                        {"extras":[None]}, {"extras":["x"]*11}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                breakdown("25.00", invalid)
        for invalid_price in ("NaN", "Infinity", "-1"):
            with self.subTest(price=invalid_price), self.assertRaises(ValueError):
                breakdown(invalid_price, {})


if __name__ == "__main__":
    unittest.main()
