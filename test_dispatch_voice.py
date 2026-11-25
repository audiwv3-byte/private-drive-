import base64
import hashlib
import hmac
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pd_dispatch_voice import StagingVoiceCalls
from test_sync_server.pd_demo_server import DemoStore, TripError


class DispatchVoiceTests(unittest.TestCase):
    def test_only_assigned_pair_can_join_an_accepted_audio_call(self):
        with TemporaryDirectory() as directory:
            store = DemoStore(Path(directory) / "trip.sqlite")
            voice = StagingVoiceCalls(store, "wss://voice.example.test", "test-key", "test-secret")
            trip = store.create("passenger", {"from": "A", "to": "B"})
            trip_id = trip["id"]
            with self.assertRaises(TripError):
                voice.handle(trip_id, "passenger", "passenger", {"action": "invite"})
            store.assign(trip_id, "pilot", trip["version"], "dispatcher")
            call = voice.handle(trip_id, "passenger", "passenger", {"action": "invite"})["call"]
            self.assertEqual(call["state"], "ringing")
            for role, actor in (("pilot", "another-pilot"), ("dispatcher", "dispatcher"),
                                ("passenger", "another-passenger")):
                with self.assertRaises(TripError):
                    voice.handle(trip_id, role, actor)
            action = {"id": call["id"], "action": "join"}
            with self.assertRaises(TripError):
                voice.handle(trip_id, "pilot", "pilot", action)
            accepted = voice.handle(
                trip_id, "pilot", "pilot", {**action, "action": "accept"}
            )
            self.assertEqual(accepted["call"]["state"], "accepted")
            users = set()
            for role in ("pilot", "passenger"):
                response = voice.handle(trip_id, role, role, action)
                self.assertEqual(response["url"], "wss://voice.example.test")
                header, payload, signature = response["token"].split(".")
                actual = base64.urlsafe_b64decode(signature + "=")
                expected = hmac.new(b"test-secret", f"{header}.{payload}".encode(),
                                    hashlib.sha256).digest()
                self.assertTrue(hmac.compare_digest(actual, expected))
                claims = json.loads(base64.urlsafe_b64decode(payload + "==="))
                self.assertEqual(claims["video"]["room"], call["id"])
                self.assertEqual(claims["video"]["canPublishSources"], ["microphone"])
                self.assertFalse(claims["video"]["canPublishData"])
                users.add(claims["sub"])
            self.assertEqual(len(users), 2)
            voice.handle(trip_id, "passenger", "passenger", {**action, "action": "end"})
            self.assertIsNone(voice.handle(trip_id, "pilot", "pilot")["call"])
            with self.assertRaises(TripError):
                voice.handle(trip_id, "pilot", "pilot", action)


if __name__ == "__main__":
    unittest.main()
