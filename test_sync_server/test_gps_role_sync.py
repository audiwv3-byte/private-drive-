"""Isolated localhost integration tests: pilot GPS never fabricated or leaked."""
import hashlib
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pd_demo_server import ApiServer, DemoStore

TOKENS = {"passenger": "p"*40, "pilot": "d"*40,
          "dispatcher": "a"*40, "stranger": "q"*40}


class GpsRoleSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "gps.sqlite")
        self.store = DemoStore(self.path)
        credentials = {hashlib.sha256(v.encode()).digest(): (
            "passenger" if k == "stranger" else k, k+"_test")
            for k, v in TOKENS.items()}
        self.server = ApiServer(("127.0.0.1", 0), self.store, credentials)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self.tmp.cleanup()

    def req(self, method, path, role="passenger", data=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Authorization": "Bearer " + TOKENS[role]}
        raw = json.dumps(data).encode() if data is not None else None
        if raw is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=headers)
        res = conn.getresponse()
        output = res.status, json.loads(res.read())
        conn.close()
        return output

    def assigned(self):
        code, response = self.req("POST", "/v1/trips",
            data={"from":"Synthetic A","to":"Synthetic B"})
        self.assertEqual(code, 201)
        tid = response["trip"]["id"]
        self.assertEqual(self.req("POST", f"/v1/trips/{tid}/assign",
            "dispatcher", {"pilot":"pilot_test","version":1})[0], 200)
        return tid

    def test_no_fake_gps_role_access_and_opt_in(self):
        tid = self.assigned()
        endpoint = f"/v1/trips/{tid}/gps"
        for role in ("passenger", "pilot", "dispatcher"):
            self.assertEqual(self.req("GET", endpoint, role)[1]["gps"],
                             {"available": False})
        self.assertEqual(self.req("GET", endpoint, "stranger")[0], 404)
        payload = {"enabled": True,"latitude":54.6872,"longitude":25.2797}
        self.assertEqual(self.req("POST", endpoint, "passenger", payload)[0],403)
        self.assertEqual(self.req("POST", endpoint, "dispatcher", payload)[0],403)
        self.assertEqual(self.req("POST", endpoint, "pilot", payload)[0],200)
        for role in ("passenger", "dispatcher", "pilot"):
            gps = self.req("GET", endpoint, role)[1]["gps"]
            self.assertEqual(gps["available"], True)
            self.assertEqual(gps["latitude"], 54.6872)
        self.assertEqual(self.req("POST", endpoint, "pilot", {"enabled":False})[0],200)
        self.assertEqual(self.req("GET", endpoint, "passenger")[1]["gps"],
                         {"available":False})

    def test_invalid_coordinates_stale_and_server_restart(self):
        tid = self.assigned()
        endpoint = f"/v1/trips/{tid}/gps"
        for lat, lng in ((999,25), (54,181), (True,25), ("54",25), (float("nan"),25)):
            self.assertEqual(self.req("POST", endpoint, "pilot",
                {"enabled":True,"latitude":lat,"longitude":lng})[0],400)
            self.assertEqual(self.req("GET", endpoint, "dispatcher")[1]["gps"],
                             {"available":False})
        self.assertEqual(self.req("POST", endpoint,"pilot",
            {"enabled":True,"latitude":54.6,"longitude":25.2})[0],200)
        self.store.close()
        self.store = DemoStore(self.path)
        self.server.store = self.store
        self.assertEqual(self.req("GET", endpoint, "passenger")[1]["gps"]["available"],True)
        with self.store.db:
            self.store.db.execute("UPDATE pilot_gps SET updated_at=? WHERE trip_id=?",
                                  (time.time()-31,tid))
        self.assertEqual(self.req("GET", endpoint, "passenger")[1]["gps"],
                         {"available":False})

    def test_unassigned_pilot_and_finished_order_never_publish(self):
        code, created = self.req("POST", "/v1/trips",
            data={"from":"A","to":"B"})
        tid=created["trip"]["id"]
        endpoint=f"/v1/trips/{tid}/gps"
        fix={"enabled":True,"latitude":54.7,"longitude":25.3}
        self.assertEqual(self.req("POST",endpoint,"pilot",fix)[0],404)
        self.assertEqual(self.req("POST",f"/v1/trips/{tid}/assign","dispatcher",
            {"pilot":"pilot_test","version":1})[0],200)
        self.assertEqual(self.req("POST",endpoint,"pilot",fix)[0],200)
        for version in (2,3,4):
            self.assertEqual(self.req("POST",f"/v1/trips/{tid}/action","pilot",
                {"action":"advance","version":version})[0],200)
        self.assertEqual(self.req("GET",endpoint,"dispatcher")[1]["gps"],
                         {"available":False})
        self.assertEqual(self.req("POST",endpoint,"pilot",fix)[0],409)


if __name__ == "__main__":
    unittest.main()
