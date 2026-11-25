from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pd_dispatch_qa_store import PILOTS, StagingTripStore
from test_sync_server.pd_demo_server import TripError


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = StagingTripStore(Path(directory.name) / "test.sqlite")
        self.addCleanup(self.store.close)
        self.now = 100
        timer = patch("pd_dispatch_qa_store.time.monotonic", side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)

    def order(self, owner):
        return self.store.create(owner, {"from": "A", "to": "B"})

    def pilot_ready(self, pilot):
        self.store.ping_pilot(pilot)
        self.store.set_pilot_position(pilot, [54.69, 25.28])

    def test_offers_reserve_pilots_before_confirmation(self):
        first = self.order("passenger_a")
        second = self.order("passenger_b")
        third = self.order("passenger_c")
        for pilot in PILOTS:
            self.pilot_ready(pilot)
        self.assertIsNone(self.store.pilot_offer(PILOTS[0]))

        self.store.set_autopilot(True)
        first_offer = self.store.pilot_offer(PILOTS[0])
        second_offer = self.store.pilot_offer(PILOTS[1])
        self.assertEqual(first_offer["trip_id"], first["id"])
        self.assertEqual(second_offer["trip_id"], second["id"])
        self.assertEqual(first_offer["seconds_left"], 20)
        self.assertEqual(self.store.current("passenger", "passenger_a")["status"], "requested")
        self.assertIsNone(self.store.current("pilot", PILOTS[0]))
        self.assertFalse(next(t for t in self.store.snapshot()["trips"]
                              if t["id"] == third["id"])["awaiting_response"])

        with self.assertRaises(TripError):
            self.store.respond_offer(first["id"], PILOTS[1], first_offer["id"], "accept")
        self.store.respond_offer(first["id"], PILOTS[0], first_offer["id"], "accept")
        self.assertEqual(self.store.current("passenger", "passenger_a")["status"], "assigned")
        self.store.set_autopilot(False)
        self.assertIsNone(self.store.pilot_offer(PILOTS[1]))
        with self.assertRaises(TripError):
            self.store.respond_offer(second["id"], PILOTS[1], second_offer["id"], "accept")
        self.assertEqual(self.store.current("passenger", "passenger_a")["status"], "assigned")

    def test_decline_and_timeout_offer_the_order_to_the_next_pilot(self):
        for answer in ("decline", "timeout"):
            with self.subTest(answer=answer):
                self.store.set_autopilot(False)
                first = self.order(f"passenger_{answer}")
                self.pilot_ready(PILOTS[0])
                self.pilot_ready(PILOTS[1])
                self.store.set_autopilot(True)
                offer = self.store.pilot_offer(PILOTS[0])
                self.assertEqual(offer["trip_id"], first["id"])
                if answer == "decline":
                    self.store.respond_offer(first["id"], PILOTS[0], offer["id"], "decline")
                else:
                    self.now += 10
                    self.pilot_ready(PILOTS[0])
                    self.pilot_ready(PILOTS[1])
                    self.now += 10
                next_offer = self.store.pilot_offer(PILOTS[1])
                self.assertEqual(next_offer["trip_id"], first["id"])
                self.assertNotEqual(next_offer["id"], offer["id"])
                with self.assertRaises(TripError):
                    self.store.respond_offer(first["id"], PILOTS[0], offer["id"], "accept")
                self.store.respond_offer(first["id"], PILOTS[1], next_offer["id"], "accept")
                self.assertEqual(self.store.current("passenger", f"passenger_{answer}")["pilot"], PILOTS[1])
                for version in (2, 3, 4):
                    self.store.advance(first["id"], PILOTS[1], version, "advance")
                # Rotate the least-recently assigned order back to the first pilot.
                self.store.last_assignment.clear()

    def test_assignment_source_stays_in_dispatcher_view(self):
        trip = self.order("passenger_a")
        self.pilot_ready(PILOTS[0])
        self.store.set_autopilot(True)
        offer = self.store.pilot_offer(PILOTS[0])
        self.store.respond_offer(trip["id"], PILOTS[0], offer["id"], "accept")

        self.assertTrue(self.store.snapshot()["trips"][0]["auto_assigned"])
        for role, actor in (("pilot", PILOTS[0]), ("passenger", "passenger_a")):
            with self.subTest(role=role):
                self.assertNotIn("auto_assigned", self.store.current(role, actor))
                events = self.store.mobile_events(trip["id"], role, actor, 0)
                self.assertEqual(events[-1]["event"], "assigned")
                self.assertEqual(events[-1]["actor"], "dispatcher_test")
        history = self.store.events(trip["id"], "dispatcher", "tester", 0)
        self.assertEqual(history[-1]["actor"], "autopilot_qa")

    def test_route_changes_invalidate_pending_offers_and_reach_the_pilot(self):
        trip = self.order("passenger_a")
        self.pilot_ready(PILOTS[0])
        self.store.set_autopilot(True)
        offer = self.store.pilot_offer(PILOTS[0])
        route = {"from": "New pickup", "to": "New destination",
                 "stops": ["Stop 1", "Stop 2", "Stop 3"], "version": 1}
        with self.assertRaises(TripError):
            self.store.update_route(trip["id"], "someone_else", route)
        with self.assertRaises(TripError):
            self.store.update_route(trip["id"], "passenger_a", {**route, "stops": ["S"] * 4})
        changed = self.store.update_route(trip["id"], "passenger_a", route)
        self.assertEqual(changed["stops"], route["stops"])
        self.assertEqual(changed["version"], 2)
        with self.assertRaises(TripError):
            self.store.respond_offer(trip["id"], PILOTS[0], offer["id"], "accept")
        new_offer = self.store.pilot_offer(PILOTS[0])
        self.assertEqual(new_offer["origin"], route["from"])
        self.store.respond_offer(trip["id"], PILOTS[0], new_offer["id"], "accept")
        self.assertEqual(self.store.current("pilot", PILOTS[0])["stops"], route["stops"])
        self.assertEqual(self.store.snapshot()["trips"][0]["stops"], route["stops"])

        for version in (3, 4):
            self.store.advance(trip["id"], PILOTS[0], version, "advance")
        with self.assertRaises(TripError):
            self.store.update_route(trip["id"], "passenger_a", {**route, "version": 5, "from": "Another pickup"})
        revised = self.store.update_route(trip["id"], "passenger_a", {**route, "version": 5, "to": "New end"})
        self.assertEqual(revised["destination"], "New end")

    def test_scheduled_trip_stays_available_for_manual_assignment(self):
        trip = self.order("passenger_scheduled")
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO qa_source_imports VALUES (?,?,?,?,?,?)",
                ("telegram_miniapp", "123", trip["id"], "hash", "2099-01-01", "12:00")
            )
        self.pilot_ready(PILOTS[1])
        self.store.set_autopilot(True)
        self.assertEqual(self.store.get(trip["id"], "dispatcher", "tester")["status"], "requested")
        result = self.store.assign_manually(trip["id"], PILOTS[1], trip["version"])
        self.assertEqual(result["pilot"], PILOTS[1])
        self.assertFalse(self.store.snapshot()["trips"][0]["auto_assigned"])


if __name__ == "__main__":
    unittest.main()
