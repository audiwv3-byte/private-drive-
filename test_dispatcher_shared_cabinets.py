"""Exercise the existing authenticated web cabinet against the mobile QA API."""

import json
import os
import re
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flask import Flask
from werkzeug.security import generate_password_hash

from pd_native_cabinet_mock import CabinetStore, PHOTO, make_mock_server, utc_now
from pd_web_dispatcher import register


class SharedCabinetsTests(unittest.TestCase):
    def mobile(self, path, *, token=None, payload=None, status=200):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(f"http://127.0.0.1:{self.api.server_port}{path}", data=data, headers=headers)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def setUp(self):
        store = CabinetStore(":memory:")
        self.addCleanup(store.close)
        self.api = make_mock_server(store, lambda *_: None, isolated_qa_auth=True)
        self.addCleanup(self.api.server_close)
        worker = threading.Thread(target=self.api.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.api.shutdown)
        self.dispatcher_token = self.mobile("/native-auth/qa-session", payload={
            "role": "dispatcher",
        })["access_token"]
        self.passenger = self.mobile("/native-auth/qa-session", payload={
            "role": "passenger",
        })["access_token"]
        self.pilot = self.mobile("/native-auth/qa-session", payload={
            "role": "pilot",
        })["access_token"]

    def test_existing_dispatch_login_connects_to_mobile_order_gps_and_chat(self):
        config = {
            "PD_DISPATCH_STAGING_ONLY": "1",
            "PD_DISPATCH_SESSION_SECRET": "synthetic-test-dispatcher-session-secret",
            "PD_DISPATCH_ADMIN_ID": "1",
            "PD_DISPATCH_PASSWORD_HASH": generate_password_hash("synthetic-only-password"),
            "PD_DISPATCH_SHARED_QA": "1",
            "PD_DISPATCH_SHARED_QA_PORT": str(self.api.server_port),
            "PD_DISPATCH_SHARED_QA_TOKEN": self.dispatcher_token,
        }
        with patch.dict(os.environ, config, clear=True):
            app = Flask(__name__)
            register(app, SimpleNamespace(ADMIN_IDS={1}, is_admin=lambda uid: uid == 1))
            browser = app.test_client()
            browser_origin = "https://dispatcher.test"
            state_path = "/dispatch/test-sync/state"
            self.assertEqual(browser.get(state_path, base_url=browser_origin).status_code, 401)
            self.mobile("/v1/dispatch/state", token=self.passenger, status=403)
            login = browser.get("/dispatch/login", base_url=browser_origin)
            csrf = re.search(rb'name="csrf" value="([^"]+)"', login.data)[1].decode()
            logged_in = browser.post("/dispatch/login", base_url=browser_origin, data={
                "password": "synthetic-only-password", "csrf": csrf,
            })
            self.assertEqual(logged_in.status_code, 302)
            dashboard = browser.get("/dispatch", base_url=browser_origin)
            self.assertEqual(dashboard.status_code, 200)
            self.assertIn(b'id="orderChat"', dashboard.data)
            self.assertNotIn(self.dispatcher_token.encode(), dashboard.data)
            csrf = re.search(rb'name="csrf" value="([^"]+)"', dashboard.data)[1].decode()

            self.mobile("/native-identity/submit", token=self.pilot, payload={"photo": PHOTO})
            photo = self.mobile("/native-identity/queue", token=self.dispatcher_token)["items"][0]["id"]
            self.mobile(f"/native-identity/decision/{photo}", token=self.dispatcher_token,
                        payload={"decision": "approved"})
            trip = self.mobile("/v1/trips", token=self.passenger, status=201, payload={
                "from": "Synthetic pickup", "to": "Synthetic destination",
                "departure": utc_now().isoformat(), "client_id": uuid.uuid4().hex,
            })["trip"]
            trip_id = trip["id"]
            self.mobile("/v1/gps", token=self.pilot, payload={
                "online": True, "latitude": 54.7, "longitude": 25.3, "seen_at": utc_now().isoformat(),
            })
            self.mobile(f"/v1/trips/{trip_id}/passenger-position", token=self.passenger,
                        payload={"latitude": 54.69, "longitude": 25.27})
            board = browser.get(state_path, base_url=browser_origin).get_json()
            self.assertEqual(board["trips"][0]["id"], trip_id)
            self.assertEqual(board["pilot_position"], [54.7, 25.3])
            self.assertEqual(board["passenger_positions"][trip_id]["latitude"], 54.69)

            assign = "/dispatch/test-sync/assign"
            fields = {"trip_id": trip_id, "version": trip["version"]}
            self.assertEqual(browser.post(assign, base_url=browser_origin, data=fields).status_code, 403)
            assigned = browser.post(assign, base_url=browser_origin, data={**fields, "csrf": csrf})
            self.assertEqual(assigned.status_code, 200)
            assigned_trip = self.mobile("/v1/current", token=self.pilot)["trip"]
            self.assertEqual((assigned_trip["id"], assigned_trip["status"]), (trip_id, "assigned"))

            api_messages = f"/v1/trips/{trip_id}/messages"
            web_messages = f"/dispatch/test-sync/trips/{trip_id}/messages"
            self.mobile(api_messages, token=self.passenger, status=201, payload={
                "client_id": uuid.uuid4().hex, "text": "Synthetic passenger message",
            })
            self.assertEqual(browser.get(web_messages, base_url=browser_origin).get_json()["messages"][0]["role"],
                             "passenger")
            sent = browser.post(web_messages, base_url=browser_origin, data={
                "csrf": csrf, "client_id": uuid.uuid4().hex, "text": "Synthetic dispatcher reply",
            })
            self.assertEqual(sent.status_code, 201)
            messages = self.mobile(api_messages, token=self.passenger)["messages"]
            self.assertEqual([row["role"] for row in messages], ["passenger", "dispatcher"])
