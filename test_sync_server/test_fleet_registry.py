"""Synthetic-only fleet registry eligibility and dispatch tests."""
import os
import tempfile
import unittest

try:
    from .pd_auto_dispatch import DispatchError, IsolatedDispatch
    from .pd_fleet_registry import IsolatedFleetRegistry
except ImportError:
    from pd_auto_dispatch import DispatchError, IsolatedDispatch
    from pd_fleet_registry import IsolatedFleetRegistry


class Clock:
    def __init__(self):
        self.t = 1700000000.0

    def __call__(self):
        return self.t


class FleetRegistryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.clock = Clock()
        self.path = os.path.join(folder.name, "synthetic_fleet.sqlite")
        self.fleet = IsolatedFleetRegistry(self.path, clock=self.clock)
        self.engine = IsolatedDispatch(self.path, clock=self.clock)
        self.fleet.seed_synthetic_identity("dispatcher_1", "dispatcher")
        self.fleet.seed_synthetic_identity("unverified_dispatcher", "dispatcher",
                                           verified=False)
        self.fleet.seed_synthetic_identity("passenger_1", "passenger")
        for pilot in ("pilot_a", "pilot_b", "pilot_c", "pilot_d",
                      "pilot_e", "pilot_unverified"):
            self.fleet.seed_synthetic_identity(
                pilot, "pilot", verified=pilot != "pilot_unverified")

    def activate(self, pilot, *, busy=False):
        self.fleet.set_approval(pilot, authenticated_dispatcher="dispatcher_1",
                                approved=True)
        self.fleet.update_presence(authenticated_pilot=pilot, online=True,
                                   vehicle_ready=True, busy=busy,
                                   gps=(54.7, 25.3))

    def test_only_three_available_approved_nearest_are_offered(self):
        for p in ("pilot_a", "pilot_b", "pilot_c", "pilot_d"):
            self.activate(p)
        self.activate("pilot_e", busy=True)
        self.engine.create_test_order("synthetic_trip")
        candidates = {"pilot_d": 400, "pilot_b": 100,
                      "pilot_a": 200, "pilot_c": 300, "pilot_e": 1}
        self.assertEqual(self.fleet.offer_nearest_synthetic(
            "synthetic_trip", authenticated_dispatcher="dispatcher_1",
            trusted_road_etas=candidates),
            ["pilot_b", "pilot_a", "pilot_c"])
        order, offers = self.engine.snapshot("synthetic_trip")
        self.assertEqual(order["status"], "offered")
        self.assertEqual(len(offers), 3)
        self.assertTrue(all(o["deadline"] == self.clock.t + 20 for o in offers))

    def test_unapproved_offline_busy_no_vehicle_and_stale_gps_are_filtered(self):
        self.activate("pilot_a")
        self.activate("pilot_b")
        self.activate("pilot_c")
        self.fleet.update_presence(authenticated_pilot="pilot_b", online=False)
        self.fleet.update_presence(authenticated_pilot="pilot_c", busy=True)
        self.assertEqual([p for p, _ in self.fleet.eligible_by_road_eta(
            authenticated_dispatcher="dispatcher_1",
            road_etas={"pilot_a": 80, "pilot_b": 10, "pilot_c": 30,
                       "pilot_d": 20})], ["pilot_a"])
        self.fleet.update_presence(authenticated_pilot="pilot_a",
                                   vehicle_ready=False)
        self.assertEqual(self.fleet.eligible_by_road_eta(
            authenticated_dispatcher="dispatcher_1",
            road_etas={"pilot_a": 80}), [])
        self.fleet.update_presence(authenticated_pilot="pilot_a",
                                   vehicle_ready=True)
        self.clock.t += 90
        self.assertEqual(self.fleet.eligible_by_road_eta(
            authenticated_dispatcher="dispatcher_1",
            road_etas={"pilot_a": 80}), [])
        self.fleet.update_presence(authenticated_pilot="pilot_a",
                                   gps=(54.7001, 25.3001))
        self.assertEqual(len(self.fleet.eligible_by_road_eta(
            authenticated_dispatcher="dispatcher_1",
            road_etas={"pilot_a": 80})), 1)

    def test_role_boundaries_and_verified_identity(self):
        self.activate("pilot_a")
        for actor in ("passenger_1", "pilot_a", "unverified_dispatcher"):
            with self.assertRaises(DispatchError):
                self.fleet.eligible_by_road_eta(
                    authenticated_dispatcher=actor,
                    road_etas={"pilot_a": 20})
            with self.assertRaises(DispatchError):
                self.fleet.set_approval("pilot_a",
                    authenticated_dispatcher=actor, approved=False)
        with self.assertRaises(DispatchError):
            self.fleet.set_approval("pilot_unverified",
                authenticated_dispatcher="dispatcher_1", approved=True)
        with self.assertRaises(DispatchError):
            self.fleet.update_presence(authenticated_pilot="pilot_unverified",
                online=True)
        with self.assertRaises(DispatchError):
            self.fleet.update_presence(authenticated_pilot="passenger_1",
                online=True)

    def test_invalid_gps_and_invalid_road_eta_rejected(self):
        for bad in ((91, 25), (0, 181), (float("nan"), 5),
                    ("54.7", 25), (54.7,)):
            with self.assertRaises(DispatchError):
                self.fleet.update_presence(authenticated_pilot="pilot_a",
                    gps=bad)
        self.activate("pilot_a")
        for invalid in (float("nan"), -1, float("inf"), "40", True):
            with self.assertRaises(DispatchError):
                self.fleet.eligible_by_road_eta(
                    authenticated_dispatcher="dispatcher_1",
                    road_etas={"pilot_a": invalid})

    def test_revocation_excludes_pilot_and_manual_assignment_untouched(self):
        self.activate("pilot_a")
        self.fleet.set_approval("pilot_a",
            authenticated_dispatcher="dispatcher_1", approved=False)
        self.assertEqual(self.fleet.eligible_by_road_eta(
            authenticated_dispatcher="dispatcher_1",
            road_etas={"pilot_a": 10}), [])
        # Preserve the standalone synthetic dispatch engine behavior without
        # registry tables. Registered fleet mode correctly rejects unknown IDs.
        with tempfile.TemporaryDirectory() as standalone:
            manual = IsolatedDispatch(os.path.join(standalone, "manual.sqlite"),
                                      clock=self.clock)
            manual.create_test_order("manual_fixture")
            self.assertEqual(manual.offer_nearest(
                "manual_fixture", [("manual_pilot", 40)], actor_role="dispatcher"),
                ["manual_pilot"])


if __name__ == "__main__":
    unittest.main()
