"""Readiness gate rate-limit regression tests, no database connections."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from pd_native_auth_schema_readiness import SchemaReadinessGate


class SchemaRecoveryRateLimitTests(unittest.TestCase):
    def test_failure_throttled_until_interval_then_recovers(self):
        now=[100.0]
        statuses=iter(((False,"database_unavailable"),(True,"ready")))
        calls=[]
        def probe(url):
            calls.append(url)
            return next(statuses)
        gate=SchemaReadinessGate("synthetic-only",monotonic=lambda:now[0],
                                 inspector=probe,retry_seconds=15)
        self.assertEqual(gate.status(),(False,"database_unavailable"))
        for _ in range(30):
            self.assertEqual(gate.status(),(False,"database_unavailable"))
        self.assertEqual(len(calls),1)
        now[0]+=14.99
        self.assertFalse(gate.status()[0])
        self.assertEqual(len(calls),1)
        now[0]+=0.01
        self.assertEqual(gate.status(),(True,"ready"))
        self.assertEqual(len(calls),2)

    def test_connection_error_cached_without_secret_leak(self):
        now=[0]
        count=[]
        def fail(url):
            count.append(1)
            raise RuntimeError("sensitive-dsn-should-not-leak")
        gate=SchemaReadinessGate("sensitive-dsn-should-not-leak",
                                 monotonic=lambda:now[0],inspector=fail)
        for i in range(25):
            self.assertEqual(gate.status(),(False,"database_unavailable"))
        self.assertEqual(len(count),1)

    def test_concurrent_requests_share_one_probe(self):
        now=[100]
        count=[]
        def probe(url):
            count.append(1)
            return (True,"ready")
        gate=SchemaReadinessGate("synthetic-only",monotonic=lambda:now[0],inspector=probe)
        with ThreadPoolExecutor(max_workers=16) as pool:
            results=list(pool.map(lambda i:gate.status(),range(50)))
        self.assertEqual(len(count),1)
        self.assertTrue(all(x==(True,"ready") for x in results))

    def test_runtime_failure_is_fail_closed_and_throttled(self):
        now=[100]
        probes=[]
        def probe(url):
            probes.append(1)
            return (True,"ready")
        gate=SchemaReadinessGate("synthetic-only",monotonic=lambda:now[0],inspector=probe)
        self.assertTrue(gate.status()[0])
        gate.mark_database_unavailable()
        self.assertEqual(gate.status(),(False,"database_unavailable"))
        self.assertEqual(len(probes),1)
        now[0]+=15
        self.assertEqual(gate.status(),(True,"ready"))
        self.assertEqual(len(probes),2)

    def test_interval_cannot_be_disabled(self):
        with self.assertRaises(ValueError):
            SchemaReadinessGate("synthetic-only",retry_seconds=0)


if __name__=="__main__":
    unittest.main()
