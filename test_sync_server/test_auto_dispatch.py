"""Offline-only tests of the isolated auto-dispatch engine."""
import os
import tempfile
import threading
import unittest

try:
    from .pd_auto_dispatch import IsolatedDispatch, DispatchError
except ImportError:
    from pd_auto_dispatch import IsolatedDispatch, DispatchError


class FakeClock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


class AutoDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock()
        self.store = IsolatedDispatch(os.path.join(self.tmp.name, "dispatch.sqlite"),
                                      clock=self.clock)
        self.store.create_test_order("test_1")

    def candidates(self):
        return [("far", 500), ("near", 90), ("middle", 180),
                ("third", 240), ("next", 600)]

    def test_three_nearest_only_and_expire_after_twenty_seconds(self):
        self.assertEqual(self.store.offer_nearest("test_1", self.candidates(),
                         actor_role="dispatcher"), ["near", "middle", "third"])
        with self.assertRaises(DispatchError):
            self.store.offer_nearest("test_1", self.candidates(),
                                    actor_role="dispatcher")
        self.clock.value += 21
        self.assertEqual(self.store.respond("test_1",
                         authenticated_pilot_id="near", accept=True), "expired")
        self.assertEqual(self.store.offer_nearest("test_1", self.candidates(),
                         actor_role="dispatcher"), ["far", "next"])
        self.assertEqual(self.store.respond("test_1",
                         authenticated_pilot_id="next", accept=True), "accepted")

    def test_decline_does_not_assign(self):
        self.store.offer_nearest("test_1", self.candidates(), actor_role="dispatcher")
        self.assertEqual(self.store.respond("test_1",
                         authenticated_pilot_id="middle", accept=False), "declined")
        order, _ = self.store.snapshot("test_1")
        self.assertIsNone(order["winner"])

    def test_uninvited_pilot_and_non_dispatcher_denied(self):
        with self.assertRaises(DispatchError):
            self.store.offer_nearest("test_1", self.candidates(), actor_role="passenger")
        self.store.offer_nearest("test_1", self.candidates(), actor_role="dispatcher")
        with self.assertRaises(DispatchError):
            self.store.respond("test_1", authenticated_pilot_id="next", accept=True)

    def test_atomic_accept_two_concurrent_pilot_connections(self):
        self.store.offer_nearest("test_1", self.candidates(), actor_role="dispatcher")
        start = threading.Barrier(3)
        outcomes = []
        lock = threading.Lock()

        def accept(pilot):
            engine = IsolatedDispatch(self.store.database_path, clock=self.clock)
            start.wait()
            result = engine.respond("test_1", authenticated_pilot_id=pilot, accept=True)
            with lock:
                outcomes.append(result)

        first = threading.Thread(target=accept, args=("near",))
        second = threading.Thread(target=accept, args=("middle",))
        first.start()
        second.start()
        start.wait()
        first.join(5)
        second.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertCountEqual(outcomes, ["accepted", "already_taken"])
        order, offers = self.store.snapshot("test_1")
        self.assertEqual(order["status"], "assigned")
        self.assertEqual(len([o for o in offers if o["status"] == "accepted"]), 1)
        self.assertEqual(len([o for o in offers if o["status"] == "lost"]), 2)

    def test_idempotent_winner_retry(self):
        self.store.offer_nearest("test_1", self.candidates(), actor_role="dispatcher")
        self.assertEqual(self.store.respond("test_1",
                         authenticated_pilot_id="near", accept=True), "accepted")
        self.assertEqual(self.store.respond("test_1",
                         authenticated_pilot_id="near", accept=True), "already_yours")
        self.assertEqual(self.store.respond("test_1",
                         authenticated_pilot_id="middle", accept=True), "already_taken")


if __name__ == "__main__":
    unittest.main()
