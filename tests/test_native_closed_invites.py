import hashlib
import io
import json
import unittest
from wsgiref.util import setup_testing_defaults

from pd_native_closed_invites import (
    INVITE_PATH, InviteStorageUnavailable, make_closed_invites_app,
)

STAGING = "postgresql://127.0.0.1/private_drive_test"
FLAGS = {
    "PD_NATIVE_CLOSED_PILOT_INVITES": "1",
    "PD_NATIVE_SMS_ISOLATED": "YES",
    "PD_PAYMENT_MODE": "disabled",
}
INVITE_CODE = "x" * 43
ACCESS_TOKEN = "y" * 64


def request(app, *, payload=None, body=None, path=INVITE_PATH, method="POST",
            content_type="application/json", query=""):
    if body is None:
        body = json.dumps({"invite_code": INVITE_CODE} if payload is None
                          else payload).encode("utf-8")
    captured = {}
    env = {}
    setup_testing_defaults(env)
    env.update(PATH_INFO=path, REQUEST_METHOD=method,
               CONTENT_LENGTH=str(len(body)), CONTENT_TYPE=content_type,
               QUERY_STRING=query, **{"wsgi.input": io.BytesIO(body)})
    def start(status, headers):
        captured.update(status=int(status[:3]), headers=dict(headers))
    captured["body"] = json.loads(b"".join(app(env, start)))
    return captured


def fallback(env, start):
    start("404 Not Found", [("Content-Type", "application/json")])
    return [b'{"error":"not_found"}']


class ClosedInviteHttpTests(unittest.TestCase):
    def setUp(self):
        self.exchange_calls = []
        self.now = 100.0
        self.result = ("opaque-user", "passenger", 604900)

    def exchange(self, *args):
        self.exchange_calls.append(args)
        return self.result

    def app(self, *, env=FLAGS, database_url=STAGING, exchange=None):
        return make_closed_invites_app(
            fallback, database_url, environ=env,
            exchange=exchange or self.exchange, token=lambda n: ACCESS_TOKEN,
            monotonic=lambda: self.now,
        )

    def test_closed_default_and_wrong_target(self):
        for config in (
            {},
            {**FLAGS, "PD_NATIVE_SMS_LIVE": "YES"},
            {**FLAGS, "TWILIO_VERIFY_ENABLED": "true"},
            {**FLAGS, "PD_PAYMENT_MODE": "live"},
            {**FLAGS, "PD_NATIVE_SMS_ISOLATED": "NO"},
        ):
            self.assertEqual(request(self.app(env=config))["status"], 404)
        for url in (STAGING.replace("private_drive_test", "private_drive"), STAGING + "?dbname=prod"):
            self.assertEqual(request(self.app(database_url=url))["status"], 404)
        self.assertEqual(self.exchange_calls, [])

    def test_session_created_passenger_only_no_store_and_only_hashes_reach_db(self):
        app = self.app()
        response = request(app)
        self.assertEqual(response["status"], 200)
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")
        self.assertEqual(response["body"], {
            "user_id": "opaque-user", "role": "passenger", "expires_at": 604900,
            "access_token": ACCESS_TOKEN, "token_type": "Bearer",
        })
        self.assertEqual(self.exchange_calls, [
            (STAGING, hashlib.sha256(INVITE_CODE.encode()).hexdigest(),
             hashlib.sha256(ACCESS_TOKEN.encode()).hexdigest()),
        ])

    def test_rejects_client_roles_query_body_transport_and_non_post(self):
        app = self.app()
        for args in (
            dict(payload={"invite_code": INVITE_CODE, "role": "admin"}),
            dict(payload={"invite_code": "123456"}),
            dict(body=b"\xff"),
            dict(body=b"x"*257),
            dict(content_type="text/plain"),
            dict(query="invite_code=unused"),
        ):
            self.assertEqual(request(app, **args)["status"], 400)
        self.assertEqual(request(app, method="GET")["status"], 405)
        self.assertEqual(request(app, path="/native-auth/session")["status"], 404)
        self.assertEqual(self.exchange_calls, [])

    def test_rejects_unknown_or_non_passenger_and_hides_store_failure(self):
        app = self.app()
        for data in (None, ("opaque", "admin", 123)):
            self.result = data
            self.assertEqual(request(app)["body"], {"error": "invalid_or_expired_invite"})

        def fail(*args):
            raise InviteStorageUnavailable("private connection detail")
        response = request(self.app(exchange=fail))
        self.assertEqual((response["status"], response["body"]),
                         (503, {"error": "invite_service_unavailable"}))

    def test_bounded_rate_limit_does_not_hit_db_and_replenishes(self):
        app = self.app()
        self.result = None
        for _ in range(25):
            self.assertEqual(request(app)["status"], 401)
        self.assertEqual(request(app)["status"], 429)
        self.assertEqual(len(self.exchange_calls), 25)
        self.now += .5
        self.assertEqual(request(app)["status"], 401)


if __name__ == "__main__":
    unittest.main()
