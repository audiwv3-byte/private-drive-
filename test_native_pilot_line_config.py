import os
import unittest
from unittest.mock import patch

from pd_native_pilot_assignment import _pilot_line_database, make_native_pilot_orders_app


class PilotLineConfigTests(unittest.TestCase):
    host = "dpg-dc00pubm8hqs7397rblg-a"
    auth_url = f"postgresql://auth@{host}/private_drive_test"
    line_url = (
        f"postgresql://pd_staging_pilot_line@{host}.frankfurt-postgres.render.com"
        "/private_drive_test?sslmode=require"
    )
    flags = {
        "PD_NATIVE_SMS_ISOLATED": "YES",
        "PD_DISPATCH_STAGING_ONLY": "1",
        "PD_PAYMENT_MODE": "disabled",
    }

    def test_pasted_url_reaches_session_check(self):
        for ending in ("", "\n", "\r\n"):
            with self.subTest(ending=ending), patch.dict(os.environ, {
                **self.flags, "PD_NATIVE_PILOT_LINE_DATABASE_URL": self.line_url + ending
            }, clear=True):
                self.assertEqual(_pilot_line_database(self.auth_url), self.line_url)
                app = make_native_pilot_orders_app(None, self.auth_url)
                for method in ("GET", "PATCH"):
                    statuses = []
                    app({"PATH_INFO": "/native-pilot-availability", "REQUEST_METHOD": method},
                        lambda status, headers: statuses.append(status))
                    self.assertEqual(statuses, ["401 Unauthorized"])

    def test_pasted_url_still_requires_staging_target_role_and_ssl(self):
        for original, replacement in (
            (self.host, "other-host"),
            ("private_drive_test", "other_db"),
            ("pd_staging_pilot_line", "other_user"),
            ("sslmode=require", "sslmode=disable"),
        ):
            url = self.line_url.replace(original, replacement) + "\r\n"
            with self.subTest(original=original), patch.dict(os.environ, {
                **self.flags, "PD_NATIVE_PILOT_LINE_DATABASE_URL": url
            }, clear=True):
                self.assertIsNone(_pilot_line_database(self.auth_url))
