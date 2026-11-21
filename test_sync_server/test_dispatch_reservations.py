"""Offline synthetic tests for atomic reservations across different trips."""
import os
import sqlite3
import tempfile
import threading
import unittest

try:
    from .pd_auto_dispatch import IsolatedDispatch, DispatchError
    from .pd_fleet_registry import IsolatedFleetRegistry
except ImportError:
    from pd_auto_dispatch import IsolatedDispatch, DispatchError
    from pd_fleet_registry import IsolatedFleetRegistry


class Clock:
    def __init__(self):
        self.now = 1700000000.0

    def __call__(self):
        return self.now


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "synthetic.sqlite")
        self.clock = Clock()
        self.fleet = IsolatedFleetRegistry(self.path, clock=self.clock)
        self.fleet.seed_synthetic_identity("dispatcher_1", "dispatcher")
        self.fleet.seed_synthetic_identity("passenger_1", "passenger")
        self.fleet.seed_synthetic_identity("pilot_1", "pilot")
        self.fleet.seed_synthetic_identity("pilot_2", "pilot")
        for pilot in ("pilot_1", "pilot_2"):
            self.fleet.set_approval(pilot, authenticated_dispatcher="dispatcher_1",
                                    approved=True)
            self.fleet.update_presence(authenticated_pilot=pilot, online=True,
                                       vehicle_ready=True, busy=False,
                                       gps=(54.6872, 25.2797))
        self.engine = IsolatedDispatch(self.path, clock=self.clock)
        for trip in ("trip_a", "trip_b"):
            self.engine.create_test_order(trip)
            self.engine.offer_nearest(trip, [("pilot_1", 20), ("pilot_2", 50)],
                                      actor_role="dispatcher")

    def test_one_pilot_cannot_win_two_concurrent_orders(self):
        barrier = threading.Barrier(3)
        lock = threading.Lock()
        results = []
        errors = []

        def worker(trip):
            instance = IsolatedDispatch(self.path, clock=self.clock)
            barrier.wait()
            try:
                result = instance.respond(trip,
                    authenticated_pilot_id="pilot_1", accept=True)
                with lock:
                    results.append(result)
            except Exception as error:
                with lock:
                    errors.append(error)

        threads = [threading.Thread(target=worker, args=(trip,))
                   for trip in ("trip_a", "trip_b")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertCountEqual(results, ["accepted", "pilot_unavailable"])
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT pilot_id,order_id FROM dispatch_reservations").fetchall()
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0][0], "pilot_1")
        winner_order = row[0][1]
        loser_order = "trip_b" if winner_order == "trip_a" else "trip_a"
        self.assertEqual(self.engine.snapshot(loser_order)[0]["winner"], None)

    def test_release_requires_verified_dispatcher_and_matching_order(self):
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "accepted")
        for user in ("pilot_1", "passenger_1", "unknown"):
            with self.assertRaises(DispatchError) as ctx:
                self.engine.release_reservation("trip_a",
                    authenticated_dispatcher=user)
            self.assertEqual(ctx.exception.code, "forbidden")
        with self.assertRaises(DispatchError) as ctx:
            self.engine.release_reservation("trip_b",
                authenticated_dispatcher="dispatcher_1")
        self.assertEqual(ctx.exception.code, "not_assigned")
        self.assertEqual(self.engine.release_reservation("trip_a",
                         authenticated_dispatcher="dispatcher_1"), "released")
        self.assertEqual(self.engine.release_reservation("trip_a",
                         authenticated_dispatcher="dispatcher_1"), "already_released")
        self.assertEqual(self.engine.respond("trip_b",
                         authenticated_pilot_id="pilot_1", accept=True), "accepted")

    def test_manual_busy_or_revoked_status_rechecked_before_acceptance(self):
        self.fleet.update_presence(authenticated_pilot="pilot_1", busy=True)
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "pilot_unavailable")
        self.fleet.update_presence(authenticated_pilot="pilot_1", busy=False)
        self.fleet.set_approval("pilot_1", authenticated_dispatcher="dispatcher_1",
                                approved=False)
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "pilot_unavailable")
        self.fleet.set_approval("pilot_1", authenticated_dispatcher="dispatcher_1",
                                approved=True)
        self.clock.now += 90
        # The offer expires in 20 seconds; expiry takes precedence over
        # the stale GPS rejection when the acceptance arrives too late.
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "expired")
        self.fleet.update_presence(authenticated_pilot="pilot_1",
                                   gps=(54.7, 25.3))
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "expired")

    def test_offer_round_revalidates_busy_gps_and_existing_reservation(self):
        self.fleet.update_presence(authenticated_pilot="pilot_2", busy=True)
        self.engine.create_test_order("trip_c")
        offered = self.engine.offer_nearest("trip_c",
                    [("pilot_2", 10), ("pilot_1", 30)], actor_role="dispatcher")
        self.assertEqual(offered, ["pilot_1"])
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "accepted")
        self.engine.create_test_order("trip_d")
        self.assertEqual(self.engine.offer_nearest("trip_d",
                    [("pilot_1", 10)], actor_role="dispatcher"), [])

    def test_reservation_cannot_be_cleared_by_presence_busy_false(self):
        self.assertEqual(self.engine.respond("trip_a",
                         authenticated_pilot_id="pilot_1", accept=True), "accepted")
        self.fleet.update_presence(authenticated_pilot="pilot_1", busy=False)
        self.assertEqual(self.engine.respond("trip_b",
                         authenticated_pilot_id="pilot_1", accept=True), "pilot_unavailable")
        with sqlite3.connect(self.path) as conn:
            reserved = conn.execute("SELECT order_id FROM dispatch_reservations WHERE pilot_id=?",
                                    ("pilot_1",)).fetchone()
        self.assertEqual(reserved[0], "trip_a")


if __name__ == "__main__":
    unittest.main()
