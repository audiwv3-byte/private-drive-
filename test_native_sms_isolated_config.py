"""No-network tests of protected config for isolated SMS sign-in."""
import io
import json
import os
import tempfile
import unittest

from pd_native_sms_isolated_config import make_isolated_sms_app


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {
            "PD_NATIVE_SMS_ISOLATED": "YES",
            "PD_NATIVE_SMS_DB": os.path.join(self.tmp.name, "test.sqlite"),
        }

    def new_app(self, config):
        return make_isolated_sms_app(
            environ=config,
            start_sms=lambda phone: None,
            check_sms=lambda phone, code: code == "123456",
            clock=lambda: 1000,
        )

    @staticmethod
    def call(app, path, payload):
        encoded = json.dumps(payload).encode()
        statuses = []
        body = b"".join(app({
            "PATH_INFO": path, "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(encoded)),
            "wsgi.input": io.BytesIO(encoded), "REMOTE_ADDR": "127.0.0.1",
        }, lambda status, headers: statuses.append(status)))
        return int(statuses[0][:3]), json.loads(body)

    def login(self, app, phone):
        status, started = self.call(app, "/native-auth/request-code",
            {"channel": "phone", "destination": phone, "role": "admin"})
        self.assertEqual(status, 202)
        status, logged = self.call(app, "/native-auth/verify-code",
            {"challenge_id": started["challenge_id"], "code": "123456",
             "role": "admin"})
        self.assertEqual(status, 200)
        return logged

    def test_admin_provisioned_privately_passenger_default(self):
        config = dict(self.config, PD_NATIVE_ADMIN_PHONE="+37061111111")
        app, db = self.new_app(config)
        self.addCleanup(db.close)
        self.assertEqual(self.login(app, "+37061111111")["role"], "admin")
        self.assertEqual(self.login(app, "+37062222222")["role"], "passenger")
        self.assertEqual(self.login(app, "+37063333333")["role"], "passenger")

    def test_staff_roles_are_provisioned_only_on_the_server(self):
        config = dict(self.config, PD_NATIVE_PILOT_PHONE="+37061111111",
                      PD_NATIVE_DISPATCHER_PHONE="+37062222222")
        app, db = self.new_app(config)
        self.addCleanup(db.close)
        self.assertEqual(self.login(app, "+37061111111")["role"], "pilot")
        self.assertEqual(self.login(app, "+37062222222")["role"], "dispatcher")
        self.assertEqual(self.login(app, "+37063333333")["role"], "passenger")

    def test_existing_admin_can_also_be_provisioned_as_pilot(self):
        config = dict(self.config, PD_NATIVE_ADMIN_PHONE="+37061111111",
                      PD_NATIVE_PILOT_PHONE="+37061111111")
        app, db = self.new_app(config)
        self.addCleanup(db.close)
        self.assertEqual(self.login(app, "+37061111111")["role"], "pilot_dispatcher")

    def test_admin_not_enabled_without_private_setting(self):
        app, db = self.new_app(self.config)
        self.addCleanup(db.close)
        self.assertEqual(self.login(app, "+37061111111")["role"], "passenger")

    def test_fail_closed_without_isolated_opt_in_and_safe_storage(self):
        for config in (
            {**self.config, "PD_NATIVE_SMS_ISOLATED": "NO"},
            {**self.config, "PD_NATIVE_SMS_DB": ":memory:"},
            {**self.config, "PD_NATIVE_SMS_DB": "relative.sqlite"},
            {**self.config, "PD_NATIVE_ADMIN_PHONE": "invalid"},
        ):
            with self.assertRaises((ValueError, RuntimeError)):
                self.new_app(config)

    def test_real_sms_disabled_without_live_opt_in(self):
        with self.assertRaises(RuntimeError):
            make_isolated_sms_app(environ=self.config)
        with self.assertRaises(RuntimeError):
            make_isolated_sms_app(environ={
                **self.config, "PD_NATIVE_SMS_LIVE": "YES",
                "TWILIO_VERIFY_ENABLED": "true",
            })


if __name__ == "__main__":
    unittest.main()
