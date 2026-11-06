"""Offline regression contracts for agreed user-facing Mini App behavior."""
from pathlib import Path
import unittest
import pd_fixed_prices

ROOT = Path(__file__).resolve().parent

class MiniAppUiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "miniapp/templates/index.html").read_text(encoding="utf-8")
        cls.runtime = (ROOT / "pd_trip_runtime_v4.js").read_text(encoding="utf-8")
        cls.pilot = (ROOT / "pd_pilot_cabinet_v4.js").read_text(encoding="utf-8")

    def test_fixed_tariff_one_way(self):
        self.assertEqual(pd_fixed_prices.base({
            "origin": "Vilnius, Lithuania",
            "destination": "Kaunas, Lithuania",
            "roundtrip": False,
        }), "130.00")

    def test_fixed_tariff_return(self):
        self.assertEqual(pd_fixed_prices.base({
            "origin": "Вильнюс",
            "destination": "Каунас",
            "roundtrip": True,
        }), "200.00")

    def test_extra_stop_does_not_use_fixed_tariff(self):
        self.assertIsNone(pd_fixed_prices.base({
            "origin": "Vilnius", "destination": "Kaunas",
            "roundtrip": True, "stop_address": "Trakai",
        }))

    def test_temperature_not_advertised_in_legacy_booking(self):
        self.assertNotIn("Температура в салоне", self.html)
        self.assertNotIn("pdTemperatureLayoutFix", self.html)

    def test_pilot_passenger_switch_not_visible(self):
        self.assertIn("#pdPilotPassenger{display:none!important}", self.html)
        self.assertIn("passenger.classList.add('hidden');", self.pilot)

    def test_gps_stopped_when_trip_window_closes(self):
        self.assertIn("function cleanDialog(){stopPosition();closing(false);", self.runtime)

if __name__ == "__main__":
    unittest.main()
