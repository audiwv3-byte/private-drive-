import unittest
from datetime import datetime, timedelta, timezone

try:
    from .pd_identity_check_policy import identity_check_due, proposed_driver_status
except ImportError:
    from pd_identity_check_policy import identity_check_due, proposed_driver_status


class IdentityCheckScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 21, 8, tzinfo=timezone.utc)

    def test_initial_check_required(self):
        self.assertTrue(identity_check_due(None, now=self.now))
        self.assertEqual(proposed_driver_status(None, now=self.now),
                         "verification_required")

    def test_seven_day_boundary(self):
        self.assertFalse(identity_check_due(self.now - timedelta(days=6, hours=23),
                                            now=self.now))
        self.assertTrue(identity_check_due(self.now - timedelta(days=7),
                                           now=self.now))
        self.assertTrue(identity_check_due(self.now - timedelta(days=10),
                                           now=self.now))

    def test_future_or_untrusted_timestamp_requires_recheck(self):
        self.assertTrue(identity_check_due(self.now + timedelta(seconds=1),
                                           now=self.now))
        self.assertTrue(identity_check_due("2026-11-21", now=self.now))
        self.assertTrue(identity_check_due(datetime(2026, 11, 21), now=self.now))

    def test_timezone_aware_equivalence(self):
        local = (self.now - timedelta(days=6)).astimezone(
            timezone(timedelta(hours=2)))
        self.assertFalse(identity_check_due(local, now=self.now))


if __name__ == "__main__":
    unittest.main()
